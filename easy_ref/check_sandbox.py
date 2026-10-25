"""Resolve check isolation once and distinguish sandbox errors from check exits."""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from .process import execute


def resolve(mode):
    reason = 'disabled by owner'
    executable = None
    if mode != 'none':
        reason = 'requires macOS'
        if platform.system() == 'Darwin':
            executable = shutil.which('codex')
            reason = 'codex is missing'
            if executable:
                try:
                    with tempfile.TemporaryDirectory() as temporary:
                        log = Path(temporary) / 'help'
                        code = execute([executable, 'sandbox', '--help'], temporary, log, 10,
                                       os.environ.copy())
                        help_text = log.read_text(errors='replace')
                    if code == 0 and all(re.search(pattern, help_text) for pattern in (
                            r'-P,\s+--permission-profile', r'-c,\s+--config', r'-C,\s+--cd',
                            r'\[COMMAND\]')):
                        return {'mode': 'codex', 'executable': executable}, ''
                    reason = 'codex sandbox help lacks required options'
                except (OSError, TimeoutError) as exc:
                    reason = f'codex sandbox help failed: {exc}'
        if mode == 'codex':
            raise ValueError('check sandbox unavailable: ' + reason)
    return {'mode': 'none'}, 'Checks run unsandboxed with owner permissions: ' + reason + '.'


# Isolated Python ignores worktree modules and Python environment customization.
# The receipt is emitted only after the command starts and finishes. A launcher
# error, signal, or missing receipt fails closed, regardless of Codex exit code.
LAUNCH = '''import json, subprocess, sys
result = subprocess.run(sys.argv[2:], stdin=subprocess.DEVNULL)
print("\\n" + sys.argv[1] + json.dumps(result.returncode), flush=True)
'''


def run(selection, command, worktree, path, timeout, env, stopped):
    if selection['mode'] == 'none':
        return execute(command, worktree, path, timeout, env, stopped)
    if selection['mode'] != 'codex':
        raise ValueError('invalid frozen check sandbox')
    policy = {k: v for k, v in env.items() if k == 'GIT_CONFIG_COUNT'
              or k.startswith(('GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_'))}
    setting = '{' + ', '.join(json.dumps(k) + '=' + json.dumps(v) for k, v in policy.items()) + '}'
    marker = 'easy-ref-check-result-' + uuid.uuid4().hex + ':'
    argv = [selection['executable'], 'sandbox', '-P', ':workspace',
            '-c', 'shell_environment_policy.set=' + setting, '-C', str(worktree), '--',
            sys.executable, '-I', '-c', LAUNCH, marker, *command]
    code = execute(argv, worktree, path, timeout, env, stopped)
    output = path.read_text(errors='replace')
    matches = re.findall(r'^' + re.escape(marker) + r'(-?\d+)\n', output, re.MULTILINE)
    if code != 0 or len(matches) != 1:
        raise ValueError(f'check sandbox failed to start or complete (exit {code})')
    path.write_text(re.sub(r'\n' + re.escape(marker) + r'-?\d+\n', '', output))
    return int(matches[0])
