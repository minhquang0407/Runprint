"""
Snapshot Collectors Package
===========================
Gathers system, git provenance, and runtime environment data prior to execution.
"""

from qr.snapshot.git import capture_git_snapshot
from qr.snapshot.hardware import capture_hardware_snapshot
from qr.snapshot.runtime import capture_runtime_snapshot

__all__ = [
    "capture_git_snapshot",
    "capture_runtime_snapshot",
    "capture_hardware_snapshot",
]
