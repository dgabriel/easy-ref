"""Claude Code: confined file tools and sandboxed builder shell commands."""
import json
from .common import Harness, SCHEMA, decode, structured
from ..process import execute, Result


class Adapter(Harness):
    executable = 'claude'
    flags = ('--print', '--output-format', '--json-schema', '--permission-mode', '--permission-prompts',
             '--restricted', '--safe-mode', '--tools', '--disallowedTools', '--settings',
             '--strict-mcp-config', '--mcp-config', '--no-session-persistence', '--model')

    def invoke(self, role, prompt, worktree, run_dir, timeout, *, env, stopped):
        self.validate_role(role)
        log = run_dir / f'{role}.log'
        stdout = run_dir / f'{role}-stdout.json'
        source = run_dir / f'{role}-input.txt'
        source.write_text(prompt)
        args = [self.executable, '--print', '--output-format', 'json', '--restricted', '--safe-mode',
                '--strict-mcp-config', '--mcp-config', json.dumps({'mcpServers': {}}), '--no-session-persistence',
                '--permission-prompts', 'none', *self.model_args()]
        if role == 'builder':
            settings = {'sandbox': {'enabled': True, 'failIfUnavailable': True,
                                   'autoAllowBashIfSandboxed': True, 'allowUnsandboxedCommands': False}}
            args += ['--permission-mode', 'acceptEdits', '--tools', 'Read,Grep,Glob,Edit,Write,Bash',
                     '--settings', json.dumps(settings)]
        else:
            # No general shell: it cannot be made read-only with a tool denylist.
            args += ['--permission-mode', 'manual', '--tools', 'Read,Grep,Glob',
                     '--disallowedTools', 'Edit,Write,NotebookEdit,Bash,Agent,Task',
                     '--json-schema', json.dumps(SCHEMA)]
        with source.open('rb') as stdin:
            code = execute(args, worktree, log, timeout, env, stopped, stdin=stdin, stdout_path=stdout)
        if code:
            return Result(code, '', str(log))
        envelope = decode(stdout.read_text())
        if not isinstance(envelope, dict) or envelope.get('type') != 'result' or envelope.get('is_error') is not False or envelope.get('subtype') != 'success':
            raise ValueError('Claude did not return a successful final result')
        denials = envelope.get('permission_denials', [])
        if denials:
            raise ValueError('Claude reported permission denials; owner intervention required')
        if role == 'reviewer':
            # Do not fall back to unstructured text if structured output failed.
            message = structured(envelope['structured_output'])
        else:
            message = envelope.get('result', '')
        return Result(0, message, str(log))
