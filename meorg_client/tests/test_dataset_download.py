"""Unit tests for dataset downloads. They mock HTTP, so they need no server."""

import json
from unittest.mock import patch

import pytest
import requests
from click.testing import CliRunner

import meorg_client.cli as cli
import meorg_client.downloads as med
from meorg_client.client import Client
from meorg_client.exceptions import DownloadException

SECRET_URL = "https://objects.example/f1?X-Amz-Signature=secret"


def _response(status_code=200, content=b"", json_body=None):
    """Build a requests.Response with a body."""
    response = requests.Response()
    response.status_code = status_code
    if json_body is not None:
        content = json.dumps(json_body).encode()
    response._content = content
    response._content_consumed = True
    return response


def _manifest(files):
    """Build a manifest response from {relativePath: content}."""
    return {
        "experimentId": "exp-1",
        "files": [
            {
                "fileId": f"f{i}",
                "relativePath": path,
                "size": len(content),
                "url": f"https://objects.example/f{i}",
            }
            for i, (path, content) in enumerate(files.items())
        ],
    }


def _client():
    client = Client()
    client.base_url = "https://meorg.example/api"
    client.headers.update({"X-User-Id": "user-1", "X-Auth-Token": "token-1"})
    return client


def _objects(by_url):
    """Fake requests.get for signed URLs: {url: content}."""
    return lambda url, **kwargs: _response(content=by_url[url])


def test_manifest_uses_authenticated_endpoint():
    """Test the manifest request URL and auth headers."""
    with patch(
        "meorg_client.client.requests.get",
        return_value=_response(json_body={"files": []}),
    ) as get:
        assert _client().get_experiment_dataset_manifest("exp-1") == {"files": []}

    args, kwargs = get.call_args
    assert args[0] == "https://meorg.example/api/experiment/exp-1/datasets/manifest"
    assert kwargs["headers"]["X-Auth-Token"] == "token-1"


def test_download_writes_relative_paths_and_skips_complete_files(tmp_path):
    """Test files land at their relative paths and a second run downloads nothing."""
    files = {"datasets/a/met.nc": b"met", "datasets/a/flux.nc": b"flux!"}
    manifest = _manifest(files)
    client = _client()
    client.get_experiment_dataset_manifest = lambda experiment_id: manifest
    by_url = {f["url"]: files[f["relativePath"]] for f in manifest["files"]}

    with patch("meorg_client.downloads.requests.get", side_effect=_objects(by_url)):
        paths = client.download_experiment_datasets("exp-1", tmp_path, progress=False)

    assert paths == [tmp_path / path for path in files]
    assert [path.read_bytes() for path in paths] == list(files.values())

    with patch("meorg_client.downloads.requests.get") as get:
        client.download_experiment_datasets("exp-1", tmp_path, progress=False)
    get.assert_not_called()


def test_wrong_size_leaves_no_file(tmp_path):
    """Test a short download fails and leaves no file or partial file."""
    target = tmp_path / "met.nc"
    with patch(
        "meorg_client.downloads.requests.get", return_value=_response(content=b"ab")
    ):
        with pytest.raises(DownloadException, match="has 2 bytes; expected 3"):
            med.download_file(SECRET_URL, target, 3)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "fake_get",
    [
        lambda url, **kwargs: _response(status_code=403, content=b"expired"),
        lambda url, **kwargs: (_ for _ in ()).throw(
            requests.exceptions.ConnectionError(f"Max retries exceeded with url: {url}")
        ),
    ],
    ids=["http-error", "transport-error"],
)
def test_errors_never_show_the_signed_url(tmp_path, fake_get):
    """Test a failed download names the file but never the signed URL."""
    with patch("meorg_client.downloads.requests.get", side_effect=fake_get):
        with pytest.raises(DownloadException) as raised:
            med.download_file(SECRET_URL, tmp_path / "met.nc", 3)

    assert "met.nc" in raised.value.msg
    assert "secret" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("path", ["../x.nc", "/etc/x.nc", "a/../../x.nc", "a\\x.nc", ""])
def test_unsafe_paths_are_rejected(tmp_path, path):
    """Test a server path cannot leave the output directory."""
    with pytest.raises(DownloadException, match="unsafe path"):
        med.safe_join(tmp_path, path)


def test_cli_prints_each_path(tmp_path, monkeypatch):
    """Test the CLI prints one path per line."""
    client = _client()
    client.download_experiment_datasets = lambda **kwargs: [tmp_path / "a.nc"]
    monkeypatch.setattr(cli, "_get_client", lambda: client)

    result = CliRunner().invoke(cli.cli, ["dataset", "download", "exp-1"])

    assert result.exit_code == 0, result.output
    assert result.output == f"{tmp_path / 'a.nc'}\n"
