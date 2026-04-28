from __future__ import annotations

import json
import mimetypes
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
from uuid import uuid4

from formai.models import ProcessingIssue
from formai.utils import ensure_parent_directory


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ArtifactRecord:
    artifact_id: str
    kind: str
    path: str
    mime_type: str
    size_bytes: int
    step_name: str
    created_at: str

    @classmethod
    def from_dict(cls, payload: dict) -> "ArtifactRecord":
        return cls(
            artifact_id=str(payload["artifact_id"]),
            kind=str(payload["kind"]),
            path=str(payload["path"]),
            mime_type=str(payload.get("mime_type", "application/octet-stream")),
            size_bytes=int(payload.get("size_bytes", 0)),
            step_name=str(payload.get("step_name", "")),
            created_at=str(payload.get("created_at", utc_now_iso())),
        )

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "path": self.path,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "step_name": self.step_name,
            "created_at": self.created_at,
        }


@dataclass
class StepResultRecord:
    step_name: str
    status: str
    started_at: str = ""
    finished_at: str = ""
    data: dict = field(default_factory=dict)
    issues: List[dict] = field(default_factory=list)
    artifact_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0

    @classmethod
    def from_dict(cls, payload: dict) -> "StepResultRecord":
        return cls(
            step_name=str(payload["step_name"]),
            status=str(payload["status"]),
            started_at=str(payload.get("started_at", "")),
            finished_at=str(payload.get("finished_at", "")),
            data=dict(payload.get("data", {})),
            issues=list(payload.get("issues", [])),
            artifact_ids=list(payload.get("artifact_ids", [])),
            confidence=float(payload.get("confidence", 0.0)),
        )

    def to_dict(self) -> dict:
        return {
            "step_name": self.step_name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "data": self.data,
            "issues": self.issues,
            "artifact_ids": self.artifact_ids,
            "confidence": self.confidence,
        }


@dataclass
class JobRecord:
    job_id: str
    job_type: str
    status: str
    created_at: str
    updated_at: str
    job_dir: str
    inputs: Dict[str, str] = field(default_factory=dict)
    step_results: List[StepResultRecord] = field(default_factory=list)
    artifacts: List[ArtifactRecord] = field(default_factory=list)
    issues: List[dict] = field(default_factory=list)
    review_items: List[dict] = field(default_factory=list)
    confidence: float = 0.0
    error_message: str = ""

    @classmethod
    def from_dict(cls, payload: dict) -> "JobRecord":
        return cls(
            job_id=str(payload["job_id"]),
            job_type=str(payload["job_type"]),
            status=str(payload["status"]),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            job_dir=str(payload["job_dir"]),
            inputs=dict(payload.get("inputs", {})),
            step_results=[StepResultRecord.from_dict(item) for item in payload.get("step_results", [])],
            artifacts=[ArtifactRecord.from_dict(item) for item in payload.get("artifacts", [])],
            issues=list(payload.get("issues", [])),
            review_items=list(payload.get("review_items", [])),
            confidence=float(payload.get("confidence", 0.0)),
            error_message=str(payload.get("error_message", "")),
        )

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "job_dir": self.job_dir,
            "inputs": self.inputs,
            "step_results": [item.to_dict() for item in self.step_results],
            "artifacts": [item.to_dict() for item in self.artifacts],
            "issues": self.issues,
            "review_items": self.review_items,
            "confidence": self.confidence,
            "error_message": self.error_message,
        }


