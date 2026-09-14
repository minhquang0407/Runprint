"""
Runprint Package
================
Runprint is the project distribution package for QR.
Re-exports the QR API: `import runprint` or `import qr`.
"""

import qr
from qr import (
    __version__,
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
