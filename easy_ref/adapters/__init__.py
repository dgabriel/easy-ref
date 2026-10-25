"""One registry entry and one module per harness."""
from importlib import import_module

REGISTRY = {'codex': 'codex', 'claude': 'claude', 'pi': 'pi'}


def build(config, role):
    name = config[role]
    if name not in REGISTRY:
        raise ValueError(f'unknown adapter: {name}')
    adapter = import_module('.' + REGISTRY[name], __name__).Adapter(
        model=config.get(role + '_model'), allow_unsandboxed=config.get('allow_unsandboxed', False))
    return adapter
