"""Resolve trusted owner configuration once; reject ambiguous or invalid inputs."""
import math
from pathlib import Path
import tomllib

from .adapters import REGISTRY

DEFAULTS = {'builder': 'codex', 'reviewer': 'claude', 'checks': [], 'round_limit': 3,
            'timeout': 1800, 'notifier': 'auto', 'allow_unsandboxed': False}
OPTIONAL = {'builder_model', 'reviewer_model', 'builder_timeout', 'reviewer_timeout',
            'check_timeout', 'worktree_root'}


def resolve(repo, overrides=None):
    path = Path(repo) / 'easy-ref.toml'
    text = path.read_text() if path.exists() else None
    config = {**DEFAULTS, **(tomllib.loads(text) if text is not None else {}), **(overrides or {})}
    unknown = set(config) - set(DEFAULTS) - OPTIONAL
    if unknown:
        raise ValueError(f'unknown configuration fields: {sorted(unknown)}')
    for role in ('builder', 'reviewer'):
        if not isinstance(config[role], str) or config[role] not in REGISTRY:
            raise ValueError(f'unknown {role} adapter')
    if type(config['round_limit']) is not int or config['round_limit'] < 1:
        raise ValueError('round_limit must be positive')
    for key in ('timeout', 'builder_timeout', 'reviewer_timeout', 'check_timeout'):
        if key in config and (type(config[key]) not in (int, float) or not math.isfinite(config[key]) or config[key] <= 0):
            raise ValueError(f'{key} must be positive and finite')
    checks = config['checks']
    if not isinstance(checks, list) or any(not isinstance(c, list) or not c or
            any(not isinstance(a, str) or not a or '\0' in a for a in c) for c in checks):
        raise ValueError('checks must be nonempty argument arrays')
    if config['notifier'] not in ('auto', 'macos', 'terminal'):
        raise ValueError('unknown notifier')
    if type(config['allow_unsandboxed']) is not bool:
        raise ValueError('allow_unsandboxed must be boolean')
    if 'pi' in (config['builder'], config['reviewer']) and not config['allow_unsandboxed']:
        raise ValueError('Pi has no sandbox: require --allow-unsandboxed')
    for key in ('builder_model', 'reviewer_model', 'worktree_root'):
        if key in config and (not isinstance(config[key], str) or not config[key].strip() or '\0' in config[key]):
            raise ValueError(f'{key} must be a nonempty string')
    return config, text
