"""easy-ref requires Python 3.11 or newer, with no third-party dependencies."""
import sys

if sys.version_info < (3, 11):
    raise RuntimeError("easy-ref requires Python 3.11 or newer; use a Python 3.11+ interpreter.")
