"""
QR — Reproducible Research Execution Wrapper
=============================================
Run anything. Capture everything needed to reproduce it.
"""

from qr.sdk import (
    activate,
    artifact,
    finish,
    init,
    input_dataset,
    log,
    note,
    params,
    run,
    timer,
)

__version__ = "0.1.6"

__all__ = [
    "__version__",
    "log",
    "artifact",
    "input_dataset",
    "note",
    "timer",
    "activate",
    "init",
    "finish",
    "params",
    "run",
]
