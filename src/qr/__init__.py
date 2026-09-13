"""
QR — Reproducible Research Execution Wrapper
=============================================
Run anything. Capture everything needed to reproduce it.
"""

from qr.sdk import artifact, input_dataset, log, note

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "log",
    "artifact",
    "input_dataset",
    "note",
]
