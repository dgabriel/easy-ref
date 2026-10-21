"""Shared harness mechanics. Probes call help/version only, never models."""
import json
from pathlib import Path
import subprocess

from ..verdict import unique


FINDING = {'type': 'object', 'properties': {key: {'type': 'string'} for key in ('id', 'what', 'evidence')},
           'required': ['id', 'what', 'evidence'], 'additionalProperties': False}
# All properties are required for providers' strict structured output. Convert
# owner_question=null to absence at the adapter boundary before strict parsing.
SCHEMA = {'type': 'object', 'properties': {
    'verdict': {'type': 'string', 'enum': ['APPROVE', 'CHANGES_REQUIRED', 'NEEDS_OWNER']},
    'summary': {'type': 'string'}, 'required': {'type': 'array', 'items': FINDING},
    'owner_question': {'type': ['string', 'null']}},
    'required': ['verdict', 'summary', 'required', 'owner_question'], 'additionalProperties': False}


def structured(value):
    if not isinstance(value, dict):
        raise ValueError('structured verdict is not an object')
    if value.get('owner_question', object()) is None and value.get('verdict') != 'NEEDS_OWNER':
        value = {k: v for k, v in value.items() if k != 'owner_question'}
    return json.dumps(value)


def decode(text):
    return json.loads(text, object_pairs_hook=unique)


def probe(executable, help_args, required):
    def read(args):
        result = subprocess.run([executable, *args], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise ValueError(f'{executable}: capability probe failed')
        return result.stdout
    version = read(['--version']).strip()
    help_text = read(help_args)
    missing = [flag for flag in required if flag not in help_text]
    if missing:
        raise ValueError(f'{executable}: unsupported CLI options: {missing}')
    return version


class Harness:
    executable = ''
    help_args = ['--help']
    flags = ()

    def __init__(self, model=None, allow_unsandboxed=False):
        self.model = model
        self.allow_unsandboxed = allow_unsandboxed

    def verify(self):
        return probe(self.executable, self.help_args, self.flags)

    def model_args(self):
        return ['--model', self.model] if self.model else []

    def validate_role(self, role):
        if role not in ('builder', 'reviewer'):
            raise ValueError('unknown agent role')
