"""Offline fault injection tests the client only; it never simulates market data."""
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from full_alpha.client import (
    Client,
    ResearchError,
    atomic_write,
    decode,
    encode,
    load_inputs,
    run_lock,
)

ORIGIN = "https://example.hf.space"
INPUTS = {"study": {"purpose": "verification"}, "payload": {
    "defaults": {"period": "Train"},
    "candidates": [{"candidate_id": "control", "expression": "rank(open_gap)"}],
}}
FULL = {"result_schema_version": "1", "run_id": "recorded-id", "settings": {"quantiles": 5},
        "report": [{"period": "Train", "ic": None, "net_sharpe": -0.25}],
        "metric_definitions": {"ic": "native"}, "metric_compatibility": {"verified": False}}
JOB = "/api/v1/jobs/instance-job"


class Server:
    def __init__(self):
        self.calls = []
        self.mode = "ok"
        self.instance = "instance"
        self.posts = 0

    def handle(self, request):
        path = request.url.path
        self.calls.append((request.method, str(request.url)))
        if path == "/api/v1/mining/batches":
            self.posts += 1
            if self.mode == "timeout":
                raise httpx.ReadTimeout("lost response", request=request)
            if self.mode == "capacity":
                return httpx.Response(429)
            return httpx.Response(202, json={"job_id": "instance-job", "instance_id": self.instance})
        if path == "/api/v1/jobs/limits":
            return httpx.Response(200, json={"instance_id": self.instance})
        if path == "/api/v1/readiness":
            return httpx.Response(200, json={"state": "ERROR" if self.mode == "unready" else "READY"})
        if path in {"/api/v1/meta", "/api/v1/health"}:
            return httpx.Response(200, json={})
        if path == "/api/v1/mining/validate":
            return httpx.Response(200, json={"items": [{"valid": True}]})
        if path == JOB:
            if self.mode == "gone":
                return httpx.Response(410)
            return httpx.Response(200, json={"state": "queued" if self.mode == "pending" else "complete"})
        if path == JOB + "/summary":
            item = {"candidate_id": "control", "state": "complete", "result": FULL,
                    "result_url": JOB + "/items/0/result", "csv_url": JOB + "/items/0/result?format=csv"}
            if self.mode == "cross_origin":
                item["result_url"] = "https://other.example/api/v1/steal"
            if self.mode == "bad_label":
                item["candidate_id"] = "other"
            if self.mode == "missing_result":
                item["result"] = None
            items = [item]
            if self.mode == "partial":
                items.append({"candidate_id": "bad", "state": "failed", "result": None,
                              "error": {"code": "INVALID_EXPRESSION"}})
            return httpx.Response(200, json={"state": "failed" if self.mode == "partial" else "complete", "items": items,
                                           "csv_url": JOB + "/export.csv", "guide_url": "/api/v1/downloads/guide-v1.csv"})
        if path == JOB + "/items/0/result" and not request.url.query:
            full = deepcopy(FULL)
            if self.mode == "mismatch":
                full["report"][0]["ic"] = 0
            return httpx.Response(200, json=full)
        if path.endswith("export.csv") or request.url.query:
            return httpx.Response(200, content=b"metric,value\nic,\nnet_sharpe,-0.25\n", headers={
                "content-disposition": 'attachment; filename="../../unsafe.csv"'})
        if path == "/api/v1/downloads/guide-v1.csv":
            return httpx.Response(200, content=b"key,value\r\n/schema,1\r\n")
        raise AssertionError(f"Unexpected API request: {request.method} {path}")


@pytest.fixture
def server_client():
    server = Server()
    client = Client(ORIGIN, token="secret-test", transport=httpx.MockTransport(server.handle))
    yield server, client
    client.close()


def test_recorded_results_and_recovery_after_server_expiry(tmp_path, server_client):
    server, client = server_client
    root = tmp_path / "run"
    result = client.start(INPUTS, root)
    assert result["items"][0]["result"]["report"][0]["ic"] is None
    state = decode((root / "state.json").read_bytes())
    assert state["phase"] == "collected" and state["job_id"] == "instance-job"
    assert "secret-test" not in "".join(path.read_text() for path in root.iterdir() if path.is_file())
    assert (root / "batch.csv").read_bytes() == b"metric,value\nic,\nnet_sharpe,-0.25\n"
    assert (root / "guide.csv").read_bytes() == b"key,value\r\n/schema,1\r\n"
    assert not (root / "guide.md").exists()
    assert not (tmp_path / "unsafe.csv").exists()
    server.mode = "gone"
    calls = len(server.calls)
    assert client.resume(root) == result
    assert len(server.calls) == calls  # Fully collected evidence is usable offline.
    assert server.posts == 1


def test_uncertain_submission_never_reposts(tmp_path, server_client):
    server, client = server_client
    server.mode = "timeout"
    root = tmp_path / "run"
    with pytest.raises(ResearchError, match="Transport"):
        client.start(INPUTS, root)
    assert decode((root / "state.json").read_bytes())["phase"] == "submitting"
    server.instance = "restarted"
    with pytest.raises(ResearchError, match="automatic resubmission"):
        client.resume(root)
    assert server.posts == 1


def test_known_job_recovers_with_get_only_and_stops_on_410(tmp_path, server_client):
    server, client = server_client
    server.mode = "pending"
    root = tmp_path / "run"
    with pytest.raises(ResearchError, match="deadline"):
        client.start(INPUTS, root, wait_seconds=0.001)
    server.mode = "gone"
    calls = len(server.calls)
    with pytest.raises(ResearchError, match="JOB_GONE"):
        client.resume(root)
    assert all(method == "GET" for method, _ in server.calls[calls:])
    server.mode = "ok"
    client.resume(root)
    assert server.posts == 1


