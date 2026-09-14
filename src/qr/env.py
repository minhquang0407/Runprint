"""
Environment Drift Detection & Comparison
=========================================
Parses pip freeze lockfiles, compares installed packages against the current
Python environment, and identifies missing packages, version drift, and extras.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def canonicalize_package_name(name: str) -> str:
    """Normalize package name per PEP 503 (lowercase, dashes for underscores/dots)."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def parse_freeze_text(text: str) -> Dict[str, str]:
    """
    Parse the content of a pip freeze file into {canonical_name: version_str}.
    Handles standard `pkg==1.0.0`, direct URLs `pkg @ url`, and editable `-e` formats.
    """
    packages: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("-e "):
            # Editable package: e.g. -e git+https://...#egg=mypkg or -e /path/to/pkg
            part = line[3:].strip()
            egg_idx = part.lower().find("#egg=")
            if egg_idx != -1:
                name = part[egg_idx + 5 :].split("&")[0].strip()
                packages[canonicalize_package_name(name)] = "editable"
            else:
                name = Path(part).name
                packages[canonicalize_package_name(name)] = "editable"
            continue

        if " @ " in line:
            parts = line.split(" @ ", 1)
            name = canonicalize_package_name(parts[0].strip())
            packages[name] = parts[1].strip()
            continue

        if "==" in line:
            parts = line.split("==", 1)
            name = canonicalize_package_name(parts[0].strip())
            packages[name] = parts[1].strip()
            continue

        if ">=" in line:
            parts = line.split(">=", 1)
            name = canonicalize_package_name(parts[0].strip())
            packages[name] = f">={parts[1].strip()}"
            continue

        if "~=" in line:
            parts = line.split("~=", 1)
            name = canonicalize_package_name(parts[0].strip())
            packages[name] = f"~={parts[1].strip()}"
            continue

        # Single name without version specifier
        cleaned = canonicalize_package_name(line)
        if cleaned:
            packages[cleaned] = "installed"

    return packages


