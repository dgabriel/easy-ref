"""Pluggable terminal/macOS notification, with a terminal fallback."""
import shutil
import subprocess
import sys

SCRIPT = 'on run argv\n display notification (item 1 of argv) with title "easy-ref"\nend run'


def notifier(name='auto'):
    if name not in ('auto', 'macos', 'terminal'):
        raise ValueError('unknown notifier')

    def notify(message):
        print(message)
        if name == 'terminal' or sys.platform != 'darwin':
            return
        executable = shutil.which('osascript')
        if not executable:
            return
        try:
            # Message is an argument, never interpolated into AppleScript source.
            subprocess.run([executable, '-e', SCRIPT, message[:1000]], stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=5, check=True)
        except (OSError, subprocess.SubprocessError):
            pass  # The terminal already received the full summary.
    return notify
