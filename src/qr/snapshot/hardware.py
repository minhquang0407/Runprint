"""
Hardware Snapshot Collector
===========================
Detects system CPU, available RAM, GPU model, GPU driver, and CUDA environment.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import List, Optional, Tuple
from qr.manifest import HardwareSnapshot


def _get_ram_gb() -> Optional[float]:
    """Retrieve total system RAM in GB across platforms."""
    try:
        if platform.system() == "Windows":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return round(stat.ullTotalPhys / (1024 ** 3), 2)
        elif platform.system() == "Linux":
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return round(kb / (1024 ** 2), 2)
    except Exception:
        pass
    return None


def _detect_gpus() -> Tuple[List[str], Optional[str], Optional[str]]:
    """Detect NVIDIA GPUs, driver version, and CUDA version via nvidia-smi."""
    gpu_names: List[str] = []
    driver_version: Optional[str] = None
    cuda_version: Optional[str] = None

    if not shutil.which("nvidia-smi"):
        return gpu_names, driver_version, cuda_version

    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if parts:
                    gpu_names.append(parts[0])
                if len(parts) > 1 and not driver_version:
                    driver_version = parts[1]
    except Exception:
        pass

    try:
        proc = subprocess.run(
            ["nvcc", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if "release" in line:
                    cuda_version = line.strip()
                    break
    except Exception:
        pass

    return gpu_names, driver_version, cuda_version


def capture_hardware_snapshot() -> HardwareSnapshot:
    """Collect hardware specs of the current host machine."""
    cpu_name = platform.processor() or platform.machine()
    cpu_count = os.cpu_count()
    ram_gb = _get_ram_gb()
    gpus, driver, cuda = _detect_gpus()

    return HardwareSnapshot(
        cpu=cpu_name if cpu_name else None,
        cpu_count=cpu_count,
        ram_gb=ram_gb,
        gpu=gpus,
        gpu_driver=driver,
        cuda=cuda,
    )
