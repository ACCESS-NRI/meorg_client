"""Methods for downloading files from signed URLs."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath

import requests
from tqdm import tqdm

import meorg_client.constants as mcc
import meorg_client.exceptions as mx


def safe_join(root: Path, relative: str) -> Path:
    """Join a relative path sent by the server onto root.

    Parameters
    ----------
    root : Path
        Local directory.
    relative : str
        POSIX path relative to root.

    Returns
    -------
    Path
        The joined path.

    Raises
    ------
    mx.DownloadException
        When the path is absolute or leaves root.
    """
    path = PurePosixPath(relative)
    if not path.parts or path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise mx.DownloadException(f"The server sent an unsafe path: {relative}")
    return Path(root).joinpath(*path.parts)


def download_file(url: str, target: Path, size: int, name: str = None) -> bool:
    """Download a signed URL to target, unless target already has the size.

    The bytes go to a hidden file beside target, which replaces target only
    when its size matches. Readers never see a partial file.

    Parameters
    ----------
    url : str
        Signed URL. Never put it in a message: it is a credential.
    target : Path
        Local path.
    size : int
        Expected size in bytes.
    name : str, optional
        Name for messages, by default the name of target.

    Returns
    -------
    bool
        True if the file was downloaded, False if it was already complete.
    """
    if target.is_file() and target.stat().st_size == size:
        return False

    name = name or target.name
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
    try:
        try:
            with requests.get(url, stream=True, timeout=mcc.DOWNLOAD_TIMEOUT) as response:
                if response.status_code not in mcc.HTTP_STATUS_SUCCESS_RANGE:
                    raise mx.DownloadException(
                        f"Download of {name} failed with status code "
                        f"{response.status_code}. Run the command again to get new "
                        "URLs; complete files are kept."
                    )
                with open(partial, "wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        output.write(chunk)
        except requests.exceptions.RequestException as ex:
            # The message of a transport error holds the signed URL.
            raise mx.DownloadException(
                f"Download of {name} failed ({type(ex).__name__})."
            ) from None

        actual = partial.stat().st_size
        if actual != size:
            raise mx.DownloadException(
                f"Downloaded {name} has {actual} bytes; expected {size}."
            )
        os.replace(partial, target)
    finally:
        if partial.exists():
            partial.unlink()

    return True


def download_files(jobs: list, n: int = 4, progress: bool = True) -> list:
    """Download files in parallel threads.

    Parameters
    ----------
    jobs : list
        Argument tuples for `download_file`.
    n : int, optional
        Number of threads, by default 4.
    progress : bool, optional
        Show a progress bar, by default True.

    Returns
    -------
    list
        The `download_file` results, in job order.
    """
    if n < 1:
        raise ValueError("Number of threads must be greater than or equal to 1.")

    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(download_file, *job) for job in jobs]
        for future in tqdm(as_completed(futures), total=len(futures), disable=not progress):
            future.result()

    return [future.result() for future in futures]
