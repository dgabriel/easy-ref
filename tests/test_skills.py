import contextlib
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

from easy_ref.__main__ import display, main
from easy_ref.core import load
from easy_ref.loop import answer, prompt, run
from easy_ref.skills import LIMIT, PRECEDENCE, collect, digest
from tests.test_core import RepoTest
from tests.test_loop import Fake, verdict


class SkillTests(RepoTest):
    def skill(self, name, parent=None):
        path = (parent or self.root.resolve()) / name
        path.mkdir(parents=True)
        (path / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: Test\n---\n{name} instructions\n', encoding='utf-8')
        return path

    def test_role_prompts_frozen_across_rounds_and_resume(self):
        builder_path = self.skill('regression-testing')
        reviewer_path = self.skill('spec-review')
        refs = reviewer_path / 'references'
        refs.mkdir()
        (refs / 'z.md').write_text('last reference')
        (refs / 'a.md').write_text('first reference')
        # Unselected content must never be opened, even if invalid UTF-8.
        (reviewer_path / 'ignored.md').write_bytes(b'\xff')
        (refs / 'ignored.txt').write_bytes(b'\xff')
        (refs / 'nested').mkdir()
        (refs / 'nested' / 'ignored.md').write_bytes(b'\xff')
        state = self.start(builder_skills=['../regression-testing'], reviewer_skills=['../spec-review'])
        original_records = state['skills']
        for path in (builder_path, reviewer_path):
            (path / 'SKILL.md').write_text('SOURCE CHANGED')
        builder = Fake(['edit', 'edit'])
        reviewer = Fake([verdict('CHANGES_REQUIRED'), verdict('NEEDS_OWNER'), verdict()])
        result = run(state['run_dir'], builder, reviewer, notify=lambda _: None)
        self.assertEqual(result['status'], 'NEEDS_OWNER', result['reason'])
        answer(state['run_dir'], 'Continue')
        result = run(state['run_dir'], builder, reviewer, notify=lambda _: None)
        self.assertEqual(result['status'], 'DONE', result['reason'])
        self.assertEqual(len(builder.prompts), 2)
        self.assertEqual(len(reviewer.prompts), 3)
        for role, adapter, name, other in (
                ('builder', builder, 'regression-testing', 'spec-review'),
                ('reviewer', reviewer, 'spec-review', 'regression-testing')):
            for message in adapter.prompts:
                self.assertIn(name + '/SKILL.md', message)
                self.assertIn(name + ' instructions', message)
                self.assertNotIn(other + ' instructions', message)
                self.assertNotIn('SOURCE CHANGED', message)
                self.assertLess(message.index(PRECEDENCE), message.index(name + ' instructions'))
            record = original_records[role][0]
            frozen = Path(state['run_dir']) / 'skills' / role / name
            self.assertEqual(record['sha256'], digest({f: (frozen / f).read_bytes() for f in record['files']}))
        message = reviewer.prompts[-1]
        self.assertLess(message.index('spec-review/references/a.md'), message.index('spec-review/references/z.md'))
        self.assertEqual(load(state['run_dir'])['skills'], original_records)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            display(result)
        self.assertEqual(json.loads(output.getvalue())['skills'], original_records)
        summary = (Path(state['run_dir']) / 'summary.txt').read_text()
        for role in original_records:
            record = original_records[role][0]
            self.assertIn(record['name'], summary)
            self.assertIn(record['sha256'], summary)

    def test_no_skills_leaves_both_prompts_unchanged(self):
        state = self.start()
        directory = Path(state['run_dir'])
        common = ('Build a thing\n\nNever push, open pull requests, merge, deploy, or delete branches.\n'
                  'Ignored paths changed during prior reviews: []\n'
                  'Unsandboxed adapters (Pi): []\nOwner decisions:\n')
        expected_builder = (common + '\nRequired fixes:\n\nDo not commit. easy-ref commits your changes. '
                            'Start your hand-back with a one-line commit subject, 72 characters or fewer.\n')
        expected_reviewer = (common + f"\nBase: {state['base']}\nHEAD: {state['base']}\nDiff:\n\n"
                             '\nWorking-tree status:\n\nInspect untracked files locally.\n'
                             '\nHand-back:\n\nChecks:\n[]\nCheck sandbox: none\n'
                             '\nConfiguration changed: False\n' + state['warning'] +
                             '\nReview read-only. Return strict verdict JSON with verdict, summary, required'
                             ' (id, what, evidence), and owner_question only for NEEDS_OWNER.\n')
        self.assertEqual(prompt(state, 'builder', directory), expected_builder)
        self.assertEqual(prompt(state, 'reviewer', directory), expected_reviewer)

    def test_builder_skills_close_with_output_contract(self):
        self.check_skill_output_contract('builder')

    def test_reviewer_skills_close_with_output_contract(self):
        self.check_skill_output_contract('reviewer')

    def check_skill_output_contract(self, role):
        contracts = {
            'builder': 'Do not commit. Start your hand-back with a one-line commit subject, 72 characters or fewer.',
            'reviewer': "Return only strict verdict JSON with verdict, summary, required (id, what, evidence), and owner_question only for NEEDS_OWNER, not the skill's report format.",
        }
        closing = contracts[role]
        path = self.skill(role + '-output')
        refs = path / 'references'
        refs.mkdir()
        (refs / 'output.md').write_text('Return a PASS/FAIL report.\n\n')
        state = self.start(**{role + '_skills': [str(path)]})
        directory = Path(state['run_dir'])
        message = prompt(state, role, directory)
        self.assertEqual(message.rstrip().splitlines()[-1], closing)
        self.assertLess(message.index(PRECEDENCE), message.index(path.name + ' instructions'))
        self.assertLess(message.index('Return a PASS/FAIL report.'), message.rindex(closing))
        other = 'reviewer' if role == 'builder' else 'builder'
        without_skills = dict(state, skills={}, config={**state['config'], role + '_skills': []})
        self.assertEqual(prompt(state, other, directory), prompt(without_skills, other, directory))

    def test_invalid_sources_refused_before_worktree_creation(self):
        for case in ('missing', 'no-header', 'wrong-name', 'duplicate-name-field', 'unterminated',
                     'file-link', 'directory-link', 'reference-link', 'references-link',
                     'directory-file', 'fifo', 'reference-directory', 'utf8', 'reference-utf8', 'oversize'):
            with self.subTest(case=case):
                path = self.skill(case)
                entry = path / 'SKILL.md'
                if case == 'missing':
                    entry.unlink()
                elif case in ('no-header', 'wrong-name', 'duplicate-name-field', 'unterminated'):
                    entry.write_text({'no-header': 'name: no-header', 'wrong-name': '---\nname: other\n---',
                                      'duplicate-name-field': '---\nname: duplicate-name-field\nname: other\n---',
                                      'unterminated': '---\nname: unterminated'}[case])
                elif case == 'file-link':
                    entry.unlink()
                    entry.symlink_to(self.order)
                elif case == 'directory-link':
                    link = path.parent / 'link'
                    link.symlink_to(path, target_is_directory=True)
                    path = link
                elif case in ('directory-file', 'fifo'):
                    entry.unlink()
                    entry.mkdir() if case == 'directory-file' else os.mkfifo(entry)
                elif case == 'utf8':
                    entry.write_bytes(b'\xff')
                elif case == 'oversize':
                    entry.write_bytes(entry.read_bytes() + b'x' * LIMIT)
                else:
                    refs = path / 'references'
                    if case == 'references-link':
                        refs.symlink_to(self.root, target_is_directory=True)
                    else:
                        refs.mkdir()
                        file = refs / 'bad.md'
                        if case == 'reference-link':
                            file.symlink_to(self.order)
                        elif case == 'reference-directory':
                            file.mkdir()
                        else:
                            file.write_bytes(b'\xff')
                with self.assertRaises((ValueError, OSError)):
                    self.start(builder_skills=[str(path)])
                self.assertFalse((self.root / 'repo.easy-ref').exists())

    def test_duplicates_and_role_byte_limits(self):
        a = self.skill('same', self.root.resolve() / 'a')
        b = self.skill('same', self.root.resolve() / 'b')
        for role in ('builder', 'reviewer'):
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                self.start(**{role + '_skills': [str(a), str(b)]})
        # Same name in different roles is allowed, and limits are per role.
        entry = a / 'SKILL.md'
        entry.write_bytes(entry.read_bytes() + b'x' * (LIMIT - entry.stat().st_size))
        config = {'builder_skills': [str(a)], 'reviewer_skills': [str(a)]}
        collect(self.repo.resolve(), config)
        refs = a / 'references'
        refs.mkdir()
        (refs / 'extra.md').write_text('é', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '128 KB'):
            collect(self.repo.resolve(), config)
        (refs / 'extra.md').unlink()
        c = self.skill('another')
        with self.assertRaisesRegex(ValueError, '128 KB'):
            collect(self.repo.resolve(), {'builder_skills': [str(a), str(c)], 'reviewer_skills': []})

    def test_invalid_config_lists(self):
        for value in ('path', [1], [''], ['\0'], [False]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.start(builder_skills=value)

    def test_corrupt_frozen_copy_stops_before_adapter(self):
        path = self.skill('example')
        state = self.start(builder_skills=[str(path)])
        frozen = Path(state['run_dir']) / 'skills/builder/example/SKILL.md'
        frozen.write_text('corrupted')
        builder = Fake(['edit'])
        result = run(state['run_dir'], builder, Fake([verdict()]), notify=lambda _: None)
        self.assertEqual(result['status'], 'NEEDS_OWNER')
        self.assertIn('digest mismatch', result['reason'])
        self.assertEqual(builder.prompts, [])

    def test_cli_replaces_each_roles_list(self):
        for name in ('build-one', 'build-two', 'review-one'):
            self.skill(name)
        (self.repo / 'easy-ref.toml').write_text('builder_skills = ["missing-builder"]\nreviewer_skills = ["missing-reviewer"]\n')
        with patch('easy_ref.__main__.dispatch', side_effect=lambda state: {**state, 'status': 'DONE'}) as dispatch, \
                contextlib.redirect_stdout(io.StringIO()):
            code = main(['run', str(self.order), '--repo', str(self.repo),
                         '--builder-skill', '../build-one', '--builder-skill', '../build-two',
                         '--reviewer-skill', '../review-one'])
        self.assertEqual(code, 0)
        state = dispatch.call_args.args[0]
        self.assertEqual([s['name'] for s in state['skills']['builder']], ['build-one', 'build-two'])
        self.assertEqual([s['name'] for s in state['skills']['reviewer']], ['review-one'])

    def test_cli_preserves_unoverridden_role(self):
        self.skill('configured-reviewer')
        self.skill('chosen-builder')
        (self.repo / 'easy-ref.toml').write_text(
            'builder_skills = ["missing"]\nreviewer_skills = ["../configured-reviewer"]\n')
        with patch('easy_ref.__main__.dispatch', side_effect=lambda state: {**state, 'status': 'DONE'}) as dispatch, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main(['run', str(self.order), '--repo', str(self.repo),
                         '--builder-skill', '../chosen-builder'])
        self.assertEqual(code, 0)
        self.assertEqual(dispatch.call_args.args[0]['skills']['reviewer'][0]['name'], 'configured-reviewer')
