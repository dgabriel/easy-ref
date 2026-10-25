import contextlib
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from easy_ref.__main__ import display, parser
from easy_ref.core import git, load
from easy_ref.loop import answer, run
from tests.test_core import RepoTest
from tests.test_loop import Fake, verdict


class SandboxTests(RepoTest):
    def setUp(self):
        super().setUp()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.codex = self.bin / 'codex'
        self.capture = self.root / 'argv.json'
        self.codex.write_text('#!' + sys.executable + '\n' + '''
import json, os, subprocess, sys, tomllib
from pathlib import Path
if sys.argv[1:] == ['sandbox', '--help']:
    print('Usage: codex sandbox [OPTIONS] [COMMAND]...')
    print('-P, --permission-profile -c, --config -C, --cd')
    sys.exit(0)
Path(os.environ['CAPTURE']).write_text(json.dumps(sys.argv[1:]))
if os.environ.get('FAIL_SANDBOX'):
    sys.exit(71)
env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_CONFIG_')}
setting = sys.argv[sys.argv.index('-c') + 1]
env.update(tomllib.loads(setting)['shell_environment_policy']['set'])
result = subprocess.run(sys.argv[sys.argv.index('--') + 1:], env=env)
sys.exit(result.returncode)
''')
        self.codex.chmod(0o755)
        for context in (patch('easy_ref.check_sandbox.platform.system', return_value='Darwin'),
                        patch.dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                                   CAPTURE=str(self.capture))):
            context.start()
            self.addCleanup(context.stop)

    def go(self, state, builders=None, reviews=None):
        self.builder = Fake(builders or ['edit'])
        self.reviewer = Fake(reviews or [verdict()])
        return run(state['run_dir'], self.builder, self.reviewer, notify=lambda _: None)

    def test_wrapped_argv_environment_and_reporting(self):
        git(self.repo, 'remote', 'add', 'origin', 'https://example.invalid/repo')
        command = [sys.executable, '-I', '-c',
                   "import os,sys; assert os.environ['GIT_CONFIG_COUNT']=='2'; "
                   "assert os.environ['GIT_CONFIG_KEY_1']=='remote.origin.pushurl'; "
                   "assert os.environ['GIT_CONFIG_VALUE_1']=='invalid://easy-ref-disabled'; "
                   "assert os.environ['GIT_CONFIG_VALUE_0']==''; assert sys.stdin.read()==''"]
        state = self.go(self.start(check_sandbox='codex', checks=[command]))
        self.assertEqual(state['status'], 'DONE', state['reason'])
        argv = json.loads(self.capture.read_text())
        self.assertEqual(argv[:3], ['sandbox', '-P', ':workspace'])
        self.assertEqual(argv[3], '-c')
        self.assertEqual(argv[5:8], ['-C', state['worktree'], '--'])
        self.assertEqual(argv[-len(command):], command)
        self.assertIn('Check sandbox: codex', self.reviewer.prompts[0])
        self.assertIn('Check sandbox: codex', (Path(state['run_dir']) / 'summary.txt').read_text())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            display(state)
        self.assertEqual(json.loads(output.getvalue())['check_sandbox']['mode'], 'codex')

    def test_auto_uses_codex(self):
        state = self.go(self.start(checks=[[sys.executable, '-c', 'pass']]))
        self.assertEqual(state['status'], 'DONE')
        self.assertEqual(state['check_sandbox']['mode'], 'codex')
        self.assertTrue(self.capture.exists())

    def test_none_runs_directly(self):
        state = self.go(self.start(check_sandbox='none', checks=[[sys.executable, '-c', 'pass']]))
        self.assertEqual(state['status'], 'DONE')
        self.assertIn('unsandboxed', state['warning'])
        self.assertFalse(self.capture.exists())

    def test_missing_auto_falls_back(self):
        with patch('easy_ref.check_sandbox.shutil.which', return_value=None):
            state = self.start(checks=[[sys.executable, '-c', 'pass']])
        state = self.go(state)
        self.assertEqual(state['status'], 'DONE')
        self.assertEqual(state['check_sandbox']['mode'], 'none')
        self.assertIn('codex is missing', state['warning'])
        self.assertFalse(self.capture.exists())

    def test_required_missing_refuses_creation(self):
        with patch('easy_ref.check_sandbox.shutil.which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'codex is missing'):
                self.start(check_sandbox='codex')
        self.assertFalse((self.repo / '.git/easy-ref/runs').exists())
        self.assertEqual(git(self.repo, 'branch', '--list', 'ref/*'), '')

    def test_incompatible_help(self):
        self.codex.write_text('#!' + sys.executable + '\nprint("old help")\n')
        with self.assertRaisesRegex(ValueError, 'required options'):
            self.start(check_sandbox='codex')
        self.assertIn('required options', self.start()['warning'])

    def test_frozen_on_review_resume(self):
        state = self.go(self.start(checks=[[sys.executable, '-c', 'pass']]),
                        reviews=[verdict('NEEDS_OWNER')])
        (self.repo / 'easy-ref.toml').write_text('check_sandbox="none"')
        answer(state['run_dir'], 'Continue')
        with patch('easy_ref.check_sandbox.resolve', side_effect=AssertionError('re-resolved')):
            state = self.go(load(state['run_dir']))
        self.assertEqual(state['status'], 'DONE', state['reason'])
        self.assertEqual(state['check_sandbox']['mode'], 'codex')
        self.assertEqual(state['config']['check_sandbox'], 'auto')

    def test_start_failure_needs_owner(self):
        state = self.start(checks=[[sys.executable, '-c', 'pass']])
        with patch.dict(os.environ, FAIL_SANDBOX='1'):
            state = self.go(state)
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('sandbox failed', state['reason'])
        self.assertEqual(state['checks'][0]['exit_code'], None)
        self.assertEqual(len(self.builder.prompts), 1)
        self.assertEqual(self.reviewer.prompts, [])

    def test_ordinary_nonzero_feeds_builder(self):
        command = [sys.executable, '-c', "from pathlib import Path; import sys; sys.exit(len(Path('built').read_text()) < 2)"]
        state = self.go(self.start(checks=[command]), builders=['edit', 'edit'])
        self.assertEqual(state['status'], 'DONE', state['reason'])
        self.assertIn('Independent checks failed', self.builder.prompts[1])

    def test_frozen_fallback_does_not_upgrade(self):
        with patch('easy_ref.check_sandbox.shutil.which', return_value=None):
            state = self.start(checks=[[sys.executable, '-c', 'pass']])
        state = self.go(state, reviews=[verdict('NEEDS_OWNER')])
        answer(state['run_dir'], 'Continue')
        state = self.go(load(state['run_dir']))
        self.assertEqual(state['status'], 'DONE')
        self.assertEqual(state['check_sandbox']['mode'], 'none')
        self.assertFalse(self.capture.exists())

    def test_missing_frozen_executable_stops(self):
        state = self.start(checks=[[sys.executable, '-c', 'pass']])
        self.codex.unlink()
        state = self.go(state)
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIsNone(state['checks'][0]['exit_code'])

    def test_wrapped_timeout_stops(self):
        state = self.go(self.start(check_timeout=0.2,
                                  checks=[[sys.executable, '-c', 'import time; time.sleep(30)']]))
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('timed out', state['reason'])
        self.assertIsNone(state['checks'][0]['exit_code'])

    def test_unsupported_platform(self):
        with patch('easy_ref.check_sandbox.platform.system', return_value='Linux'):
            with self.assertRaisesRegex(ValueError, 'requires macOS'):
                self.start(check_sandbox='codex')
            self.assertIn('requires macOS', self.start()['warning'])

    def test_cli_and_invalid_config(self):
        self.assertEqual(parser().parse_args(['run', 'order', '--check-sandbox', 'none']).check_sandbox, 'none')
        with self.assertRaisesRegex(ValueError, 'check_sandbox'):
            self.start(check_sandbox='workspace-write')