@pytest.mark.parametrize("mode,match", [("cross_origin", "unsafe"), ("mismatch", "mismatch"), ("bad_label", "labels"), ("missing_result", "no recorded result")])
def test_contract_failures_are_closed(tmp_path, server_client, mode, match):
    server, client = server_client
    server.mode = mode
    with pytest.raises(ResearchError, match=match):
        client.start(INPUTS, tmp_path / "run")
    assert all(ORIGIN in url for _, url in server.calls)


def test_saved_manifest_and_download_tampering(tmp_path, server_client):
    _, client = server_client
    root = tmp_path / "run"
    client.start(INPUTS, root)
    (root / "batch.csv").write_bytes(b"changed")
    with pytest.raises(ResearchError, match="checksum"):
        client.resume(root)
    (root / "manifest.json").write_bytes(encode(INPUTS))
    with pytest.raises(ResearchError, match="manifest"):
        client.resume(root)


@pytest.mark.parametrize("url", ["http://example.com", "https://user:pass@example.com", "https://example.com/?token=x"])
def test_credential_and_origin_boundaries(url):
    with pytest.raises(ResearchError, match="HTTPS origin"):
        Client(url)


def test_redirects_and_nonfinite_json_are_refused():
    client = Client(ORIGIN, transport=httpx.MockTransport(lambda _: httpx.Response(302, headers={"Location": "https://evil.example"})))
    with pytest.raises(ResearchError, match="HTTP 302"):
        client.json("GET", "/api/v1/meta")
    client.close()
    with pytest.raises(ResearchError, match="numeric"):
        decode(b'{"metric":NaN}')
    with pytest.raises(ResearchError, match="overflow"):
        decode(b'{"metric":1e999}')


def test_frozen_csv_protocol_and_budget(tmp_path):
    project = Path(__file__).parents[1]
    inputs = load_inputs(project / "checks/protocol.toml", project / "checks/smoke.csv")
    assert len(inputs["payload"]["candidates"]) == 3
    csv_path = tmp_path / "candidates.csv"
    csv_path.write_text("candidate_id,expression\na,open_gap\na,prev_ret\n")
    with pytest.raises(ResearchError, match="Duplicate"):
        load_inputs(project / "checks/protocol.toml", csv_path)
    protocol = tmp_path / "protocol.toml"
    protocol.write_text((project / "checks/protocol.toml").read_text().replace('period = "Train"', 'period = "OOS"'))
    with pytest.raises(ResearchError, match="sealed OOS"):
        load_inputs(protocol, project / "checks/smoke.csv")
    protocol.write_text((project / "checks/protocol.toml").read_text().replace('candidate_budget = 3', 'candidate_budget = 1'))
    with pytest.raises(ResearchError, match="budget"):
        load_inputs(protocol, project / "checks/smoke.csv")


def test_run_directory_is_exclusive_and_wait_is_checked_before_intake(tmp_path, server_client):
    server, client = server_client
    with pytest.raises(ResearchError, match="positive"):
        client.start(INPUTS, tmp_path / "run", wait_seconds=float("nan"))
    assert not server.calls
    root = tmp_path / "existing"
    root.mkdir()
    with pytest.raises(FileExistsError):
        client.start(INPUTS, root)
    assert not server.calls


def test_input_freeze_is_exact(tmp_path, server_client):
    _, client = server_client
    root = tmp_path / "run"
    client.start(INPUTS, root)
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["payload"] == INPUTS["payload"]
    assert manifest["study"] == INPUTS["study"]


def test_concurrent_writer_and_atomic_failure_preserve_evidence(tmp_path, monkeypatch):
    with run_lock(tmp_path), pytest.raises(ResearchError, match="Another process"):
        with run_lock(tmp_path):
            pytest.fail("Second writer acquired lock")
    path = tmp_path / "state.json"
    atomic_write(path, b"original")

    def failed_replace(*args):
        raise OSError("controlled disk failure")

    monkeypatch.setattr("full_alpha.client.os.replace", failed_replace)
    with pytest.raises(OSError, match="disk failure"):
        atomic_write(path, b"replacement")
    assert path.read_bytes() == b"original"
    assert not list(tmp_path.glob(".pending-*"))


def test_failed_sibling_is_retained_without_poisoning_success(tmp_path, server_client):
    server, client = server_client
    server.mode = "partial"
    inputs = deepcopy(INPUTS)
    inputs["payload"]["candidates"].append({"candidate_id": "bad", "expression": "not_a_field"})
    root = tmp_path / "run"
    summary = client.start(inputs, root)
    assert summary["state"] == "failed"
    assert summary["items"][1]["error"]["code"] == "INVALID_EXPRESSION"
    assert (root / "00-control.csv").exists()
    assert len(decode((root / "manifest.json").read_bytes())["payload"]["candidates"]) == 2
    assert client.resume(root) == summary


@pytest.mark.parametrize("mode,posts", [("unready", 0), ("capacity", 1)])
def test_readiness_capacity_do_not_trigger_retries(tmp_path, server_client, mode, posts):
    server, client = server_client
    server.mode = mode
    root = tmp_path / "run"
    with pytest.raises(ResearchError):
        client.start(INPUTS, root)
    assert (root / "manifest.json").exists()
    assert server.posts == posts
    with pytest.raises(ResearchError, match="resubmission"):
        client.resume(root)
    assert server.posts == posts
