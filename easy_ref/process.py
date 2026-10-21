"""Bounded subprocess execution shared by checks and future adapters."""
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import time


@dataclass(frozen=True)
class Result:
    exit_code: int
    final_message: str
    log_path: str


def execute(argv, cwd, log_path, timeout, env, stopped=lambda: False, *, stdin=subprocess.DEVNULL):
    """No shell; terminate the process group on timeout, stop, or interruption."""
    with Path(log_path).open('wb') as output:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=stdin, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if stopped():
                    raise InterruptedError('owner requested stop')
                if time.monotonic() >= deadline:
                    raise TimeoutError('subprocess timed out')
                time.sleep(0.02)
            return process.returncode
        finally:
            # Also clean up children left behind by a successful parent.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
