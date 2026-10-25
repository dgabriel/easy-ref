"""Pi has no sandbox; explicit owner opt-in is mandatory for either role."""
from .common import Harness
from ..process import execute, Result


class Adapter(Harness):
    executable = 'pi'
    flags = ('--print', '--tools', '--no-session', '--no-extensions', '--no-skills',
             '--no-prompt-templates', '--no-themes', '--model')

    def __init__(self, model=None, allow_unsandboxed=False):
        if not allow_unsandboxed:
            raise ValueError('Pi has no sandbox: require --allow-unsandboxed')
        super().__init__(model, allow_unsandboxed)

    def invoke(self, role, prompt, worktree, run_dir, timeout, *, env, stopped):
        self.validate_role(role)
        source = run_dir / f'{role}-input.txt'
        source.write_text(prompt + '\nReturn the reviewer verdict in a fenced json block when reviewing.\n')
        log = run_dir / f'{role}.log'
        stdout = run_dir / f'{role}-stdout.txt'
        args = [self.executable, '--print', '--no-session', '--no-extensions', '--no-skills',
                '--no-prompt-templates', '--no-themes', '--tools',
                'read,grep,find,ls,bash,edit,write' if role == 'builder' else 'read,grep,find,ls',
                *self.model_args(), '--', '@' + str(source)]
        code = execute(args, worktree, log, timeout, env, stopped, stdout_path=stdout)
        return Result(code, stdout.read_text() if code == 0 else '', str(log))
