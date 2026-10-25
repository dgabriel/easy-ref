"""Codex exec with workspace-write builders and read-only reviewers."""
import json
from .common import Harness, SCHEMA, decode, structured
from ..process import execute, Result


class Adapter(Harness):
    executable = 'codex'
    help_args = ['exec', '--help']
    flags = ('--sandbox', '--cd', '--output-schema', '--output-last-message',
             '--ephemeral', '--ignore-user-config', '--model', '--config')

    def invoke(self, role, prompt, worktree, run_dir, timeout, *, env, stopped):
        self.validate_role(role)
        log = run_dir / f'{role}.log'
        final = run_dir / f'{role}-answer.txt'
        source = run_dir / f'{role}-input.txt'
        source.write_text(prompt)
        args = [self.executable, 'exec', '--sandbox', 'workspace-write' if role == 'builder' else 'read-only',
                '--cd', str(worktree), '--ephemeral', '--ignore-user-config',
                '--output-last-message', str(final), *self.model_args()]
        policy = {key: value for key, value in env.items()
                  if key == 'GIT_CONFIG_COUNT' or key.startswith(('GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_'))}
        toml_policy = '{' + ', '.join(json.dumps(k) + '=' + json.dumps(v) for k, v in policy.items()) + '}'
        args += ['--config', 'shell_environment_policy.set=' + toml_policy]
        if role == 'reviewer':
            schema = run_dir / 'verdict-schema.json'
            schema.write_text(json.dumps(SCHEMA))
            args += ['--output-schema', str(schema)]
        with source.open('rb') as stdin:
            code = execute([*args, '-'], worktree, log, timeout, env, stopped, stdin=stdin)
        message = final.read_text() if code == 0 and final.exists() else ''
        if role == 'reviewer' and code == 0:
            message = structured(decode(message))
        return Result(code, message, str(log))
