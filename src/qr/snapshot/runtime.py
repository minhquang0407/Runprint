"""
Runtime Environment Collector
=============================
Captures OS, Python runtime, installed package snapshot (pip freeze), and safe
non-sensitive environment variables (redacting secrets).
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional
from qr.manifest import RuntimeSnapshot

SENSITIVE_KEY_PATTERNS: List[str] = [
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "KEY",
    "AUTH",
    "CREDENTIAL",
    "PRIVATE",
    "AWS_",
    "GITHUB_",
    "OPENAI_",
    "ANTHROPIC_",
    "GEMINI_",
    "API",
]


def is_sensitive_key(key: str) -> bool:
    """Check whether an environment variable name likely contains secrets."""
    upper_key = key.upper()
    return any(pattern in upper_key for pattern in SENSITIVE_KEY_PATTERNS)


def filter_environment_variables() -> Dict[str, str]:
    """Capture only safe environment variables, redacting potential secrets."""
    safe_env: Dict[str, str] = {}
    for k, v in os.environ.items():
        if not is_sensitive_key(k):
            # Limit length of captured values to avoid gigantic env payloads
            safe_env[k] = v[:500]
    return safe_env


def capture_pip_freeze(env_dir: Path) -> Optional[str]:
    """Run pip freeze and write output to environment/pip-freeze.txt."""
    env_dir.mkdir(parents=True, exist_ok=True)
    freeze_file = env_dir / "pip-freeze.txt"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if proc.returncode == 0 and proc.stdout:
            freeze_file.write_text(proc.stdout, encoding="utf-8")
            return "environment/pip-freeze.txt"
    except Exception:
        pass
    return None


def capture_runtime_snapshot(run_dir: Path) -> RuntimeSnapshot:
    """Capture runtime environment snapshot and save package lock."""
    env_dir = run_dir / "environment"
    lock_rel = capture_pip_freeze(env_dir)

    os_desc = f"{platform.system()} {platform.release()} ({platform.machine()})"
    py_ver = platform.python_version()

    return RuntimeSnapshot(
        os=os_desc,
        python_version=py_ver,
        python_executable=sys.executable,
        packages_lock=lock_rel,
        env_vars=filter_environment_variables(),
    )
