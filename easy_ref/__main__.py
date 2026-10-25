"""Command-line interface for isolated, persisted builder/reviewer runs."""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from .adapters import build, REGISTRY
from .core import create, git, load, save
from .loop import answer, finish, request_stop, run, status
from .notify import notifier


def parser():
    result = argparse.ArgumentParser(prog='easy-ref', description='Requires Python 3.11+. Local agent worktrees; never publishes.')
    sub = result.add_subparsers(dest='command', required=True)
    command = sub.add_parser('run')
    command.add_argument('order')
    command.add_argument('--repo', default='.')
    for role in ('builder', 'reviewer'):
        command.add_argument('--' + role, choices=REGISTRY)
        command.add_argument('--' + role + '-model')
        command.add_argument('--' + role + '-timeout', type=float)
    command.add_argument('--round-limit', type=int)
    command.add_argument('--timeout', type=float)
    command.add_argument('--check-timeout', type=float)
    command.add_argument('--check', action='append', help='Repeatable command, split into arguments without a shell')
    command.add_argument('--worktree-root')
    command.add_argument('--notifier', choices=('auto', 'macos', 'terminal'))
    command.add_argument('--allow-unsandboxed', action='store_true', help='Explicitly allow Pi (no sandbox)')
    for name in ('status', 'answer', 'stop'):
        command = sub.add_parser(name)
        command.add_argument('run_id', nargs='?' if name == 'status' else None)
        command.add_argument('--repo', default='.')
        if name == 'answer':
            command.add_argument('decision')
    return result


def runs_root(repo):
    return Path(git(repo, 'rev-parse', '--absolute-git-dir')) / 'easy-ref' / 'runs'


def locate(repo, run_id):
    if not re.fullmatch('[a-f0-9]{32}', run_id):
        raise ValueError('invalid run id')
    root = runs_root(repo).resolve()
    directory = root / run_id
    if directory.is_symlink() or not directory.is_dir() or not (directory / 'run.json').is_file():
        raise ValueError('run not found in this repository')
    state = load(directory)
    if Path(state['run_dir']).resolve() != directory.resolve() or state['run_id'] != run_id:
        raise ValueError('run state identity mismatch')
    return directory


def dispatch(state):
    notify = notifier(state['config']['notifier'])
    try:
        adapters = {role: build(state['config'], role) for role in ('builder', 'reviewer')}
    except (OSError, ValueError) as exc:
        from .loop import locked
        with locked(state['run_dir']):
            current = load(state['run_dir'])
            if current['status'] in ('DONE', 'STOPPED'):
                return current
            return finish(current, 'adapter setup failed: ' + str(exc), notify=notify)

    def prepare(current, builder, reviewer):
        current['adapter_versions'] = {'builder': builder.verify(), 'reviewer': reviewer.verify()}

    return run(state['run_dir'], adapters['builder'], adapters['reviewer'], notify=notify, prepare=prepare)


def result_code(state):
    return {'DONE': 0, 'STOPPED': 130}.get(state['status'], 2)


def display(state):
    keys = ('run_id', 'status', 'phase', 'round', 'branch', 'worktree', 'reason', 'question',
            'warning', 'unsandboxed', 'ignored_changes')
    result = {key: state[key] for key in keys if key in state}
    result['checks'] = [{'command': c['command'], 'exit_code': c['exit_code']} for c in state['checks']]
    print(json.dumps(result, indent=2))


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'run':
            overrides = {key: value for key, value in vars(args).items()
                         if key not in ('command', 'order', 'repo', 'check') and value is not None}
            if args.check is not None:
                overrides['checks'] = [shlex.split(command) for command in args.check]
            state = create(args.repo, args.order, overrides)
            print('Run: ' + state['run_id'], flush=True)
            if state['warning']:
                print('Warning: ' + state['warning'], file=sys.stderr)
            if state['unsandboxed']:
                print('Warning: Pi has no sandbox; owner opted in.', file=sys.stderr)
            return result_code(dispatch(state))
        if args.command == 'status' and args.run_id is None:
            root = runs_root(args.repo)
            for directory in sorted(root.iterdir()) if root.exists() else []:
                if directory.is_dir():
                    checked = locate(args.repo, directory.name)
                    original = load(checked)
                    display(status(checked, notify=notifier(original['config']['notifier'])))
            return 0
        directory = locate(args.repo, args.run_id)
        state = load(directory)
        notify = notifier(state['config']['notifier'])
        if args.command == 'status':
            display(status(directory, notify=notify))
            return 0
        if args.command == 'stop':
            display(request_stop(directory, notify=notify))
            return 0
        # Recover a crashed worker before accepting an answer. Active runs refuse it.
        status(directory, notify=notify)
        state = answer(directory, args.decision)
        return result_code(dispatch(state))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print('easy-ref: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
