"""Bounded subprocess execution shared by checks and future adapters."""
from contextlib import ExitStack
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


def execute(argv, cwd, log_path, timeout, env, stopped=lambda: False, *, stdin=subprocess.DEVNULL, stdout_path=None):
    """No shell; terminate the process group on timeout, stop, or interruption."""
    with ExitStack() as stack:
        output = stack.enter_context(Path(log_path).open('wb'))
        stdout = stack.enter_context(Path(stdout_path).open('wb')) if stdout_path else output
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=stdin, stdout=stdout,
                                   stderr=output if stdout_path else subprocess.STDOUT, start_new_session=True)
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
