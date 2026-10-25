"""Fail-closed loop using injected adapters; no live harness integrations."""
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import re
import shlex
import subprocess

from .core import ignored_fingerprint, fingerprint, git, load, push_env, refs, save
from .process import execute
from .check_sandbox import run as run_check
from .verdict import parse
from .skills import section as skill_section


class RunBusy(ValueError):
    """An active worker holds the run mutation lock."""


@contextmanager
def locked(directory):
    with (Path(directory) / 'lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RunBusy('run is already active') from None
        yield


def stop_requested(state):
    return (Path(state['run_dir']) / 'stop-request').exists()


def request_stop(directory, notify=print):
    (Path(directory) / 'stop-request').touch()
    try:
        with locked(directory):
            state = load(directory)
            if state['status'] in ('DONE', 'STOPPED'):
                return state
            return finish(state, 'owner requested stop', 'STOPPED', notify=notify)
    except RunBusy:
        return load(directory)


def status(directory, notify=print):
    try:
        with locked(directory):
            state = load(directory)
            if state['status'] == 'RUNNING':
                return finish(state, 'no active worker; interrupted run requires owner inspection', notify=notify)
            return state
    except RunBusy:
        return load(directory)


def finish(state, reason, status='NEEDS_OWNER', question='', origin='builder', notify=print):
    if not question and status == 'NEEDS_OWNER':
        question = 'Inspect the stop reason and decide how to proceed.'
    state.update(status=status, reason=reason, question=question, question_origin=origin)
    save(state)
    text = (f"{status}: {reason}\nRounds: {state['round']}\nBranch: {state['branch']}\n"
            f"Worktree: {state['worktree']}\nRemove manually when ready: "
            f"git -C {shlex.quote(state['repo'])} worktree remove -- {shlex.quote(state['worktree'])}\n"
            f"Check sandbox: {state.get('check_sandbox', {'mode': 'none'})['mode']}\n"
            f"Owner-supplied skills: {json.dumps(state.get('skills', {}))}\n"
            f"Checks: {json.dumps(state['checks'])}\nQuestion: {question}\n"
            f"Configuration changed: {state.get('config_changed', False)}\n"
            f"Warning: {state.get('warning', '')}\n"
            f"Unsandboxed adapters (Pi): {state.get('unsandboxed', [])}\n"
            f"Ignored paths changed during review: {state.get('ignored_changes', [])}\n"
            f"Remote ref movement: {state.get('remote_movement', '')}\n"
            'Publishing guardrails are best-effort, not isolation.\n')
    (Path(state['run_dir']) / 'summary.txt').write_text(text)
    try:
        notify(text)
    except Exception:
        print(text)
    return state


def identity(state):
    worktree = Path(state['worktree'])
    if worktree.is_symlink() or Path(git(worktree, 'rev-parse', '--show-toplevel')).resolve() != worktree.resolve():
        raise ValueError('worktree identity changed')
    if git(worktree, 'symbolic-ref', '--short', 'HEAD') != state['branch']:
        raise ValueError('worktree branch identity changed')
    git(worktree, 'merge-base', '--is-ancestor', state['base'], 'HEAD')


def guarded(state, action):
    """Remote-ref comparison happens even when the subprocess fails."""
    identity(state)
    before = refs(state['worktree'])
    try:
        result = action(push_env(state['worktree']))
    finally:
        after = refs(state['worktree'])
        if before != after:
            state['remote_movement'] = {'before': before, 'after': after}
            raise ValueError('remote-tracking refs moved')
        identity(state)
        config_changed(state)
    if stop_requested(state):
        raise InterruptedError('owner requested stop')
    return result


def config_changed(state):
    path = Path(state['worktree']) / 'easy-ref.toml'
    state['config_changed'] = (path.read_text() if path.exists() else None) != state['config_original']


def check(state, directory):
    state['phase'] = 'checking'
    state['checks'] = []
    save(state)
    for index, command in enumerate(state['config']['checks']):
        path = directory / f'check-{index + 1}.log'
        try:
            code = guarded(state, lambda env: run_check(state.get('check_sandbox', {'mode': 'none'}), command, state['worktree'], path,
                           state['config'].get('check_timeout', state['config']['timeout']), env, lambda: stop_requested(state)))
        except Exception as exc:
            state['checks'].append({'command': command, 'exit_code': None,
                                    'error': str(exc), 'output': path.read_text(errors='replace') if path.exists() else ''})
            (directory / 'checks.json').write_text(json.dumps(state['checks'], indent=2))
            save(state)
            raise
        state['checks'].append({'command': command, 'exit_code': code, 'output': path.read_text(errors='replace')})
        save(state)
    (directory / 'checks.json').write_text(json.dumps(state['checks'], indent=2))
    config_changed(state)
    state['phase'] = 'review'
    save(state)


def decide(state, verdict):
    if verdict['verdict'] == 'APPROVE' and any(c['exit_code'] != 0 for c in state['checks']):
        raise ValueError('approval conflicts with failing checks')
    return verdict['verdict']


def portable(text, state):
    # Fix orders are tracked: omit evidence and redact path-like/secret text.
    text = re.sub(r'(?<![\w./])(?:~[/\\][^\s]+|/[^\s]+|[A-Za-z]:[/\\][^\s]+)', '[path omitted]', text)
    text = re.sub(r'(?i)(token|password|secret|session[_ -]?id)\s*[:=]\s*\S+', '[sensitive value omitted]', text)
    return text


def fix_order(state, verdict):
    directory = Path(state['worktree']) / 'work-orders'
    if directory.is_symlink() or not directory.resolve().is_relative_to(Path(state['worktree']).resolve()):
        raise ValueError('work-orders must be a directory inside the worktree')
    if not directory.is_dir():
        return
    name = f"easy-ref-{state['run_id'][:8]}-{state['round']:03d}.md"
    path = directory / name
    if path.exists():
        raise ValueError('fix order already exists')
    body = 'Status: open\n\n# Required fixes\n\n'
    # Raw adapter output stays in private run storage. Only requirements are copied.
    body += '\n'.join(f"- {portable(r['id'], state)}: {portable(r['what'], state)}\n  Evidence: inspect the corresponding private round verdict." for r in verdict['required'])
    with path.open('x') as handle:
        handle.write(body + '\n')
    state['fix_order'] = 'work-orders/' + name


def prompt(state, role, directory):
    skills = skill_section(state, role)
    if skills:
        closing = (
            'Do not commit. Start your hand-back with a one-line commit subject, 72 characters or fewer.'
            if role == 'builder' else
            'Return only strict verdict JSON with verdict, summary, required (id, what, evidence), '
            "and owner_question only for NEEDS_OWNER, not the skill's report format.")
        skills += '\n' + closing + '\n'
    order = (Path(state['run_dir']) / 'order.md').read_text()
    common = (order + '\n\nNever push, open pull requests, merge, deploy, or delete branches.\n'
              + 'Ignored paths changed during prior reviews: ' + json.dumps(state.get('ignored_changes', [])) + '\n'
              + 'Unsandboxed adapters (Pi): ' + json.dumps(state.get('unsandboxed', [])) + '\n'
              + 'Owner decisions:\n' + '\n'.join(state['decisions']))
    if role == 'builder':
        return (common + '\nRequired fixes:\n' + state.get('feedback', '') +
                '\nDo not commit. easy-ref commits your changes. Start your hand-back with a one-line commit subject, 72 characters or fewer.\n' +
                ('Keep this fix order with your edits; easy-ref will commit it with the fix: ' + state['fix_order'] if state.get('fix_order') else '') + skills)
    head = git(state['worktree'], 'rev-parse', 'HEAD')
    full_diff = subprocess.check_output(
        ['git', '-C', state['worktree'], '-c', 'core.hooksPath=/dev/null',
         'diff', '--binary', state['base'], '--'], stderr=subprocess.PIPE)
    diff_path = (directory / 'full.diff').resolve()
    diff_path.write_bytes(full_diff)
    # Pi's read tool and Codex's read-only sandbox already allow this path.
    if len(full_diff) > 64000:
        diff = (git(state['worktree'], 'diff', '--stat', state['base'], '--')
                + f'\nRead the full diff at: {diff_path}')
    else:
        diff = full_diff.decode(errors='replace').strip()
    return (common + f"\nBase: {state['base']}\nHEAD: {head}\nDiff:\n{diff}\n"
            + '\nWorking-tree status:\n' + git(state['worktree'], 'status', '--porcelain=v1', '--untracked-files=all') + '\nInspect untracked files locally.\n' + '\nHand-back:\n' + state.get('handback', '') + '\nChecks:\n' + json.dumps(state['checks'])
            + f"\nCheck sandbox: {state.get('check_sandbox', {'mode': 'none'})['mode']}\n"
            + f"\nConfiguration changed: {state.get('config_changed', False)}\n"
            + state.get('warning', '') + '\nReview read-only. Return strict verdict JSON with verdict, summary, required'
            ' (id, what, evidence), and owner_question only for NEEDS_OWNER.\n' + skills)


def call(state, directory, role, adapter):
    message = prompt(state, role, directory)
    (directory / f'{role}-prompt.txt').write_text(message)
    state['phase'] = role + '-inflight'
    save(state)
    result = guarded(state, lambda env: adapter.invoke(
        role, message, Path(state['worktree']), directory, state['config'].get(role + '_timeout', state['config']['timeout']),
        env=env, stopped=lambda: stop_requested(state)))
    if type(result.exit_code) is not int or result.exit_code != 0:
        raise ValueError(f'{role} exited {result.exit_code}')
    if not isinstance(result.final_message, str) or not result.final_message.strip():
        raise ValueError(f'{role} returned no final message')
    path = Path(result.log_path).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise ValueError('adapter log missing or outside round directory')
    (directory / f'{role}-final.txt').write_text(result.final_message)
    return result.final_message


def commit_subject(state):
    first = state['handback'].partition('\n')[0].strip()
    if first and len(first) <= 72 and first.isprintable():
        return first
    return f"easy-ref: {state['branch'].removeprefix('ref/')} round {state['round']}"


def commit_builder_changes(state, directory, start_head):
    """Commit outside the harness, without running builder-controlled Git hooks."""
    worktree = state['worktree']
    git(worktree, 'merge-base', '--is-ancestor', start_head, 'HEAD')
    state['phase'] = 'committing'
    save(state)  # Interrupted staging/commit requires owner inspection, not replay.
    args = ['git', '-C', worktree, '-c', 'core.hooksPath=/dev/null']

    def command(arguments, name):
        return guarded(state, lambda env: execute(
            args + arguments, worktree, directory / name, 30, env,
            lambda: stop_requested(state)))

    if command(['add', '-A'], 'stage.log') != 0:
        raise ValueError('could not stage builder changes')
    difference = command(['diff', '--cached', '--no-ext-diff', '--quiet', '--exit-code'], 'staged-diff.log')
    if difference not in (0, 1):
        raise ValueError('could not verify staged builder changes')
    if difference == 1:
        subject = commit_subject(state)
        (directory / 'commit-subject.txt').write_text(subject + '\n')
        if command(['commit', '--no-verify', '-m', subject], 'commit.log') != 0:
            raise ValueError('could not commit builder changes')
    head = git(worktree, 'rev-parse', 'HEAD')
    git(worktree, 'merge-base', '--is-ancestor', start_head, head)
    if head == start_head:
        raise ValueError('builder produced no changes')
    dirty = git(worktree, 'status', '--porcelain=v1', '--untracked-files=all')
    if dirty:
        (directory / 'uncommitted.txt').write_text(dirty + '\n')
        raise ValueError('worktree is not clean after committing builder changes: ' + dirty)


def run(directory, builder, reviewer, notify=print, prepare=None):
    with locked(directory):
        state = load(directory)
        if state['status'] in ('DONE', 'STOPPED', 'NEEDS_OWNER'):
            return state
        try:
            if prepare is not None:
                prepare(state, builder, reviewer)
                save(state)
            if state['phase'] not in ('build', 'review'):
                raise ValueError('interrupted operation; owner must inspect before resuming')
            identity(state)
            while True:
                if stop_requested(state):
                    return finish(state, 'owner requested stop', 'STOPPED', notify=notify)
                if state['phase'] == 'build':
                    if state['round'] >= state['config']['round_limit']:
                        return finish(state, 'round limit reached', notify=notify)
                    state['round'] += 1
                rd = Path(directory) / 'rounds' / f"{state['round']:03d}"
                rd.mkdir(parents=True, exist_ok=True)
                attempt = 1
                while (rd / f'attempt-{attempt:03d}').exists():
                    attempt += 1
                rd = rd / f'attempt-{attempt:03d}'
                rd.mkdir()
                if state['phase'] == 'build':
                    before = git(state['worktree'], 'rev-parse', 'HEAD')
                    state['handback'] = call(state, rd, 'builder', builder)
                    (rd / 'hand-back.txt').write_text(state['handback'])
                    commit_builder_changes(state, rd, before)
                    check(state, rd)
                else:
                    # Answers to reviewer questions require fresh checks and identity validation.
                    if fingerprint(state['worktree']) != tuple(state['review_snapshot']):
                        raise ValueError('worktree changed while waiting for owner')
                    check(state, rd)
                if any(c['exit_code'] != 0 for c in state['checks']):
                    state['feedback'] = 'Independent checks failed:\n' + json.dumps(state['checks'])
                    state['phase'] = 'build'
                    save(state)
                    continue
                snapshot = fingerprint(state['worktree'])
                ignored_before = ignored_fingerprint(state['worktree'])
                try:
                    message = call(state, rd, 'reviewer', reviewer)
                finally:
                    ignored_after = ignored_fingerprint(state['worktree'])
                    changed = {name for name in ignored_before.keys() | ignored_after.keys()
                               if ignored_before.get(name) != ignored_after.get(name)}
                    state['ignored_changes'] = sorted(set(state.get('ignored_changes', [])) | changed)
                    save(state)
                if fingerprint(state['worktree']) != snapshot:
                    raise ValueError('reviewer changed worktree or HEAD')
                verdict = parse(message)
                (rd / 'verdict.json').write_text(json.dumps(verdict, indent=2))
                if stop_requested(state):
                    return finish(state, 'owner requested stop', 'STOPPED', notify=notify)
                decision = decide(state, verdict)
                if decision == 'APPROVE':
                    return finish(state, verdict['summary'], 'DONE', notify=notify)
                if decision == 'NEEDS_OWNER':
                    state['review_snapshot'] = snapshot
                    state['phase'] = 'review'
                    return finish(state, verdict['summary'], question=verdict['owner_question'], origin='reviewer', notify=notify)
                findings = [r['what'] for r in verdict['required']]
                repeated = bool(set(findings) & set(state['required']))
                state['required'] = findings
                state['feedback'] = json.dumps(verdict)
                fix_order(state, verdict)
                if repeated:
                    return finish(state, 'repeated required finding', notify=notify)
                state['phase'] = 'build'
                save(state)
        except InterruptedError:
            return finish(state, 'owner requested stop', 'STOPPED', notify=notify)
        except Exception as exc:
            return finish(state, f'{type(exc).__name__}: {exc}', notify=notify)


def answer(directory, decision):
    if not isinstance(decision, str) or not decision.strip():
        raise ValueError('owner decision must be nonempty')
    with locked(directory):
        state = load(directory)
        if state['status'] != 'NEEDS_OWNER':
            raise ValueError('run is not waiting for owner')
        if state['round'] >= state['config']['round_limit'] and state['question_origin'] != 'reviewer':
            raise ValueError('round limit exhausted; start a new run')
        state['decisions'].append(decision)
        with (Path(directory) / 'decisions.jsonl').open('a') as handle:
            handle.write(json.dumps({'decision': decision}) + '\n')
        state['phase'] = 'review' if state['question_origin'] == 'reviewer' else 'build'
        state['status'] = 'RUNNING'
        save(state)
        return state
