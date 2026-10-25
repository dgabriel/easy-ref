import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from easy_ref.core import create, git, load, push_env


class RepoTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        git(self.repo, 'config', 'user.name', 'Test')
        (self.repo / 'seed').write_text('seed')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'initial')
        self.order = self.root / 'order.md'
        self.order.write_text('Build a thing')

    def start(self, **config):
        return create(self.repo, self.order, config)


class CoreTests(RepoTest):
    def test_isolation_and_state(self):
        state = self.start()
        path = Path(state['worktree'])
        self.assertEqual(path.parent, (self.root / 'repo.easy-ref').resolve())
        self.assertFalse(path.is_relative_to(self.repo))
        self.assertEqual(load(state['run_dir']), state)

    def test_existing_branch(self):
        git(self.repo, 'branch', 'ref/order')
        with self.assertRaises(ValueError):
            self.start()

    def test_invalid_worktree(self):
        for root in (self.repo / 'nested', self.repo / '.git' / 'nested'):
            with self.assertRaises(ValueError):
                self.start(worktree_root=str(root))

    def test_frozen_config(self):
        (self.repo / 'easy-ref.toml').write_text('checks = [["original"]]')
        state = self.start()
        (Path(state['worktree']) / 'easy-ref.toml').write_text('checks = []')
        self.assertEqual(load(state['run_dir'])['config']['checks'], [['original']])

    def test_push_environment(self):
        git(self.repo, 'remote', 'add', 'origin', 'https://example.invalid/repo')
        env = push_env(self.repo)
        result = subprocess.check_output(['git', 'config', '--get', 'remote.origin.pushurl'], env=env, text=True)
        self.assertEqual(result.strip(), 'invalid://easy-ref-disabled')

    def test_push_environment_resets_all_existing_pushurls(self):
        git(self.repo, 'remote', 'add', 'origin', 'https://example.invalid/fetch')
        git(self.repo, 'config', '--add', 'remote.origin.pushurl', 'https://example.invalid/one')
        git(self.repo, 'config', '--add', 'remote.origin.pushurl', 'https://example.invalid/two')
        before = git(self.repo, 'config', '--get-all', 'remote.origin.pushurl')
        output = subprocess.check_output(['git', '-C', str(self.repo), 'remote', 'get-url', '--push', '--all', 'origin'], env=push_env(self.repo), text=True)
        self.assertEqual(output.strip(), 'invalid://easy-ref-disabled')
        self.assertEqual(before, git(self.repo, 'config', '--get-all', 'remote.origin.pushurl'))

    def test_second_unfinished_run_refused(self):
        self.start()
        other = self.root / 'other.md'
        other.write_text('Other task')
        with self.assertRaisesRegex(ValueError, 'unfinished'):
            create(self.repo, other)

    def test_invalid_configuration(self):
        for config in ({'checks': ['shell command']}, {'timeout': float('nan')}, {'round_limit': True}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.start(**config)

    def test_configurable_external_worktree(self):
        state = self.start(worktree_root='../custom-agents')
        self.assertEqual(Path(state['worktree']).parent, (self.root / 'custom-agents').resolve())

    def test_external_git_directory_refused(self):
        with self.assertRaises(ValueError):
            self.start(worktree_root=str(self.root / 'other' / '.git' / 'agents'))

    def test_push_block_against_local_bare_remote(self):
        # Explicitly requested checkpoint test: isolated local bare repo only.
        bare = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(bare)], check=True)
        git(self.repo, 'remote', 'add', 'origin', str(bare))
        before = git(bare, 'for-each-ref')
        result = subprocess.run(['git', '-C', str(self.repo), 'push', 'origin', 'HEAD:refs/heads/test'],
                                env=push_env(self.repo), capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('invalid', result.stderr)
        self.assertEqual(git(bare, 'for-each-ref'), before)
