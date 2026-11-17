"""One bounded batch per directory. A saved job can only be read, never resubmitted."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import tempfile
import time
import tomllib
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx

TERMINAL = {"complete", "failed", "cancelled"}


class ResearchError(Exception):
    """A bounded failure that preserves its run directory for inspection."""


def encode(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def reject_constant(value: str):
    raise ResearchError(f"Invalid JSON numeric constant: {value}")


def finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ResearchError("Invalid JSON numeric overflow")
    return result


def decode(value: bytes) -> dict:
    return json.loads(value, parse_constant=reject_constant, parse_float=finite_float)


def atomic_write(path: Path, content: bytes) -> None:
    """Same-filesystem replace: interruption cannot leave a partial ledger/file."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def run_lock(root: Path):
    # ponytail: local Unix single-writer lock; use a transactional store for shared-host writers.
    import fcntl

    with (root / ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ResearchError("Another process owns this run directory") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load_inputs(protocol_path: Path, candidates_path: Path) -> dict:
    protocol = tomllib.loads(protocol_path.read_text())
    if set(protocol) != {"study", "defaults"}:
        raise ResearchError("Protocol needs exactly [study] and [defaults]")
    study = protocol["study"]
    for field in ("hypothesis", "acceptance", "prior_search", "purpose"):
        if not isinstance(study.get(field), str) or not study[field].strip():
            raise ResearchError(f"Declare study.{field} before running")
    if study["purpose"] not in {"research", "verification"}:
        raise ResearchError("purpose must be research or verification")
    budget = study.get("candidate_budget")
    if type(budget) is not int or not 1 <= budget <= 16:
        raise ResearchError("candidate_budget must be 1..16; do not silently expand it")
    if protocol["defaults"].get("period") not in {"Train", "Validation", "Train + validation"}:
        raise ResearchError("Declare a supported period; sealed OOS is unavailable")
    with candidates_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["candidate_id", "expression"]:
            raise ResearchError("CSV header must be candidate_id,expression")
        candidates = list(reader)
    if not 1 <= len(candidates) <= budget:
        raise ResearchError("Candidate count exceeds the declared budget or is empty")
    ids = set()
    for row in candidates:
        label, expression = row.get("candidate_id"), row.get("expression")
        if set(row) != {"candidate_id", "expression"} or not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", label):
            raise ResearchError("Invalid candidate CSV row/id")
        if label in ids or not isinstance(expression, str) or not 1 <= len(expression) <= 1024:
            raise ResearchError("Duplicate id, missing expression or oversized expression")
        ids.add(label)
    payload = {"defaults": protocol["defaults"], "candidates": candidates}
    if len(encode(payload)) > 65536:
        raise ResearchError("Payload exceeds 64 KiB")
    return {"study": study, "payload": payload}


class Client:
    def __init__(self, origin: str, *, token: str = "", api_key: str = "",
                 transport=None, timeout: float = 60):
        parts = urlsplit(origin)
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment or parts.path not in {"", "/"}):
            raise ResearchError("Base URL must be an HTTPS origin with no credentials/path/query")
        self.origin = origin.rstrip("/")
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if api_key:
            headers["X-API-Key"] = api_key
        self.http = httpx.Client(base_url=self.origin, headers=headers, timeout=timeout,
                                 transport=transport, follow_redirects=False)

    def close(self):
        self.http.close()

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        # Download links may never send credentials to a different origin.
        parts = urlsplit(path)
        if parts.scheme or parts.netloc or not path.startswith("/api/v1/") or "\\" in path or parts.fragment:
            raise ResearchError("Refusing an unsafe API/download link")
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ResearchError("Transport failure; inspect saved state, never blindly resubmit") from exc
        if response.status_code == 410:
            raise ResearchError("JOB_GONE: expired/restarted; keep evidence and explicitly decide on new work")
        if not 200 <= response.status_code < 300:
            # Neither credentials, redirect locations nor an arbitrary proxy body enter logs.
            raise ResearchError(f"HTTP {response.status_code}; saved state remains available")
        return response

    def json(self, method: str, path: str, **kwargs) -> dict:
        return decode(self.request(method, path, **kwargs).content)

    def doctor(self) -> dict:
        return {name: self.json("GET", "/api/v1/" + name)
                for name in ("health", "readiness", "jobs/limits", "meta")}

    def start(self, inputs: dict, root: Path, *, wait_seconds: float = 600) -> dict:
        if not math.isfinite(wait_seconds) or wait_seconds <= 0:
            raise ResearchError("wait_seconds must be finite and positive")
        root.mkdir(parents=True, exist_ok=False)
        with run_lock(root):
            manifest = {"client_version": "0.1.0", "origin": self.origin, **inputs}
            content = encode(manifest)
            atomic_write(root / "manifest.json", content)
            state = {"manifest_sha256": digest(content), "key": uuid.uuid4().hex,
                     "phase": "prepared", "created_at": time.time()}
            atomic_write(root / "state.json", encode(state))
            snapshot = self.doctor()
            atomic_write(root / "environment.json", encode(snapshot))
            if snapshot["readiness"]["state"] != "READY":
                raise ResearchError("Service is not READY; this run was not submitted")
            checked = self.json("POST", "/api/v1/mining/validate", json=inputs["payload"])
            atomic_write(root / "validation.json", encode(checked))
            if not any(item["valid"] for item in checked["items"]):
                state["phase"] = "validation_failed"
                atomic_write(root / "state.json", encode(state))
                raise ResearchError("No eligible candidates; all refusals saved")
            # From this durable boundary onward, a missing job id means unknown intake.
            state.update(phase="submitting", instance_id=snapshot["jobs/limits"]["instance_id"])
            atomic_write(root / "state.json", encode(state))
            accepted = self.json("POST", "/api/v1/mining/batches", json=inputs["payload"],
                                 headers={"Idempotency-Key": state["key"]})
            state.update(job_id=accepted["job_id"], phase="accepted",
                         accepted_instance_id=accepted["instance_id"])
            atomic_write(root / "state.json", encode(state))
            atomic_write(root / "accepted.json", encode(accepted))
            return self._collect(root, manifest, state, wait_seconds)

    def resume(self, root: Path, *, wait_seconds: float = 600) -> dict:
        with run_lock(root):
            content = (root / "manifest.json").read_bytes()
            manifest = decode(content)
            state = decode((root / "state.json").read_bytes())
            if digest(content) != state["manifest_sha256"] or manifest["origin"] != self.origin:
                raise ResearchError("Changed manifest or origin; refusing recovery")
            if not state.get("job_id"):
                raise ResearchError("No saved job id: intake may be unknown; automatic resubmission is forbidden")
            if state["phase"] == "collected":
                self.verify_files(root)
                return decode((root / "summary.json").read_bytes())
            return self._collect(root, manifest, state, wait_seconds)

    def _collect(self, root: Path, manifest: dict, state: dict, wait_seconds: float) -> dict:
        if not math.isfinite(wait_seconds) or wait_seconds <= 0:
            raise ResearchError("wait_seconds must be finite and positive")
        path = "/api/v1/jobs/" + state["job_id"]
        deadline = time.monotonic() + wait_seconds
        while True:
            status = self.json("GET", path)
            atomic_write(root / "status.json", encode(status))
            if status["state"] in TERMINAL:
                break
            if time.monotonic() >= deadline:
                raise ResearchError("Polling deadline reached; resume uses the saved job id and GET only")
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        summary = self.json("GET", path + "/summary")
        atomic_write(root / "summary.json", encode(summary))
        expected = [row["candidate_id"] for row in manifest["payload"]["candidates"]]
        if [row["candidate_id"] for row in summary["items"]] != expected:
            raise ResearchError("Result candidate labels/order differ from the frozen manifest")
        downloads = [(summary["csv_url"], "batch.csv"), (summary["guide_url"], "guide.csv")]
        for index, item in enumerate(summary["items"]):
            if item["state"] == "complete" and item["result"] is None:
                raise ResearchError("Completed contender has no recorded result")
            if item["result"] is not None:
                full = self.json("GET", item["result_url"])
                if full.get("result_schema_version") != "1" or not full.get("run_id"):
                    raise ResearchError("Unsupported/missing recorded result identity")
                for key in ("report", "settings", "run_id", "metric_definitions", "metric_compatibility"):
                    if full[key] != item["result"][key]:
                        raise ResearchError("Summary/full result contract mismatch")
                downloads.append((item["csv_url"], f"{index:02d}-{item['candidate_id']}.csv"))
        files = {}
        for url, fallback in downloads:
            response = self.request("GET", url)
            # Exact bytes plus recorded filename; never trust a server filename as a local path.
            atomic_write(root / fallback, response.content)
            files[fallback] = {"sha256": digest(response.content), "url": url,
                               "content_disposition": response.headers.get("content-disposition")}
        files["summary.json"] = {"sha256": digest((root / "summary.json").read_bytes())}
        atomic_write(root / "files.json", encode(files))
        state.update(phase="collected", job_state=summary["state"], collected_at=time.time())
        atomic_write(root / "state.json", encode(state))
        return summary

    @staticmethod
    def verify_files(root: Path) -> None:
        for name, evidence in decode((root / "files.json").read_bytes()).items():
            if Path(name).name != name or digest((root / name).read_bytes()) != evidence["sha256"]:
                raise ResearchError("Saved result/download checksum mismatch")
