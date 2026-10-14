"""Unit tests for analyses that run outside ME.org. They mock HTTP, so they need no server."""

import json
from unittest.mock import Mock, patch

import pytest
import requests
from click.testing import CliRunner

import meorg_client.analysis as mea
import meorg_client.cli as cli
from meorg_client.client import Client
from meorg_client.exceptions import DownloadException, RequestException

# Object key -> bytes held by the fake object store
OBJECTS = {
    "pals/data/ds1": b"dataset one",
    "pals/data/bm1": b"benchmark",
    "pals/data/mo1": b"model output one",
}


def _entry(type_, number, key):
    return {
        "type": type_,
        "number": number,
        "name": f"{type_}-{number}",
        "filename": f"{key.rsplit('/', 1)[-1]}.nc",
        "size": len(OBJECTS[key]),
        "key": key,
        "url": f"https://objects.example/{key}?X-Amz-Signature=secret",
    }


def _input_data(files=None):
    if files is None:
        files = [
            _entry("DataSet", 1, "pals/data/ds1"),
            _entry("Benchmark", 1, "pals/data/bm1"),
            _entry("ModelOutput", 1, "pals/data/mo1"),
            # The benchmark again, as model output 2, with the same key
            _entry("ModelOutput", 2, "pals/data/bm1"),
        ]
    model_output = dict(id="mo-1", name="my-output", modified="2026-09-30", modelName="CABLE")
    return {"data": {"modelOutput": model_output, "config": None, "files": files}}


def _response(status_code=200, content=b"", json_body=None):
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(json_body).encode() if json_body else content
    response._content_consumed = True
    return response


def _client(data=None):
    client = Client()
    client.base_url = "https://meorg.example/api"
    client.get_analysis_input = Mock(return_value=data or _input_data())
    return client


def _prepare(client, tmp_path, calls=None, **kwargs):
    """Run prepare_analysis_input against the fake object store."""

    def get(url, **_):
        key = url.split("objects.example/", 1)[1].split("?", 1)[0]
        (calls if calls is not None else []).append(key)
        return _response(content=OBJECTS[key])

    kwargs.setdefault("cache", tmp_path / "cache")
    with patch("meorg_client.downloads.requests.get", side_effect=get):
        return client.prepare_analysis_input(
            "mo-1", "exp-1", run_id="run-1", progress=False, **kwargs
        )