def get_current_environment_packages() -> Dict[str, str]:
    """Run `pip freeze` on current python interpreter and return parsed packages dict."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        if proc.returncode == 0 and proc.stdout:
            return parse_freeze_text(proc.stdout)
    except Exception:
        pass
    return {}


@dataclass
class EnvDiffReport:
    recorded_python: Optional[str]
    current_python: str
    python_match: bool
    missing_packages: Dict[str, str] = field(default_factory=dict)
    version_mismatches: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    extra_packages: Dict[str, str] = field(default_factory=dict)
    matching_packages: Dict[str, str] = field(default_factory=dict)

    @property
    def has_drift(self) -> bool:
        return bool(self.missing_packages or self.version_mismatches or not self.python_match)

    @property
    def is_exact_match(self) -> bool:
        return self.python_match and not self.missing_packages and not self.version_mismatches and not self.extra_packages


def diff_environments(
    recorded_lock_content: str,
    recorded_python: Optional[str] = None,
    current_packages: Optional[Dict[str, str]] = None,
) -> EnvDiffReport:
    """
    Compare recorded package requirements with current Python environment.
    """
    recorded_pkgs = parse_freeze_text(recorded_lock_content)
    current_pkgs = current_packages if current_packages is not None else get_current_environment_packages()

    current_py = platform.python_version()
    # Python matches if major.minor match
    py_match = True
    if recorded_python:
        rec_major_minor = ".".join(recorded_python.split(".")[:2])
        cur_major_minor = ".".join(current_py.split(".")[:2])
        py_match = (rec_major_minor == cur_major_minor)

    missing: Dict[str, str] = {}
    version_mismatches: Dict[str, Tuple[str, str]] = {}
    matching: Dict[str, str] = {}

    for pkg, rec_ver in recorded_pkgs.items():
        if pkg not in current_pkgs:
            missing[pkg] = rec_ver
        else:
            cur_ver = current_pkgs[pkg]
            if cur_ver == rec_ver:
                matching[pkg] = rec_ver
            else:
                version_mismatches[pkg] = (rec_ver, cur_ver)

    extra: Dict[str, str] = {
        pkg: cur_ver for pkg, cur_ver in current_pkgs.items() if pkg not in recorded_pkgs
    }

    return EnvDiffReport(
        recorded_python=recorded_python,
        current_python=current_py,
        python_match=py_match,
        missing_packages=missing,
        version_mismatches=version_mismatches,
        extra_packages=extra,
        matching_packages=matching,
    )


def get_venv_bin_dir(venv_dir: Path) -> Path:
    """Return the directory containing executables inside the virtual environment."""
    if sys.platform == "win32":
        return venv_dir / "Scripts"
    return venv_dir / "bin"


def get_venv_python(venv_dir: Path) -> Path:
    """Return the path to the Python executable in the virtual environment."""
    bin_dir = get_venv_bin_dir(venv_dir)
    if sys.platform == "win32":
        return bin_dir / "python.exe"
    return bin_dir / "python"


def is_valid_venv(venv_dir: Path) -> bool:
    """Check whether venv_dir exists and has a functioning python executable."""
    py_bin = get_venv_python(venv_dir)
    return py_bin.is_file() and os.access(str(py_bin), os.X_OK | os.R_OK)


def is_uv_available() -> bool:
    """Check if `uv` CLI is available on system PATH."""
    try:
        proc = subprocess.run(
            ["uv", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return proc.returncode == 0
    except (FileNotFoundError, PermissionError):
        return False


def sanitize_freeze_for_install(freeze_text: str) -> str:
    """
    Sanitize recorded pip freeze text so it can be installed reliably into a fresh venv.
    - Strips local `@ file://` references if the local directory/archive cannot be resolved.
    - Preserves standard versions (`pkg==1.2.3`), git URLs (`pkg @ git+https://...`).
    - Strips local editable installs (`-e .`, `-e /local/path`) unless pointing to remote git URLs.
    """
    clean_lines: List[str] = []
    for line in freeze_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Handle local file:// installs: e.g. pkg @ file:///path/to/archive
        if "@ file://" in line or "@ file:///" in line:
            parts = line.split("@", 1)
            pkg_name = parts[0].strip()
            url_part = parts[1].strip()
            file_path_str = re.sub(r"^file:///?", "", url_part)
            if Path(file_path_str).exists():
                clean_lines.append(line)
            else:
                if pkg_name:
                    clean_lines.append(pkg_name)
            continue

        # Handle editable installs
        if line.startswith("-e "):
            part = line[3:].strip()
            if "git+" in part or "http://" in part or "https://" in part:
                clean_lines.append(line)
            else:
                egg_idx = part.lower().find("#egg=")
                if egg_idx != -1:
                    clean_lines.append(part[egg_idx + 5 :].split("&")[0].strip())
            continue

        clean_lines.append(line)

    return "\n".join(clean_lines) + "\n"


def _robust_rmtree(path: Path) -> None:
    """Robustly remove directory trees on all platforms, clearing read-only flags (e.g. .git files on Windows)."""
    if not path.exists():
        return

    import os
    import stat

    def remove_readonly(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(
                path,
                onexc=lambda func, p, exc: remove_readonly(func, p, (type(exc), exc, exc.__traceback__)),
            )
        else:
            shutil.rmtree(path, onerror=remove_readonly)
    except Exception:
        pass

    if path.exists():
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass


def create_isolated_environment(
    venv_dir: Path,
    lock_path: Path,
    python_version: Optional[str] = None,
    recreate: bool = False,
) -> Path:
    """
    Create a dedicated virtual environment from a package lockfile.
    Uses `uv` if available for sub-second installs; otherwise falls back to `venv` + `pip`.
    Returns the path to the virtual environment's Python executable.
    """
    venv_dir = venv_dir.resolve()
    py_executable = get_venv_python(venv_dir)

    if venv_dir.exists() and not recreate:
        if is_valid_venv(venv_dir):
            return py_executable
        _robust_rmtree(venv_dir)

    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    if venv_dir.exists():
        _robust_rmtree(venv_dir)

    use_uv = is_uv_available()

    # Step 1: Create virtual environment
    if use_uv:
        create_cmd = ["uv", "venv", str(venv_dir)]
        if python_version:
            create_cmd.extend(["--python", python_version])
        res = subprocess.run(create_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            res = subprocess.run(
                [sys.executable, "-m", "venv", str(venv_dir)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if res.returncode != 0:
                raise RuntimeError(f"Failed to create virtual environment: {res.stderr.strip()}")
            use_uv = False
    else:
        res = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if res.returncode != 0:
            raise RuntimeError(f"Failed to create virtual environment: {res.stderr.strip()}")

    if not is_valid_venv(venv_dir):
        raise RuntimeError(f"Virtual environment created at {venv_dir} is invalid: missing {py_executable}")

    # Step 2: Install packages from lockfile
    if lock_path.is_file():
        lock_content = lock_path.read_text(encoding="utf-8", errors="replace")
        clean_reqs = sanitize_freeze_for_install(lock_content)
        req_file = venv_dir / "clean-requirements.txt"
        req_file.write_text(clean_reqs, encoding="utf-8")

        if clean_reqs.strip():
            if use_uv:
                install_cmd = [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(py_executable),
                    "-r",
                    str(req_file),
                ]
            else:
                install_cmd = [
                    str(py_executable),
                    "-m",
                    "pip",
                    "install",
                    "--no-warn-script-location",
                    "-r",
                    str(req_file),
                ]

            inst_res = subprocess.run(
                install_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if inst_res.returncode != 0:
                raise RuntimeError(
                    f"Failed to install packages into restored environment:\n{inst_res.stderr.strip()}"
                )

    return py_executable


def list_cached_envs(qr_dir: Path) -> List[Dict[str, Any]]:
    """List all cached virtual environments under .qr/envs/."""
    envs_dir = qr_dir / "envs"
    if not envs_dir.is_dir():
        return []

    results: List[Dict[str, Any]] = []
    for item in envs_dir.iterdir():
        if item.is_dir() and item.name.startswith("env_"):
            run_id = item.name[4:]
            valid = is_valid_venv(item)
            size_bytes = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
            results.append({
                "run_id": run_id,
                "name": item.name,
                "path": str(item),
                "valid": valid,
                "size_mb": round(size_bytes / (1024 * 1024), 1),
                "created_at": datetime.fromtimestamp(item.stat().st_ctime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            })

    results.sort(key=lambda x: x["created_at"], reverse=True)
    return results


def clean_cached_envs(qr_dir: Path, run_id: Optional[str] = None) -> int:
    """Remove cached virtual environments under .qr/envs/. Returns count of removed environments."""
    envs_dir = qr_dir / "envs"
    if not envs_dir.is_dir():
        return 0

    removed = 0
    if run_id:
        target = envs_dir / f"env_{run_id}"
        if target.is_dir():
            _robust_rmtree(target)
            removed += 1
    else:
        for item in envs_dir.iterdir():
            if item.is_dir() and item.name.startswith("env_"):
                _robust_rmtree(item)
                removed += 1

    return removed

