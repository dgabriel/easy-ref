import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from unittest.mock import patch

from easy_ref.__main__ import main, locate
from easy_ref.core import load, save, git
from easy_ref.loop import locked, request_stop, status
from easy_ref.notify import notifier
from tests.test_core import RepoTest
from tests.test_loop import Fake, verdict
from tests.test_adapters import SCRIPT
from easy_ref.adapters.codex import Adapter as Codex
from easy_ref.adapters.claude import Adapter as Claude


class VerifiedFake(Fake):
    def verify(self):
        return 'fake 1.0'


class CliTests(RepoTest):
    def invoke(self, args, builder=None, reviewer=None):
        output = io.StringIO()
        error = io.StringIO()
        def factory(config, role):
            return builder if role == 'builder' else reviewer
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error), \
             patch('easy_ref.__main__.notifier', return_value=lambda _: None), \
             patch('easy_ref.__main__.build', side_effect=factory):
            code = main([*args, '--repo', str(self.repo)])
        return code, output.getvalue(), error.getvalue()

    def test_run_status_complete(self):
        code, out, err = self.invoke(['run', str(self.order), '--notifier', 'terminal'],
                                    VerifiedFake(['edit']), VerifiedFake([verdict()]))
        self.assertEqual(code, 0, err)
        run_id = out.splitlines()[0].removeprefix('Run: ')
        directory = locate(self.repo, run_id)
        self.assertEqual(load(directory)['adapter_versions']['builder'], 'fake 1.0')
        code, out, err = self.invoke(['status', run_id])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['status'], 'DONE')

    def test_cli_answer_resumes_reviewer(self):
        builder = VerifiedFake(['edit'])
        reviewer = VerifiedFake([verdict('NEEDS_OWNER'), verdict()])
        code, out, err = self.invoke(['run', str(self.order)], builder, reviewer)
        self.assertEqual(code, 2)
        run_id = out.splitlines()[0].removeprefix('Run: ')
        code, out, err = self.invoke(['answer', run_id, 'Choose A'], builder, reviewer)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(builder.prompts), 1)
        self.assertIn('Choose A', reviewer.prompts[-1])

    def test_stop_idle_waiting_run_unblocks_new_run(self):
        state = self.start()
        state['status'] = 'NEEDS_OWNER'
        save(state)
        code, out, err = self.invoke(['stop', state['run_id']])
        self.assertEqual(code, 0, err)
        self.assertEqual(load(state['run_dir'])['status'], 'STOPPED')
        other = self.root / 'another.md'
        other.write_text('Different order')
        from easy_ref.core import create
        self.assertEqual(create(self.repo, other)['status'], 'RUNNING')

    def test_stop_active_worker_only_requests_stop(self):
        state = self.start()
        with locked(state['run_dir']):
            result = request_stop(state['run_dir'], notify=lambda _: None)
            self.assertEqual(result['status'], 'RUNNING')
        self.assertTrue((Path(state['run_dir']) / 'stop-request').exists())

    def test_status_recovers_crashed_worker(self):
        state = self.start()
        state['phase'] = 'builder-inflight'
        save(state)
        code, out, err = self.invoke(['status', state['run_id']])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['status'], 'NEEDS_OWNER')
        self.assertIn('interrupted', json.loads(out)['reason'])

    def test_status_active_worker_does_not_mutate_it(self):
        state = self.start()
        with locked(state['run_dir']):
            self.assertEqual(status(state['run_dir'])['status'], 'RUNNING')
        self.assertEqual(load(state['run_dir'])['status'], 'RUNNING')

    def test_missing_or_traversal_id_refused(self):
        for run_id in ('../outside', 'f' * 32):
            code, out, err = self.invoke(['status', run_id])
            self.assertEqual(code, 2)
            self.assertIn('easy-ref:', err)

    def test_missing_adapter_fails_closed(self):
        class Missing(VerifiedFake):
            def verify(self):
                raise ValueError('unsupported CLI')
        code, out, err = self.invoke(['run', str(self.order)], Missing([]), Missing([]))
        self.assertEqual(code, 2)
        run_id = out.splitlines()[0].removeprefix('Run: ')
        self.assertEqual(load(locate(self.repo, run_id))['status'], 'NEEDS_OWNER')

    def test_cli_overrides_config_and_freezes_checks(self):
        (self.repo / 'easy-ref.toml').write_text('round_limit = 1\nnotifier = "terminal"\n')
        code, out, err = self.invoke(['run', str(self.order), '--round-limit', '2',
                                    '--check', f'{sys.executable} -c "print(42)"'],
                                    VerifiedFake(['edit']), VerifiedFake([verdict()]))
        self.assertEqual(code, 0, err)
        state = load(locate(self.repo, out.splitlines()[0].removeprefix('Run: ')))
        self.assertEqual(state['config']['round_limit'], 2)
        self.assertEqual(state['checks'][0]['output'].strip(), '42')

    def test_python_version_guard(self):
        with patch.object(sys, 'version_info', (3, 10, 0)), self.assertRaisesRegex(RuntimeError, 'Python 3.11'):
            runpy.run_path(str(Path(__file__).parents[1] / 'easy_ref/__init__.py'))

    def test_notifier_fallback_and_safe_arguments(self):
        message = 'A "quote" and newline\nrequest'
        with patch('easy_ref.notify.sys.platform', 'darwin'), \
             patch('easy_ref.notify.shutil.which', return_value='osascript'), \
             patch('easy_ref.notify.subprocess.run', side_effect=OSError('unavailable')) as process, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            notifier('auto')(message)
        self.assertIn(message, output.getvalue())
        args = process.call_args.args[0]
        self.assertEqual(args[-1], message)
        self.assertNotIn(message, args[2])

    def test_notifier_terminal_never_calls_os(self):
        with patch('easy_ref.notify.subprocess.run') as process, contextlib.redirect_stdout(io.StringIO()):
            notifier('terminal')('done')
        process.assert_not_called()

    def test_cli_full_process_with_fake_harnesses_only(self):
        binary = self.root / 'bin'
        binary.mkdir()
        for name in ('codex', 'claude'):
            path = binary / name
            path.write_text('#!' + sys.executable + '\n' + SCRIPT)
            path.chmod(0o700)
        env = os.environ.copy()
        env.update(PATH=str(binary) + os.pathsep + env['PATH'],
                   PYTHONPATH=str(Path(__file__).resolve().parents[1]), FAKE_EDIT='1',
                   FAKE_HELP=' '.join(Codex.flags + Claude.flags), FAKE_CAPTURE=str(self.root / 'capture.json'))
        result = subprocess.run([sys.executable, '-m', 'easy_ref', 'run', str(self.order),
                                 '--repo', str(self.repo), '--notifier', 'terminal'],
                                env=env, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        run_id = result.stdout.splitlines()[0].removeprefix('Run: ')
        state = load(locate(self.repo, run_id))
        self.assertEqual(state['status'], 'DONE')
        self.assertEqual(git(state['worktree'], 'show', 'HEAD:built-by-cli'), 'committed')
        query = subprocess.run([sys.executable, '-m', 'easy_ref', 'status', run_id, '--repo', str(self.repo)],
                               env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual(query.returncode, 0, query.stderr)
        self.assertEqual(json.loads(query.stdout)['status'], 'DONE')