class FileJobStore:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def create_job(self, job_type: str, inputs: Dict[str, str]) -> JobRecord:
        job_id = uuid4().hex
        job_dir = self.base_dir / job_id
        (job_dir / "inputs").mkdir(parents=True, exist_ok=True)
        (job_dir / "outputs").mkdir(parents=True, exist_ok=True)
        (job_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        now = utc_now_iso()
        job = JobRecord(
            job_id=job_id,
            job_type=job_type,
            status="queued",
            created_at=now,
            updated_at=now,
            job_dir=str(job_dir),
            inputs=inputs,
        )
        self.save_job(job)
        return job

    def save_job(self, job: JobRecord) -> None:
        with self._lock:
            job.updated_at = utc_now_iso()
            job_path = Path(job.job_dir) / "job.json"
            ensure_parent_directory(job_path)
            self._write_job_atomically(job_path, job)

    def load_job(self, job_id: str) -> Optional[JobRecord]:
        job_path = self.base_dir / job_id / "job.json"
        if not job_path.exists():
            return None
        return JobRecord.from_dict(json.loads(job_path.read_text(encoding="utf-8")))

    def update_job(self, job_id: str, mutator: Callable[[JobRecord], None]) -> JobRecord:
        with self._lock:
            job_path = self.base_dir / job_id / "job.json"
            job = JobRecord.from_dict(json.loads(job_path.read_text(encoding="utf-8")))
            mutator(job)
            job.updated_at = utc_now_iso()
            self._write_job_atomically(job_path, job)
            return job

    def _write_job_atomically(self, job_path: Path, job: JobRecord) -> None:
        temp_path = job_path.with_suffix(f"{job_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(job.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(job_path)

    def register_artifact(self, job_id: str, kind: str, path: Path, step_name: str) -> ArtifactRecord:
        path = Path(path)
        mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        created_at = utc_now_iso()

        def mutate(job: JobRecord) -> None:
            artifact_id = f"{job_id}__{kind}_{len(job.artifacts) + 1}"
            artifact = ArtifactRecord(
                artifact_id=artifact_id,
                kind=kind,
                path=str(path),
                mime_type=mime_type,
                size_bytes=path.stat().st_size if path.exists() else 0,
                step_name=step_name,
                created_at=created_at,
            )
            job.artifacts.append(artifact)
            for step in job.step_results:
                if step.step_name == step_name and artifact_id not in step.artifact_ids:
                    step.artifact_ids.append(artifact_id)

        job = self.update_job(job_id, mutate)
        return job.artifacts[-1]

    def get_artifact(self, artifact_id: str) -> Optional[ArtifactRecord]:
        if "__" not in artifact_id:
            return None
        job_id = artifact_id.split("__", 1)[0]
        job = self.load_job(job_id)
        if job is None:
            return None
        for artifact in job.artifacts:
            if artifact.artifact_id == artifact_id:
                return artifact
        return None


class JobRunner:
    def __init__(self, store: FileJobStore):
        self.store = store

    def submit(self, job: JobRecord, worker: Callable[[str], None]) -> JobRecord:
        thread = threading.Thread(target=worker, args=(job.job_id,), daemon=True)
        thread.start()
        return job

    def mark_running(self, job_id: str) -> JobRecord:
        return self.store.update_job(job_id, lambda job: setattr(job, "status", "running"))

    def mark_failed(self, job_id: str, message: str, issues: List[dict] | None = None) -> JobRecord:
        def mutate(job: JobRecord) -> None:
            job.status = "failed"
            job.error_message = message
            if issues:
                job.issues.extend(issues)

        return self.store.update_job(job_id, mutate)

    def mark_succeeded(
        self,
        job_id: str,
        *,
        issues: List[dict] | None = None,
        review_items: List[dict] | None = None,
        confidence: float | None = None,
    ) -> JobRecord:
        def mutate(job: JobRecord) -> None:
            job.status = "succeeded"
            if issues is not None:
                job.issues = issues
            if review_items is not None:
                job.review_items = review_items
            if confidence is not None:
                job.confidence = confidence

        return self.store.update_job(job_id, mutate)

    def start_step(self, job_id: str, step_name: str) -> JobRecord:
        def mutate(job: JobRecord) -> None:
            for step in job.step_results:
                if step.step_name == step_name:
                    step.status = "running"
                    if not step.started_at:
                        step.started_at = utc_now_iso()
                    return
            job.step_results.append(
                StepResultRecord(
                    step_name=step_name,
                    status="running",
                    started_at=utc_now_iso(),
                )
            )

        return self.store.update_job(job_id, mutate)

    def finish_step(
        self,
        job_id: str,
        step_name: str,
        *,
        data: dict,
        issues: List[dict] | None = None,
        confidence: float = 0.0,
    ) -> JobRecord:
        def mutate(job: JobRecord) -> None:
            target = None
            for step in job.step_results:
                if step.step_name == step_name:
                    target = step
                    break
            if target is None:
                target = StepResultRecord(step_name=step_name, status="succeeded")
                job.step_results.append(target)
            target.status = "succeeded"
            target.finished_at = utc_now_iso()
            target.data = data
            target.issues = issues or []
            target.confidence = confidence

        return self.store.update_job(job_id, mutate)


def copy_or_link_input(source_path: Path, destination_path: Path) -> Path:
    source_path = Path(source_path)
    destination_path = Path(destination_path)
    ensure_parent_directory(destination_path)
    shutil.copy2(source_path, destination_path)
    return destination_path
