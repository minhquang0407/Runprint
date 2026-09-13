"""
Subprocess Runner with Live Tee Logging & Signal Handling
=========================================================
Spawns child processes, streams stdout/stderr live to user terminal while
teeing to disk files, forwards termination signals, and captures exit status.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO, List, Optional, Tuple


def _stream_pipe(pipe: IO[str], file_handle: IO[str], terminal_stream: IO[str]) -> None:
    """Read lines from a pipe, write to both file and terminal."""
    try:
        for line in iter(pipe.readline, ""):
            file_handle.write(line)
            file_handle.flush()
            terminal_stream.write(line)
            terminal_stream.flush()
    except (ValueError, OSError):
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass


class ExecutionResult:
    """Outcome of a wrapped subprocess execution."""

    def __init__(
        self,
        exit_code: int,
        duration_seconds: float,
        interrupted: bool = False,
    ):
        self.exit_code = exit_code
        self.duration_seconds = duration_seconds
        self.interrupted = interrupted


def run_command_with_tee(
    command: List[str],
    cwd: Path,
    stdout_log_path: Path,
    stderr_log_path: Path,
    env_overrides: Optional[dict] = None,
) -> ExecutionResult:
    """
    Execute `command` in `cwd`, teeing output live to terminal and log files.
    Gracefully handles Ctrl+C (SIGINT).
    """
    stdout_log_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_log_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    start_time = time.perf_counter()
    interrupted = False

    with open(stdout_log_path, "w", encoding="utf-8", errors="replace") as out_f, \
         open(stderr_log_path, "w", encoding="utf-8", errors="replace") as err_f:

        proc = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )

        t_out = threading.Thread(
            target=_stream_pipe,
            args=(proc.stdout, out_f, sys.stdout),
            daemon=True,
        )
        t_err = threading.Thread(
            target=_stream_pipe,
            args=(proc.stderr, err_f, sys.stderr),
            daemon=True,
        )

        t_out.start()
        t_err.start()

        # Handle SIGINT (Ctrl+C)
        def sigint_handler(signum, frame):
            nonlocal interrupted
            interrupted = True
            try:
                proc.send_signal(signal.SIGINT)
            except Exception:
                pass

        old_sigint = signal.signal(signal.SIGINT, sigint_handler)

        try:
            return_code = proc.wait()
        except KeyboardInterrupt:
            interrupted = True
            try:
                proc.terminate()
                return_code = proc.wait(timeout=5)
            except Exception:
                proc.kill()
                return_code = -1
        finally:
            signal.signal(signal.SIGINT, old_sigint)
            t_out.join(timeout=2)
            t_err.join(timeout=2)

    duration = round(time.perf_counter() - start_time, 2)
    return ExecutionResult(
        exit_code=return_code,
        duration_seconds=duration,
        interrupted=interrupted,
    )
