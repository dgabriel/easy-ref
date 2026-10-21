import json
from pathlib import Path
import subprocess
import sys

from easy_ref.core import git, load, save
from easy_ref.loop import answer, decide, request_stop, run
from easy_ref.process import Result, execute
from easy_ref.verdict import parse
from tests.test_core import RepoTest


def verdict(kind='APPROVE', what='Fix the edge case'):
    value = {'verdict': kind, 'summary': 'Reviewed', 'required': []}
    if kind == 'CHANGES_REQUIRED':
        value['required'] = [{'id': 'R1', 'what': what, 'evidence': 'file.py:12'}]
    if kind == 'NEEDS_OWNER':
        value['owner_question'] = 'Which behavior?'
    return json.dumps(value)


class Fake:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.prompts = []
        self.environments = []

    def invoke(self, role, prompt, worktree, run_dir, timeout, *, env, stopped):
        self.prompts.append(prompt)
        self.environments.append(env)
        action = next(self.actions)
        if isinstance(action, Exception):
            raise action
        if callable(action):
            action = action(worktree, env)
        if role == 'builder' and action == 'commit':
            # Use actual subprocesses with the policy environment, no models.
            path = worktree / 'built'
            path.write_text(path.read_text() + 'x' if path.exists() else 'x')
            execute(['git', 'add', '.'], worktree, run_dir / 'add.log', timeout, env, stopped)
            execute(['git', 'commit', '-qm', 'fake build'], worktree, run_dir / 'commit.log', timeout, env, stopped)
            action = 'Committed the change'
        log = run_dir / f'{role}.log'
        log.write_text(str(action))
        if isinstance(action, Result):
            return action
        return Result(0, action, str(log))


