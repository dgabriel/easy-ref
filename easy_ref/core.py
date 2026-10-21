"""Persistent, isolated run primitives. No model integrations."""
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tomllib
import uuid


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True, stderr=subprocess.PIPE).strip()


def save(state):
    path = Path(state['run_dir']) / 'run.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(path)


def load(path):
    state = json.loads((Path(path) / 'run.json').read_text())
    if state.get('version') != 1 or state.get('status') not in ('RUNNING', 'NEEDS_OWNER', 'DONE', 'STOPPED'):
        raise ValueError('unsupported or malformed run state')
    return state


def push_env(repo):
    env = os.environ.copy()
    # Discard inherited numbered config before adding our own trusted policy.
    for key in list(env):
        if key == 'GIT_CONFIG_COUNT' or key.startswith(('GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_')):
            del env[key]
    remotes = git(repo, 'remote').splitlines()
    for i, remote in enumerate(remotes):
        # pushurl is multi-valued: reset inherited URLs before adding the blocker.
        env[f'GIT_CONFIG_KEY_{2 * i}'] = f'remote.{remote}.pushurl'
        env[f'GIT_CONFIG_VALUE_{2 * i}'] = ''
        env[f'GIT_CONFIG_KEY_{2 * i + 1}'] = f'remote.{remote}.pushurl'
        env[f'GIT_CONFIG_VALUE_{2 * i + 1}'] = 'invalid://easy-ref-disabled'
    env['GIT_CONFIG_COUNT'] = str(2 * len(remotes))
    return env


def refs(repo):
    return git(repo, 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/remotes')


def fingerprint(repo):
    names = subprocess.check_output(['git', '-C', str(repo), 'ls-files', '-z', '--cached', '--others', '--exclude-standard']).split(b'\0')
    digest = hashlib.sha256()
    for name in sorted(set(names) - {b''}):
        path = Path(repo) / os.fsdecode(name)
        digest.update(name + b'\0')
        if any(parent.is_symlink() for parent in path.parents if parent != Path(repo) and parent.is_relative_to(Path(repo))):
            digest.update(b'parent-symlink')
        elif path.is_symlink():
            digest.update(b'link:' + os.fsencode(os.readlink(path)))
        elif path.is_file():
            digest.update(str(path.stat().st_mode).encode() + path.read_bytes())
        else:
            digest.update(b'missing')
    return (git(repo, 'rev-parse', 'HEAD'), git(repo, 'status', '--porcelain=v1', '--untracked-files=all'),
            git(repo, 'diff', '--cached', '--binary'), digest.hexdigest())


def create(repo, order, overrides=None):
    gd = Path(git(repo, 'rev-parse', '--absolute-git-dir')).resolve()
    control = gd / 'easy-ref'
    control.mkdir(exist_ok=True)
    with (control / 'create.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('another run is being created') from None
        return _create(repo, order, overrides)


def _create(repo, order, overrides=None):
    repo = Path(git(repo, 'rev-parse', '--show-toplevel')).resolve()
    gd = Path(git(repo, 'rev-parse', '--absolute-git-dir')).resolve()
    config = {'builder': 'codex', 'reviewer': 'claude', 'checks': [], 'round_limit': 3,
              'timeout': 1800, 'notifier': 'terminal'}
    cp = repo / 'easy-ref.toml'
    config_text = cp.read_text() if cp.exists() else None
    if config_text is not None:
        config.update(tomllib.loads(config_text))
    config.update(overrides or {})
    if type(config['round_limit']) is not int or config['round_limit'] < 1:
        raise ValueError('round_limit must be positive')
    if type(config['timeout']) not in (int, float) or not math.isfinite(config['timeout']) or config['timeout'] <= 0:
        raise ValueError('timeout must be positive')
    if not isinstance(config['checks'], list) or any(not isinstance(c, list) or not c or any(not isinstance(a, str) for a in c) for c in config['checks']):
        raise ValueError('checks must be nonempty argument arrays')
    slug = Path(order).stem
    branch = 'ref/' + slug
    git(repo, 'check-ref-format', '--branch', branch)
    order_text = Path(order).read_text()
    existing = git(repo, 'for-each-ref', '--format=%(refname)', 'refs/heads/' + branch)
    if existing:
        raise ValueError('branch already exists')
    runs = gd / 'easy-ref' / 'runs'
    if runs.exists():
        for record in runs.glob('*/run.json'):
            if json.loads(record.read_text())['status'] not in ('DONE', 'STOPPED'):
                raise ValueError('repository already has an unfinished run')
    run_id = uuid.uuid4().hex
    root = Path(config.get('worktree_root', repo.parent / (repo.name + '.easy-ref'))).expanduser()
    root = (repo / root).resolve()
    worktree = root / run_id
    if '.git' in worktree.parts:
        raise ValueError('worktree must not be under a .git directory')
    for forbidden in (repo, gd):
        if worktree.is_relative_to(forbidden):
            raise ValueError('worktree must be outside repository and git directory')
    if worktree.exists():
        raise ValueError('worktree already exists')
    if worktree.is_relative_to((repo / git(repo, 'rev-parse', '--git-common-dir')).resolve()):
        raise ValueError('worktree must be outside common git directory')
    base = git(repo, 'rev-parse', 'HEAD')
    run_dir = runs / run_id
    run_dir.mkdir(parents=True)
    (run_dir / 'order.md').write_text(order_text)
    state = dict(version=1, run_id=run_id, repo=str(repo), run_dir=str(run_dir), worktree=str(worktree),
                 branch=branch, base=base, config=config, round=0, phase='create', status='RUNNING',
                 checks=[], required=[], decisions=[], reason='', question='', question_origin='',
                 config_original=config_text)
    save(state)
    try:
        git(repo, 'worktree', 'add', '-b', branch, str(worktree), base)
        state['phase'] = 'build'
        save(state)
    except Exception:
        state.update(status='NEEDS_OWNER', reason='worktree creation failed')
        save(state)
        raise
    return state


def ignored_fingerprint(repo):
    """Ignored files are reported separately, never counted as review mutations."""
    names = subprocess.check_output(['git', '-C', str(repo), 'ls-files', '-z',
                                     '--others', '--ignored', '--exclude-standard']).split(b'\0')
    result = {}
    for name in set(names) - {b''}:
        path = Path(repo) / os.fsdecode(name)
        if path.is_symlink():
            value = os.fsencode(os.readlink(path))
        elif path.is_file():
            value = path.read_bytes()
        else:
            value = b'missing'
        result[os.fsdecode(name)] = hashlib.sha256(value).hexdigest()
    return result