def _seed(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_get_analysis_input_uses_authenticated_endpoint():
    """Test the request URL and auth headers."""
    client = Client()
    client.base_url = "https://meorg.example/api"
    client.headers["X-Auth-Token"] = "token-1"
    with patch(
        "meorg_client.client.requests.get", return_value=_response(json_body={"data": {}})
    ) as get:
        client.get_analysis_input("mo-1", "exp-1")

    args, kwargs = get.call_args
    assert args[0] == "https://meorg.example/api/modeloutput/mo-1/exp-1/analysis-input"
    assert kwargs["headers"]["X-Auth-Token"] == "token-1"


def test_each_key_is_downloaded_once_and_then_cached(tmp_path):
    """Test a miss is downloaded once per key, and a second run downloads nothing."""
    calls = []
    result = _prepare(_client(), tmp_path, calls)

    assert sorted(calls) == sorted(OBJECTS)
    assert (result["downloaded"], result["cached"]) == (3, 0)
    document = result["input"]
    assert document["_id"] == "run-1" and document["config"] is None
    assert [f["path"] for f in document["files"]] == [
        str(tmp_path / "cache" / key)
        for key in ["pals/data/ds1", "pals/data/bm1", "pals/data/mo1", "pals/data/bm1"]
    ]
    assert "secret" not in json.dumps(document)

    calls.clear()
    result = _prepare(_client(), tmp_path, calls)
    assert calls == []
    assert (result["downloaded"], result["cached"]) == (0, 3)


def test_read_only_roots_are_searched_first_and_wrong_sizes_are_misses(tmp_path):
    """Test a read-only hit is used in place and a wrong-size file is fetched again."""
    shared = tmp_path / "shared"
    _seed(shared / "pals/data/ds1", OBJECTS["pals/data/ds1"])
    _seed(shared / "pals/data/bm1", b"wrong size")
    calls = []

    result = _prepare(_client(), tmp_path, calls, cache_ro=[shared])

    assert sorted(calls) == ["pals/data/bm1", "pals/data/mo1"]
    assert result["input"]["files"][0]["path"] == str(shared / "pals/data/ds1")
    assert not (tmp_path / "cache/pals/data/ds1").exists()
    assert (shared / "pals/data/bm1").read_bytes() == b"wrong size"


def test_local_files_replace_model_output_one(tmp_path):
    """Test local files replace the server's model output 1, first among model outputs."""
    local = [_seed(tmp_path / "out" / name, b"abc") for name in ("r0.nc", "r1.nc")]
    calls = []

    files = _prepare(_client(), tmp_path, calls, model_output_files=local)["input"]["files"]

    assert "pals/data/mo1" not in calls
    assert [(f["type"], f["number"], f["filename"]) for f in files] == [
        ("DataSet", 1, "ds1.nc"),
        ("Benchmark", 1, "bm1.nc"),
        ("ModelOutput", 1, "r0.nc"),
        ("ModelOutput", 1, "r1.nc"),
        ("ModelOutput", 2, "bm1.nc"),
    ]
    assert files[2] == {
        "type": "ModelOutput",
        "number": 1,
        "name": "my-output",
        "setId": "mo-1",
        "setModified": "2026-09-30",
        "modelName": "CABLE",
        "filename": "r0.nc",
        "size": 3,
        "path": str(local[0]),
    }


def test_model_output_files_are_required_when_it_has_none_on_meorg(tmp_path):
    """Test an empty model output needs local files."""
    data = _input_data([_entry("DataSet", 1, "pals/data/ds1")])
    with pytest.raises(ValueError, match="no files on ME.org"):
        _prepare(_client(data), tmp_path)

    local = [_seed(tmp_path / "r0.nc", b"abc")]
    files = _prepare(_client(data), tmp_path, model_output_files=local)["input"]["files"]
    assert [f["filename"] for f in files] == ["ds1.nc", "r0.nc"]


def test_local_files_need_unique_names(tmp_path):
    """Test two local files with one name are rejected."""
    local = [_seed(tmp_path / d / "r0.nc", b"abc") for d in ("a", "b")]
    with pytest.raises(ValueError, match="same name"):
        mea.model_output_entries(_input_data()["data"]["modelOutput"], local)


def test_unsafe_key_is_rejected(tmp_path):
    """Test an object key cannot leave the cache."""
    entry = dict(_entry("ModelOutput", 1, "pals/data/mo1"), key="../../etc/x")
    with pytest.raises(DownloadException, match="unsafe path"):
        _prepare(_client(_input_data([entry])), tmp_path)


def test_input_cli_writes_input_json(tmp_path, monkeypatch):
    """Test the CLI writes input.json and prints its path."""
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path / "out/r0.nc", b"abc")
    client = _client()
    client.prepare_analysis_input = Mock(
        return_value=dict(input={"_id": "run-1"}, downloaded=1, cached=2)
    )
    monkeypatch.setattr(cli, "_get_client", lambda: client)

    result = CliRunner().invoke(
        cli.cli,
        ["analysis", "input", "mo-1", "exp-1", "out/r0.nc", "--run-id", "run-1", "--cache", "c"],
    )

    assert result.exit_code == 0, result.output
    # The path is the last line; the counts go to stderr.
    assert result.output.splitlines()[-1] == str(tmp_path / "input.json")
    assert json.loads((tmp_path / "input.json").read_text()) == {"_id": "run-1"}
    assert client.prepare_analysis_input.call_args.kwargs["model_output_files"] == (
        "out/r0.nc",
    )


def _run_dir(tmp_path, status="success"):
    """A meorg-run run directory."""
    run_dir = tmp_path / "run"
    _seed(run_dir / "run.json", json.dumps({"status": status, "externalRunId": "run-1"}).encode())
    _seed(run_dir / "input.json", b"{}")
    _seed(run_dir / "output/PALS.log", b"log")
    _seed(run_dir / "output/a.png", b"png")
    _seed(run_dir / "r-stderr.log", b"err")
    output = {"files": [{"filename": "output/a.png"}, {"filename": None, "error": "x"}]}
    _seed(run_dir / "output.json", json.dumps(output).encode())
    return run_dir


def test_result_parts(tmp_path):
    """Test which files a success and a failure send."""
    run_dir = _run_dir(tmp_path)
    names = lambda parts: [name for name, _ in parts]  # noqa: E731

    assert names(mea.result_parts(run_dir, run_dir / "input.json", True)) == [
        "output.json", "a.png", "PALS.log", "run.json", "input.json",
    ]
    assert names(mea.result_parts(run_dir, run_dir / "input.json", False)) == [
        "PALS.log", "r-stderr.log", "run.json", "input.json",
    ]


def test_submit_posts_multipart(tmp_path):
    """Test the request fields, metadata and file parts."""
    run_dir = _run_dir(tmp_path, status="error")
    client = _client()
    with patch(
        "meorg_client.client.requests.post",
        return_value=_response(json_body={"data": {"analysisId": "an-1"}}),
    ) as post:
        client.submit_analysis_result("mo-1", "exp-1", run_dir, orchestrator="benchcab")

    args, kwargs = post.call_args
    assert args[0] == "https://meorg.example/api/modeloutput/mo-1/exp-1/analysis-result"
    data = kwargs["data"]
    assert (data["outcome"], data["externalRunId"], data["runner"]) == ("failure", "run-1", "gadi")
    metadata = json.loads(data["metadata"])
    assert metadata["client"] == "meorg_client" and metadata["orchestrator"] == "benchcab"
    assert [part[1][0] for part in kwargs["files"]] == [
        "PALS.log", "r-stderr.log", "run.json", "input.json",
    ]
    # formidable reads a part without a content type as a field
    assert all(part[1][2] for part in kwargs["files"])