class LoopTests(RepoTest):
    def go(self, builders=('commit',), reviews=None, **config):
        state = self.start(**config)
        self.builder = Fake(builders)
        self.reviewer = Fake(reviews if reviews is not None else [verdict()])
        self.directory = state['run_dir']
        return run(self.directory, self.builder, self.reviewer, notify=lambda _: None)

    def test_approve_round_one(self):
        state = self.go()
        self.assertEqual(state['status'], 'DONE')
        self.assertEqual(state['round'], 1)
        self.assertIn('nothing independent', self.reviewer.prompts[0])
        self.assertTrue((Path(self.directory) / 'summary.txt').exists())

    def test_changes_then_approve(self):
        (self.repo / 'work-orders').mkdir()
        (self.repo / 'work-orders' / 'seed.md').write_text('historical')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'order directory')
        state = self.go(['commit', 'commit'], [verdict('CHANGES_REQUIRED'), verdict()])
        self.assertEqual(state['status'], 'DONE')
        self.assertIn('Fix the edge case', self.builder.prompts[1])
        self.assertIn('Commit the fix order', self.builder.prompts[1])
        self.assertIn('easy-ref-', git(state['worktree'], 'ls-tree', '-r', '--name-only', 'HEAD'))

    def test_failing_checks_feed_builder_skip_review(self):
        command = [sys.executable, '-c', "from pathlib import Path; import sys; print('check failure'); sys.exit(len(Path('built').read_text()) < 2)"]
        state = self.go(['commit', 'commit'], checks=[command])
        self.assertEqual(state['status'], 'DONE')
        self.assertEqual(len(self.reviewer.prompts), 1)
        self.assertIn('check failure', self.builder.prompts[1])

    def test_malformed_verdict(self):
        state = self.go(reviews=['not JSON'])
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('missing JSON', state['reason'])

    def test_reviewer_modifies_dirty_file(self):
        def build(w, env):
            git(w, 'commit', '--allow-empty', '-qm', 'fake')
            return 'hand-back'
        def review(w, env):
            (w / 'seed').write_text('dirty after')
            return verdict()
        state = self.go([build], [review])
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('reviewer changed', state['reason'])

    def test_reviewer_changes_head(self):
        def review(w, env):
            git(w, 'commit', '--allow-empty', '-qm', 'reviewer changed HEAD')
            return verdict()
        self.assertIn('reviewer changed', self.go(reviews=[review])['reason'])

    def test_approval_with_failed_checks_rejected(self):
        with self.assertRaisesRegex(ValueError, 'failing checks'):
            decide({'checks': [{'exit_code': 1}]}, parse(verdict()))

    def test_no_new_commit(self):
        state = self.go(['No changes'])
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('no new commit', state['reason'])

    def test_repeated_finding(self):
        state = self.go(['commit', 'commit'], [verdict('CHANGES_REQUIRED')] * 2)
        self.assertIn('repeated', state['reason'])
        self.assertEqual(state['round'], 2)

    def test_round_limit(self):
        state = self.go(['commit'], [verdict('CHANGES_REQUIRED')], round_limit=1)
        self.assertIn('round limit', state['reason'])
        self.assertEqual(state['round'], 1)

    def test_adapter_timeout(self):
        state = self.go([TimeoutError('fake timeout')])
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('TimeoutError', state['reason'])

    def test_adapter_crash(self):
        self.assertEqual(self.go([RuntimeError('crash')])['status'], 'NEEDS_OWNER')

    def test_adapter_nonzero(self):
        def fail(w, env):
            return Result(2, 'failed', str(w / 'not-used'))
        self.assertIn('exited 2', self.go([fail])['reason'])

    def test_answer_reviewer_resumes_review(self):
        state = self.go(reviews=[verdict('NEEDS_OWNER'), verdict()])
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        answer(self.directory, 'Use behavior A')
        state = run(self.directory, self.builder, self.reviewer, notify=lambda _: None)
        self.assertEqual(state['status'], 'DONE')
        self.assertEqual(len(self.builder.prompts), 1)
        self.assertIn('Use behavior A', self.reviewer.prompts[1])

    def test_answer_builder_resumes_build(self):
        state = self.go([TimeoutError('timeout'), 'commit'])
        answer(self.directory, 'Retry building')
        state = run(self.directory, self.builder, self.reviewer, notify=lambda _: None)
        self.assertEqual(state['status'], 'DONE')
        self.assertIn('Retry building', self.builder.prompts[1])

    def test_completed_and_stopped_cannot_resume(self):
        self.go()
        with self.assertRaises(ValueError):
            answer(self.directory, 'again')
        state = load(self.directory)
        state['status'] = 'STOPPED'
        save(state)
        with self.assertRaises(ValueError):
            answer(self.directory, 'again')

    def test_remote_tracking_movement(self):
        def move(w, env):
            git(w, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
            return 'commit'
        state = self.go([move])
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('remote-tracking refs moved', state['reason'])
        self.assertIn('refs/remotes/origin/main', state['remote_movement']['after'])

    def test_check_remote_movement(self):
        state = self.go(checks=[['git', 'update-ref', 'refs/remotes/origin/main', 'HEAD']])
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('remote-tracking refs moved', state['reason'])
        self.assertEqual(len(self.reviewer.prompts), 0)

    def test_frozen_checks_and_agent_check_environments(self):
        git(self.repo, 'remote', 'add', 'origin', 'https://example.invalid/repo')
        code = "import os; print(os.environ['GIT_CONFIG_KEY_0']); print(os.environ['GIT_CONFIG_VALUE_1'])"
        (self.repo / 'easy-ref.toml').write_text('checks = ' + json.dumps([[sys.executable, '-c', code]]))
        def build(w, env):
            (w / 'easy-ref.toml').write_text('checks = []')
            return 'commit'
        state = self.go([build])
        self.assertEqual(state['status'], 'DONE')
        self.assertTrue(state['config_changed'])
        self.assertEqual(len(state['checks']), 1)
        self.assertIn('invalid://easy-ref-disabled', state['checks'][0]['output'])
        self.assertIn('remote.origin.pushurl', state['checks'][0]['output'])
        for fake in (self.builder, self.reviewer):
            self.assertEqual(fake.environments[0]['GIT_CONFIG_VALUE_1'], 'invalid://easy-ref-disabled')
        self.assertIn('Configuration changed: True', self.reviewer.prompts[0])

    def test_restart_inflight_needs_owner(self):
        state = self.start()
        state['phase'] = 'builder-inflight'
        save(state)
        state = run(state['run_dir'], Fake([]), Fake([]), notify=lambda _: None)
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('interrupted operation', state['reason'])

    def test_stop_request(self):
        state = self.start()
        request_stop(state['run_dir'])
        state = run(state['run_dir'], Fake([]), Fake([]), notify=lambda _: None)
        self.assertEqual(state['status'], 'STOPPED')

    def test_real_process_timeout_and_stop(self):
        for stop, error in ((lambda: False, TimeoutError), (lambda: True, InterruptedError)):
            with self.assertRaises(error):
                execute([sys.executable, '-c', 'import time; time.sleep(5)'], self.repo,
                        self.root / 'process.log', .05, {}, stop)

    def test_review_answer_refuses_changed_tree(self):
        state = self.go(reviews=[verdict('NEEDS_OWNER')])
        (Path(state['worktree']) / 'seed').write_text('changed by owner')
        answer(self.directory, 'continue')
        state = run(self.directory, self.builder, self.reviewer, notify=lambda _: None)
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('changed while waiting', state['reason'])

    def test_strict_parser(self):
        invalid = ['[]', '{}', verdict().replace('"summary": "Reviewed"', '"summary": "Reviewed", "summary": "again"'),
                   verdict().replace('"required": []', '"required": false'),
                   verdict().replace('"required": []', '"required": [], "extra": 1'),
                   verdict('CHANGES_REQUIRED').replace('"what": "Fix the edge case"', '"what": ""'),
                   verdict('NEEDS_OWNER').replace('"Which behavior?"', 'false'),
                   '```json\n' + verdict() + '\n```\n```json\n' + verdict('NEEDS_OWNER') + '\n```']
        for message in invalid:
            with self.subTest(message=message), self.assertRaises(ValueError):
                parse(message)
        self.assertEqual(parse('Review:\n```json\n' + verdict() + '\n```')['verdict'], 'APPROVE')

    def test_reviewer_edits_ignored_untracked_file(self):
        def build(w, env):
            (w / '.gitignore').write_text('ignored\n')
            (w / 'ignored').write_text('before')
            return 'commit'
        def review(w, env):
            (w / 'ignored').write_text('after')
            return verdict()
        state = self.go([build], [review])
        self.assertEqual(state['status'], 'DONE')
        self.assertIn('ignored', state['ignored_changes'])

    def test_review_resume_preserves_previous_artifacts(self):
        self.go(reviews=[verdict('NEEDS_OWNER'), verdict()])
        first = Path(self.directory) / 'rounds/001/attempt-001/reviewer-final.txt'
        before = first.read_text()
        answer(self.directory, 'Choose A')
        state = run(self.directory, self.builder, self.reviewer, notify=lambda _: None)
        self.assertEqual(state['status'], 'DONE')
        self.assertEqual(first.read_text(), before)
        self.assertTrue((first.parent.parent / 'attempt-002/reviewer-final.txt').exists())

    def test_symlink_fix_directory_refused(self):
        outside = self.root / 'outside'
        outside.mkdir()
        def build(w, env):
            (w / 'work-orders').symlink_to(outside, target_is_directory=True)
            return 'commit'
        state = self.go([build], [verdict('CHANGES_REQUIRED')])
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertEqual(list(outside.iterdir()), [])

    def test_stop_during_agent(self):
        def stop(w, env):
            request_stop(self.directory)
            return 'commit'
        state = self.go([stop])
        self.assertEqual(state['status'], 'STOPPED')
        self.assertEqual(len(self.reviewer.prompts), 0)

    def test_large_diff_is_capped(self):
        def build(w, env):
            (w / 'large').write_text('large payload\n' * 10000)
            return 'commit'
        state = self.go([build])
        self.assertEqual(state['status'], 'DONE')
        self.assertIn('Inspect the full diff locally', self.reviewer.prompts[0])
        self.assertLess(len(self.reviewer.prompts[0]), 5000)

    def test_check_timeout(self):
        state = self.go(checks=[[sys.executable, '-c', 'import time; time.sleep(5)']], timeout=.05)
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('timed out', state['reason'])

    def test_failing_checks_exhaust_rounds(self):
        state = self.go(['commit'], checks=[[sys.executable, '-c', 'raise SystemExit(1)']], round_limit=1)
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertEqual(state['round'], 1)
        self.assertEqual(len(self.reviewer.prompts), 0)
        self.assertEqual(state['checks'][0]['exit_code'], 1)

    def test_empty_and_exhausted_answers_refused(self):
        self.go(['No changes'], round_limit=1)
        for decision in ('', 'retry'):
            with self.assertRaises(ValueError):
                answer(self.directory, decision)

    def test_run_lock_refuses_concurrent_mutation(self):
        from easy_ref.loop import locked
        state = self.start()
        with locked(state['run_dir']):
            with self.assertRaisesRegex(ValueError, 'already active'):
                run(state['run_dir'], Fake([]), Fake([]))

    def test_agent_switching_branch_stops(self):
        def build(w, env):
            git(w, 'checkout', '-qb', 'unexpected')
            return 'commit'
        state = self.go([build])
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('branch identity changed', state['reason'])

    def test_ref_change_even_on_adapter_crash(self):
        def crash(w, env):
            git(w, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
            raise RuntimeError('crashed')
        state = self.go([crash])
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('remote-tracking refs moved', state['reason'])

    def test_reviewer_nonzero_cannot_approve(self):
        def fail(w, env):
            return Result(1, verdict(), str(w / 'not-used'))
        state = self.go(reviews=[fail])
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('reviewer exited 1', state['reason'])

    def test_config_change_reported_on_no_commit_stop(self):
        def build(w, env):
            (w / 'easy-ref.toml').write_text('checks = []')
            return 'No commit'
        state = self.go([build])
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertTrue(state['config_changed'])
        self.assertIn('Configuration changed: True', (Path(self.directory) / 'summary.txt').read_text())


    def test_uncommitted_builder_work_retries_before_checks(self):
        def dirty(w, env):
            git(w, 'commit', '--allow-empty', '-qm', 'partial work')
            (w / 'needed').write_text('not yet committed')
            return 'done'
        state = self.go([dirty, 'commit'], checks=[[sys.executable, '-c',
                         "from pathlib import Path; assert Path('needed').is_file()"]])
        self.assertEqual(state['status'], 'DONE')
        self.assertEqual(state['round'], 2)
        self.assertIn('needed', self.builder.prompts[1])
        self.assertEqual(len(self.reviewer.prompts), 1)
        self.assertEqual(git(state['worktree'], 'show', 'HEAD:needed'), 'not yet committed')
        self.assertFalse((Path(self.directory) / 'rounds/001/attempt-001/checks.json').exists())

    def test_uncommitted_builder_work_exhausts_limit_without_approval(self):
        def dirty(w, env):
            git(w, 'commit', '--allow-empty', '-qm', 'partial work')
            (w / 'needed').write_text('uncommitted')
            return 'done'
        state = self.go([dirty], round_limit=1)
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertEqual(len(self.reviewer.prompts), 0)

    def test_reviewer_python_cache_is_reported_and_allows_review(self):
        (self.repo / '.gitignore').write_text('__pycache__/\n')
        (self.repo / 'module.py').write_text('value = 1\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'module')
        def review(w, env):
            subprocess.run([sys.executable, '-c', 'import module'], cwd=w, env=env, check=True)
            return verdict('CHANGES_REQUIRED')
        state = self.go(['commit', 'commit'], [review, verdict()])
        self.assertEqual(state['status'], 'DONE')
        self.assertTrue(any('__pycache__' in name for name in state['ignored_changes']))
        self.assertIn('__pycache__', self.builder.prompts[1])
        self.assertIn('__pycache__', (Path(self.directory) / 'summary.txt').read_text())

    def test_reviewer_nonignored_untracked_edit_stops(self):
        def review(w, env):
            (w / 'unexpected').write_text('new')
            return verdict()
        state = self.go(reviews=[review])
        self.assertEqual(state['status'], 'NEEDS_OWNER')
        self.assertIn('reviewer changed', state['reason'])

    def test_process_stdin_is_closed_by_default(self):
        path = self.root / 'stdin.log'
        code = execute([sys.executable, '-c', "import sys; print(repr(sys.stdin.read()))"],
                       self.repo, path, 2, {})
        self.assertEqual(code, 0)
        self.assertEqual(path.read_text().strip(), "''")

    def test_process_stdin_explicit_opt_in(self):
        path = self.root / 'stdin.log'
        source = self.root / 'input.txt'
        source.write_text('prompt')
        with source.open('rb') as handle:
            code = execute([sys.executable, '-c', 'import sys; print(sys.stdin.read())'],
                           self.repo, path, 2, {}, stdin=handle)
        self.assertEqual(code, 0)
        self.assertEqual(path.read_text().strip(), 'prompt')

    def test_fix_order_keeps_relative_paths_redacts_absolute_and_home(self):
        from easy_ref.loop import portable
        message = 'Fix src/app/range.py and ./src/app.py; omit /home/example/secret and ~/private and C:\\Users\\example\\secret'
        result = portable(message, {})
        self.assertIn('src/app/range.py', result)
        self.assertIn('./src/app.py', result)
        self.assertNotIn('/home/example', result)
        self.assertNotIn('~/private', result)
        self.assertNotIn('C:\\Users', result)
