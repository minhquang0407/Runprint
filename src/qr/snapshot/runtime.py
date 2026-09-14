"""
Runtime Environment Collector
=============================
Captures OS, Python runtime, installed package snapshot (pip freeze), and safe
non-sensitive environment variables (redacting secrets).
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set
from qr.manifest import RuntimeSnapshot

# Strict allowlist of environment variables relevant to execution determinism & reproducibility
SAFE_REPRODUCIBILITY_ENV_VARS: Set[str] = {
    # CUDA / GPU determinism & config
    "CUDA_VISIBLE_DEVICES",
    "CUDA_LAUNCH_BLOCKING",
    "CUBLAS_WORKSPACE_CONFIG",
    "TORCH_USE_CUDA_DSA",
    "PYTORCH_CUDA_ALLOC_CONF",
    "NCCL_DEBUG",
    # Threading & CPU parallelism
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    # Python determinism
    "PYTHONHASHSEED",
    "PYTHONOPTIMIZE",
    "PYTHONPATH",
    # Framework determinism & offline flags
    "TF_DETERMINISTIC_OPS",
    "TF_CUDNN_DETERMINISTIC",
    "TOKENIZERS_PARALLELISM",
    "HF_DATASETS_OFFLINE",
    "TRANSFORMERS_OFFLINE",
    # Environment & locale
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
}

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


def load_custom_env_allowlist(repo_root: Optional[Path] = None) -> Set[str]:
    """Load user-defined allowed environment variable keys from .qr/project.json if present."""
    if repo_root is None:
        return set()
    proj_file = repo_root / ".qr" / "project.json"
    if not proj_file.is_file():
        return set()
    try:
        data = json.loads(proj_file.read_text(encoding="utf-8"))
        custom_keys = data.get("capture_env", [])
        if isinstance(custom_keys, list):
            return {str(k) for k in custom_keys}
    except Exception:
        pass
    return set()


def filter_environment_variables(
    repo_root: Optional[Path] = None,
    extra_allowed_keys: Optional[Set[str]] = None,
) -> Dict[str, str]:
    """
    Capture only safe reproducibility-related environment variables using a strict allowlist.
    Never dumps arbitrary credentials or system variables.
    """
    allowed = set(SAFE_REPRODUCIBILITY_ENV_VARS)
    if extra_allowed_keys:
        allowed.update(extra_allowed_keys)
    if repo_root:
        allowed.update(load_custom_env_allowlist(repo_root))

    safe_env: Dict[str, str] = {}
    for k, v in os.environ.items():
        if k in allowed or k.startswith("QR_") or k.startswith("RUNPRINT_"):
            # Block sensitive keys even if erroneously specified in custom allowlist
            if is_sensitive_key(k):
                continue
            # Limit length of captured values to avoid gigantic env payloads
            safe_env[k] = v[:500]
    return safe_env


def capture_pip_freeze(env_dir: Path, python_executable: Optional[str] = None) -> Optional[str]:
    """Run pip freeze and write output to environment/pip-freeze.txt."""
    env_dir.mkdir(parents=True, exist_ok=True)
    freeze_file = env_dir / "pip-freeze.txt"
    py_bin = python_executable or sys.executable
    try:
        proc = subprocess.run(
            [py_bin, "-m", "pip", "freeze"],
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


def capture_runtime_snapshot(
    run_dir: Path,
    repo_root: Optional[Path] = None,
    extra_allowed_keys: Optional[Set[str]] = None,
    python_executable: Optional[str] = None,
) -> RuntimeSnapshot:
    """Capture runtime environment snapshot and save package lock."""
    env_dir = run_dir / "environment"
    lock_rel = capture_pip_freeze(env_dir, python_executable=python_executable)

    os_desc = f"{platform.system()} {platform.release()} ({platform.machine()})"

    py_bin = python_executable or sys.executable
    py_ver = platform.python_version()
    if python_executable and python_executable != sys.executable:
        try:
            ver_proc = subprocess.run(
                [python_executable, "-c", "import platform; print(platform.python_version())"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            if ver_proc.returncode == 0 and ver_proc.stdout.strip():
                py_ver = ver_proc.stdout.strip()
        except Exception:
            pass

    return RuntimeSnapshot(
        os=os_desc,
        python_version=py_ver,
        python_executable=py_bin,
        packages_lock=lock_rel,
        env_vars=filter_environment_variables(repo_root=repo_root, extra_allowed_keys=extra_allowed_keys),
    )

