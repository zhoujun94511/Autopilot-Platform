"""Local spool for job results awaiting Platform acknowledgement."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


def result_directory(server: str, runner_id: str) -> Path:
    root = Path(os.environ.get("MC_RUNNER_STATE_DIR") or Path.home() / ".autopilot" / "runner")
    namespace = f"{server.rstrip('/')}\n{runner_id}".encode()
    return root / "pending-results" / hashlib.sha256(namespace).hexdigest()[:20]


def stage_result(directory: Path, job_id: str, claimed_at: str | None, result: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(f"{job_id}\n{claimed_at or ''}".encode()).hexdigest()
    path = directory / f"{name}.json"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=directory, delete=False,
    ) as stream:
        temp = Path(stream.name)
        try:
            json.dump(result, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return path
