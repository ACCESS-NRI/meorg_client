"""Files of analyses that run outside ME.org, for example with meorg-run on Gadi."""

import json
from pathlib import Path


def model_output_entries(model_output: dict, paths: list) -> list:
    """Build input.json entries for local files of the model output under analysis.

    Parameters
    ----------
    model_output : dict
        The modelOutput object of an analysis-input response.
    paths : list
        Local file paths.

    Returns
    -------
    list
        Model output 1 entries with absolute paths.
    """
    paths = [Path(path).absolute() for path in paths]
    names = [path.name for path in paths]

    # ME.org matches the files uploaded later to these entries by name.
    if len(set(names)) != len(names):
        raise ValueError("Two model output files have the same name.")

    return [
        {
            "type": "ModelOutput",
            "number": 1,
            "name": model_output["name"],
            "setId": model_output["id"],
            "setModified": model_output["modified"],
            "modelName": model_output["modelName"],
            "filename": path.name,
            "size": path.stat().st_size,
            "path": str(path),
        }
        for path in paths
    ]


# Parts that go with the result itself. The others can be sent before it in
# batches. ME.org reads PALS.log only from the result request.
RESULT_PARTS = {"output.json", "input.json", "run.json", "PALS.log", "r-stderr.log"}


def result_parts(run_dir: Path, input_path: Path, success: bool) -> list:
    """List the files to send for a run directory written by meorg-run.

    A success sends output.json and every file it lists. Both outcomes send
    the logs that exist, run.json, and the input.json of the run.

    Parameters
    ----------
    run_dir : Path
        Run directory.
    input_path : Path
        The input.json of the run.
    success : bool
        Whether the run succeeded.

    Returns
    -------
    list
        (part name, path) pairs. ME.org matches the parts by name.
    """
    run_dir = Path(run_dir)
    paths = []
    logs = [run_dir / "output" / "PALS.log"]

    if success:
        output = json.loads((run_dir / "output.json").read_text())
        paths += [run_dir / "output.json"]
        paths += [run_dir / f["filename"] for f in output["files"] if f.get("filename")]
    else:
        logs += [run_dir / "r-stderr.log"]

    paths += [log for log in logs if log.is_file()] + [run_dir / "run.json"]
    parts = [(path.name, path) for path in dict.fromkeys(paths)]
    return parts + [("input.json", Path(input_path))]


def batches(parts: list, limit: int) -> list:
    """Split parts, in order, into batches of at most limit file bytes.

    Parameters
    ----------
    parts : list
        (part name, path) pairs.
    limit : int
        Largest number of file bytes in a batch.

    Returns
    -------
    list
        Lists of parts. A part larger than limit is in a batch alone.
    """
    groups, size = [], 0

    for part in parts:
        part_size = Path(part[1]).stat().st_size
        if groups and size + part_size <= limit:
            groups[-1].append(part)
            size += part_size
        else:
            groups.append([part])
            size = part_size

    return groups
