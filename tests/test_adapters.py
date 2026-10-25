"""Fake CLI processes only. Never invoke installed model CLIs in tests."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from easy_ref.adapters import build
from easy_ref.adapters.common import probe
from easy_ref.core import push_env, git
from easy_ref.verdict import parse
from tests.test_core import RepoTest


SCRIPT = r'''
import json, os, pathlib, sys, subprocess
args = sys.argv[1:]
if '--version' in args:
    print('fake-cli 1.0')
    sys.exit(0)
if '--help' in args:
    print(os.environ.get('FAKE_HELP', ''))
    sys.exit(0)
kind = pathlib.Path(sys.argv[0]).name
capture = pathlib.Path(os.environ['FAKE_CAPTURE'])
stdin = sys.stdin.read()
capture.write_text(json.dumps({'args': args, 'cwd': os.getcwd(), 'stdin': stdin,
                              'git_count': os.environ.get('GIT_CONFIG_COUNT'),
                              'git_block': os.environ.get('GIT_CONFIG_VALUE_1')}))
value = {'verdict': 'APPROVE', 'summary': 'Reviewed', 'required': [], 'owner_question': None}
if kind == 'codex':
    if os.environ.get('FAKE_EDIT') and args[args.index('--sandbox') + 1] == 'workspace-write':
        pathlib.Path('built-by-cli').write_text('committed')
    result = args[args.index('--output-last-message') + 1]
    pathlib.Path(result).write_text(json.dumps(value) if '--output-schema' in args else 'Built')
    print('fake progress')
elif kind == 'claude':
    value = {'type': 'result', 'subtype': 'success', 'is_error': False,
             'permission_denials': [], 'result': 'Built', 'structured_output': value}
    value.update(json.loads(os.environ.get('FAKE_ENVELOPE', '{}')))
    print(json.dumps(value))
    print('diagnostic on stderr', file=sys.stderr)
else:
    source = pathlib.Path(args[-1][1:])
    assert source.read_text()
    print('```json\n' + json.dumps({k:v for k,v in value.items() if k != 'owner_question'}) + '\n```')
sys.exit(int(os.environ.get('FAKE_EXIT', '0')))
'''


class AdapterTests(RepoTest):
    def setUp(self):
        super().setUp()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.logs = self.root / 'logs'
        self.logs.mkdir()
        self.capture = self.root / 'capture.json'
        git(self.repo, 'remote', 'add', 'origin', 'https://example.invalid/repo')
        for name in ('codex', 'claude', 'pi'):
            path = self.bin / name
            path.write_text('#!' + sys.executable + '\n' + SCRIPT)
            path.chmod(0o700)

    def adapter(self, name, **config):
        adapter = build({'builder': name, 'allow_unsandboxed': True, **config}, 'builder')
        adapter.executable = str(self.bin / name)
        return adapter

    def invoke(self, adapter, role='reviewer', **extra):
        env = push_env(self.repo)
        env.update(FAKE_CAPTURE=str(self.capture), **extra)
        result = adapter.invoke(role, 'work order prompt', self.repo, self.logs, 3, env=env, stopped=lambda: False)
        return result, json.loads(self.capture.read_text())

    def test_codex_schema_stdin_and_role_sandbox(self):
        adapter = self.adapter('codex', builder_model='chosen-model')
        for role, sandbox in (('builder', 'workspace-write'), ('reviewer', 'read-only')):
            result, call = self.invoke(adapter, role)
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(call['args'][call['args'].index('--sandbox') + 1], sandbox)
            self.assertEqual(call['stdin'], 'work order prompt')
            self.assertEqual(call['git_block'], 'invalid://easy-ref-disabled')
            self.assertEqual(call['cwd'], str(self.repo.resolve()))
            self.assertIn('shell_environment_policy.set=', ' '.join(call['args']))
            self.assertIn('GIT_CONFIG_KEY_0', ' '.join(call['args']))
            self.assertIn('chosen-model', call['args'])
            if role == 'reviewer':
                self.assertEqual(parse(result.final_message)['verdict'], 'APPROVE')
                self.assertNotIn('owner_question', parse(result.final_message))

    def test_claude_readonly_allowlist_and_structured_stdout(self):
        result, call = self.invoke(self.adapter('claude'))
        self.assertEqual(parse(result.final_message)['verdict'], 'APPROVE')
        self.assertEqual(call['args'][call['args'].index('--tools') + 1], 'Read,Grep,Glob')
        self.assertIn('Edit,Write,NotebookEdit,Bash,Agent,Task', call['args'])
        self.assertIn('manual', call['args'])
        self.assertEqual(call['stdin'], 'work order prompt')
        self.assertIn('diagnostic on stderr', Path(result.log_path).read_text())

    def test_claude_builder_sandbox_no_permission_bypass(self):
        result, call = self.invoke(self.adapter('claude'), 'builder')
        self.assertEqual(result.final_message, 'Built')
        settings = json.loads(call['args'][call['args'].index('--settings') + 1])
        self.assertTrue(settings['sandbox']['enabled'])
        self.assertTrue(settings['sandbox']['failIfUnavailable'])
        self.assertFalse(settings['sandbox']['allowUnsandboxedCommands'])
        self.assertNotIn('network', settings['sandbox'])
        self.assertIn('acceptEdits', call['args'])

    def test_claude_error_or_denial_cannot_approve(self):
        for envelope in ({'is_error': True}, {'subtype': 'error'}, {'permission_denials': [{'tool_name': 'Write'}]}, {'structured_output': None}):
            with self.subTest(envelope=envelope), self.assertRaises(ValueError):
                self.invoke(self.adapter('claude'), FAKE_ENVELOPE=json.dumps(envelope))

    def test_pi_opt_in_and_readonly_tools(self):
        with self.assertRaisesRegex(ValueError, 'no sandbox'):
            build({'builder': 'pi'}, 'builder')
        result, call = self.invoke(self.adapter('pi'))
        self.assertEqual(parse(result.final_message)['verdict'], 'APPROVE')
        self.assertEqual(call['args'][call['args'].index('--tools') + 1], 'read,grep,find,ls')
        self.assertIn('--no-extensions', call['args'])
        self.assertEqual(call['stdin'], '')
        self.assertEqual(call['git_block'], 'invalid://easy-ref-disabled')

    def test_nonzero_exit_is_not_a_verdict(self):
        for name in ('codex', 'claude', 'pi'):
            result, _ = self.invoke(self.adapter(name), FAKE_EXIT='4')
            self.assertEqual(result.exit_code, 4)
            self.assertEqual(result.final_message, '')

    def test_capability_probe_fail_closed(self):
        adapter = self.adapter('codex')
        with patch.dict(os.environ, {'FAKE_HELP': ' '.join(adapter.flags)}):
            self.assertEqual(adapter.verify(), 'fake-cli 1.0')
        with patch.dict(os.environ, {'FAKE_HELP': '--model'}):
            with self.assertRaisesRegex(ValueError, 'unsupported'):
                adapter.verify()

    def test_unknown_adapter_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unknown adapter'):
            build({'builder': 'unknown'}, 'builder')


    def test_claude_empty_mcp_config_includes_server_map(self):
        for role in ('builder', 'reviewer'):
            with self.subTest(role=role):
                result, call = self.invoke(self.adapter('claude'), role)
                self.assertEqual(result.exit_code, 0)
                value = call['args'][call['args'].index('--mcp-config') + 1]
                self.assertEqual(value, json.dumps({'mcpServers': {}}))
