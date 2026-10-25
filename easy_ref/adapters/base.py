"""Small adapter contract; implementations must use the guarded process runner."""
from pathlib import Path
from typing import Callable, Protocol
from ..process import Result


class Adapter(Protocol):
    def invoke(self, role: str, prompt: str, worktree: Path, run_dir: Path,
               timeout: float, *, env: dict[str, str], stopped: Callable[[], bool]) -> Result:
        """Honor timeout/stop with process-group cleanup; return a private log path.

        env is the mandatory push-block environment supplied by the loop.
        Raise on timeout or interruption. Never enable additional network access.
        """
        ...