@pytest.mark.parametrize(
    "errors, posts",
    [
        ([RequestException(502, "bad gateway")], 2),
        ([requests.exceptions.ConnectionError()], 2),
        ([RequestException(409, "conflict")], 1),
        ([RequestException(500, "error")] * 4, 4),
    ],
    ids=["5xx-then-ok", "network-then-ok", "4xx-not-retried", "gives-up"],
)
def test_submit_retries_only_server_and_network_errors(tmp_path, errors, posts):
    """Test retries for 5xx and network errors, but not for 4xx."""
    client = _client()
    client.post_analysis_result = Mock(side_effect=errors + [{"data": {}}])
    run_dir = _run_dir(tmp_path)

    if posts == len(errors):
        with pytest.raises(type(errors[0])):
            client.submit_analysis_result("mo-1", "exp-1", run_dir, backoff=0)
    else:
        client.submit_analysis_result("mo-1", "exp-1", run_dir, backoff=0)

    assert client.post_analysis_result.call_count == posts


def test_batches_split_parts_by_size(tmp_path):
    """Test batches keep the order and put a large part alone."""
    sizes = {"a": 40, "b": 50, "c": 120, "d": 10, "e": 100}
    parts = [(name, _seed(tmp_path / name, b"x" * size)) for name, size in sizes.items()]

    groups = mea.batches(parts, 100)

    assert [[name for name, _ in group] for group in groups] == [["a", "b"], ["c"], ["d"], ["e"]]
    assert mea.batches([], 100) == []


def _large_run_dir(tmp_path):
    """A run directory with three 40-byte plots."""
    run_dir = _run_dir(tmp_path)
    plots = ["a.png", "b.png", "c.png"]
    for name in plots:
        _seed(run_dir / "output" / name, b"p" * 40)
    output = {"files": [{"filename": f"output/{name}"} for name in plots]}
    _seed(run_dir / "output.json", json.dumps(output).encode())
    return run_dir


def test_submit_sends_artifacts_in_batches_then_the_result(tmp_path):
    """Test a result larger than a batch is sent as artifacts and then the result."""
    client = _client()
    with patch(
        "meorg_client.client.requests.post",
        return_value=_response(json_body={"data": {"analysisId": "an-1", "complete": False}}),
    ) as post:
        client.submit_analysis_result("mo-1", "exp-1", _large_run_dir(tmp_path), batch_size=90)

    calls = [(args[0].rsplit("/", 1)[-1], [part[1][0] for part in kwargs["files"]], kwargs["data"])
             for args, kwargs in post.call_args_list]
    assert [(route, names) for route, names, _ in calls] == [
        ("artifacts", ["a.png", "b.png"]),
        ("artifacts", ["c.png"]),
        ("analysis-result", ["output.json", "PALS.log", "run.json", "input.json"]),
    ]
    assert calls[0][2] == {"externalRunId": "run-1", "runner": "gadi"}
    assert calls[2][2]["outcome"] == "success"


def test_submit_stops_batches_when_the_run_has_a_result(tmp_path):
    """Test the batches stop once ME.org says the run already has a result."""
    client = _client()
    client.post_analysis_artifacts = Mock(return_value={"data": {"complete": True}})
    client.post_analysis_result = Mock(return_value={"data": {"created": False}})

    client.submit_analysis_result("mo-1", "exp-1", _large_run_dir(tmp_path), batch_size=50)

    assert client.post_analysis_artifacts.call_count == 1
    assert client.post_analysis_result.call_count == 1


def test_submit_retries_a_batch(tmp_path):
    """Test a failed batch is retried on its own."""
    client = _client()
    client.post_analysis_artifacts = Mock(
        side_effect=[RequestException(502, "bad gateway"), {"data": {}}, {"data": {}}]
    )
    client.post_analysis_result = Mock(return_value={"data": {}})

    run_dir = _large_run_dir(tmp_path)
    client.submit_analysis_result("mo-1", "exp-1", run_dir, batch_size=90, backoff=0)

    batches = [call.kwargs["files"] for call in client.post_analysis_artifacts.call_args_list]
    assert [[name for name, _ in batch] for batch in batches] == [
        ["a.png", "b.png"], ["a.png", "b.png"], ["c.png"],
    ]


def test_submit_cli_prints_analysis_id(tmp_path, monkeypatch):
    """Test the CLI prints the analysis ID, and notes a result stored before."""
    client = _client()
    client.submit_analysis_result = Mock(
        return_value={"data": {"analysisId": "an-1", "created": False}}
    )
    monkeypatch.setattr(cli, "_get_client", lambda: client)

    result = CliRunner().invoke(
        cli.cli, ["analysis", "submit-result", "mo-1", "exp-1", str(_run_dir(tmp_path))]
    )

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[-1] == "an-1"
    assert "already stored" in result.output
    assert client.submit_analysis_result.call_args.kwargs["batch_size"] == 100 * 2**20
