"""
Run Manifest Data Models (Schema v0.1)
======================================
Defines the schema for captured experiment provenance, execution metadata,
inputs, outputs, and system state according to the QR v0.1 specification.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class GitSnapshot(BaseModel):
    """Git version control state at the time of snapshotting."""
    commit: Optional[str] = Field(default=None, description="HEAD commit hash")
    branch: Optional[str] = Field(default=None, description="Active branch name")
    dirty: bool = Field(default=False, description="Whether working tree had uncommitted changes")
    diff_file: Optional[str] = Field(default=None, description="Relative path to git.diff if dirty")
    remote_url: Optional[str] = Field(default=None, description="Origin remote repository URL")
    modified_files: List[str] = Field(default_factory=list, description="List of uncommitted modified files")
    untracked_ignored: List[str] = Field(default_factory=list, description="List of untracked files ignored due to .qrignore or size limits")



class RuntimeSnapshot(BaseModel):
    """Runtime execution environment snapshot."""
    os: str = Field(description="Operating system name and version")
    python_version: str = Field(description="Python version string")
    python_executable: str = Field(description="Path to python binary")
    packages_lock: Optional[str] = Field(default=None, description="Relative path to pip/uv lock file")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="Captured non-secret environment variables")


class HardwareSnapshot(BaseModel):
    """Hardware resources available at run time."""
    cpu: Optional[str] = Field(default=None, description="CPU model name")
    cpu_count: Optional[int] = Field(default=None, description="Number of logical CPU cores")
    ram_gb: Optional[float] = Field(default=None, description="Total system RAM in gigabytes")
    gpu: List[str] = Field(default_factory=list, description="List of GPU device names")
    gpu_driver: Optional[str] = Field(default=None, description="NVIDIA/accelerator driver version")
    cuda: Optional[str] = Field(default=None, description="CUDA runtime version")


class DatasetInput(BaseModel):
    """Declared dataset reference and fingerprint."""
    name: str = Field(description="Dataset identifier or name")
    uri: str = Field(description="Path or URI to the dataset")
    version: Optional[str] = Field(default=None, description="Dataset version tag")
    fingerprint: Optional[str] = Field(default=None, description="Cryptographic hash or checksum")
    sha256: Optional[str] = Field(default=None, description="SHA-256 hash or checksum")

    @property
    def path(self) -> str:
        return self.uri


class RunInputs(BaseModel):
    """Declared or detected inputs to the experiment."""
    configs: List[str] = Field(default_factory=list, description="Config file paths detected or declared")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="CLI parameters extracted from command argv")
    datasets: List[DatasetInput] = Field(default_factory=list, description="Input dataset references")


class ArtifactItem(BaseModel):
    """Declared or detected artifact output."""
    path: str = Field(description="File or directory path")
    kind: Optional[str] = Field(default="generic", description="Kind of artifact (model, log, eval, etc.)")
    size_bytes: Optional[int] = Field(default=None, description="File size in bytes")
    checksum: Optional[str] = Field(default=None, description="SHA256 checksum if calculated")


class Timestamps(BaseModel):
    """Run lifecycle timestamps in ISO 8601 format."""
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = Field(default=None)


class RunManifest(BaseModel):
    """The central Run Manifest (v0.1) recording complete execution provenance."""
    schema_version: str = Field(default="0.1", description="QR manifest schema version")
    run_id: str = Field(description="Unique Run identifier (e.g. QR-20260914-A7F2)")
    parent_run_id: Optional[str] = Field(default=None, description="Parent run ID if this is a rerun")
    tags: List[str] = Field(default_factory=list, description="Tags associated with this run")
    command: List[str] = Field(description="Executed command and arguments")
    cwd: str = Field(description="Working directory where run was initiated")
    timestamps: Timestamps = Field(default_factory=Timestamps)
    git: Optional[GitSnapshot] = Field(default=None)
    runtime: RuntimeSnapshot
    hardware: HardwareSnapshot
    inputs: RunInputs = Field(default_factory=RunInputs)
    status: str = Field(default="created", description="created | running | completed | failed | interrupted")
    exit_code: Optional[int] = Field(default=None)
    duration_seconds: Optional[float] = Field(default=None)
    restorability_score: Optional[int] = Field(default=None, description="Calculated restorability score (0-100)")
    restorability_status: Optional[str] = Field(default=None, description="HIGHLY_RESTORABLE | PARTIALLY_RESTORABLE | LOW_RESTORABILITY")
    metrics_file: Optional[str] = Field(default="metrics.jsonl")
    artifacts_file: Optional[str] = Field(default="artifacts.json")
    stdout_file: Optional[str] = Field(default="stdout.log")
    stderr_file: Optional[str] = Field(default="stderr.log")

    def to_json(self, indent: int = 2) -> str:
        """Serialize manifest to JSON string."""
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> RunManifest:
        """Deserialize manifest from JSON string."""
        return cls.model_validate_json(json_str)

    @classmethod
    def from_file(cls, path: Path) -> RunManifest:
        """Load manifest from file."""
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
