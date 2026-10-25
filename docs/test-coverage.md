# v1 acceptance coverage

All Python tests are standard-library `unittest` cases. Test repositories,
credentials-free fixture outputs, and fake CLI executable scripts are temporary.
No installed model CLI is invoked by tests. Help/version inspection is separate
from testing and is recorded in [adapter verification](adapter-verification.md).

| Order scenario | Test in `tests/test_loop.py` unless stated |
| --- | --- |
| Approve round 1 | `test_approve_round_one` |
| Changes then approve | `test_changes_then_approve` |
| Checks fail and feed builder | `test_failing_checks_feed_builder_skip_review` |
| Malformed verdict stops | `test_malformed_verdict`, `test_strict_parser` |
| Reviewer changes files | `test_reviewer_modifies_dirty_file`, `test_reviewer_nonignored_untracked_edit_stops`, `test_reviewer_changes_head` |
| Approval with failed checks stops | `test_approval_with_failed_checks_rejected` (decision-function regression; the normal loop skips review on failure) |
| No changes (supersedes no new commit) | `test_no_changes`, `test_ignored_only_builder_changes_stop_without_commit` |
| Repeated finding | `test_repeated_finding` |
| Round limit | `test_round_limit`, `test_failing_checks_exhaust_rounds` |
| Timeout | `test_adapter_timeout`, `test_check_timeout`, `test_real_process_timeout_and_stop` |
| Answer/resume | `test_answer_reviewer_resumes_review`, `test_answer_builder_resumes_build`; `test_cli_answer_resumes_reviewer` in `test_cli.py` |
| Existing branch refused | `test_existing_branch` in `test_core.py` |

## Design-review amendments

- `test_isolation_and_state`, `test_invalid_worktree`,
  `test_configurable_external_worktree`, `test_external_git_directory_refused`:
  default/configured worktree paths, persisted state, refused tracked/Git paths.
- `test_frozen_config` and `test_frozen_checks_and_agent_check_environments`:
  builder edits cannot change frozen checks and are reported to review.
- `test_remote_tracking_movement`, `test_check_remote_movement`,
  `test_ref_change_even_on_adapter_crash`: agent/check ref movement fails closed.
- `test_push_environment`, `test_push_environment_resets_all_existing_pushurls`,
  `test_push_block_against_local_bare_remote`: environment overrides and a real
  rejected local bare-remote push, without editing Git config files.
- `test_frozen_checks_and_agent_check_environments`: policy environment reaches
  both roles and the check subprocess. Fake executable tests in `test_adapters.py`
  additionally verify adapter invocations, stdin, structured output and errors.

## Checkpoint amendments

- The earlier uncommitted-work retry behavior is superseded by the adapter review:
  easy-ref now commits edits before checks. The clean-worktree assertion remains
  after the host commit; see the tests below.
- `test_reviewer_python_cache_is_reported_and_allows_review` and
  `test_reviewer_edits_ignored_untracked_file`: ignored caches/edits are tolerated,
  preserved in reports, and passed into later prompts. Tracked/non-ignored edits
  still stop.
- `test_process_stdin_is_closed_by_default`, `test_process_stdin_explicit_opt_in`:
  checks receive EOF; an adapter can explicitly supply a prompt file.
- `test_fix_order_keeps_relative_paths_redacts_absolute_and_home`: usable relative
  source paths survive fix-order redaction.
- `test_stop_idle_waiting_run_unblocks_new_run`,
  `test_stop_active_worker_only_requests_stop` in `test_cli.py`: idle stops are
  persisted immediately; active workers receive a stop request.
- `test_python_version_guard` in `test_cli.py`: Python older than 3.11 gets an
  explicit version error before `tomllib` is imported.

Additional tests cover restart recovery, artifact preservation on review resume,
invalid resume transitions, active run locks, branch identity changes, symlink
fix-order directories, capped large diffs, config/CLI overrides, notifier fallback
and argument safety, missing adapter capabilities, permission-denial/error
results, Pi opt-in, and the complete CLI path using fake harness processes.


## Adapter-review fix: host-owned commits

- `test_uncommitted_builder_work_is_committed_before_checks`: the fake builder
  only edits; easy-ref commits in round one using the hand-back subject before
  checking/reviewing. The builder prompt explicitly says not to commit.
- `test_long_subject_uses_fallback`, `test_empty_first_line_uses_fallback`,
  `test_subject_validation`: invalid subjects fall back; a 72-character subject
  is accepted and control characters are rejected.
- `test_builder_written_tracked_hooks_never_run`: tracked hooks configured through
  `core.hooksPath` cannot execute during host Git operations; includes pre-commit,
  prepare-commit-msg, commit-msg, post-commit, and post-index-change hooks.
- `test_no_changes`, `test_ignored_only_builder_changes_stop_without_commit`:
  nothing to commit and no builder commits stops for the owner.
- `test_builder_commits_plus_leftover_changes_are_kept`: valid builder commits
  and subsequent uncommitted edits are both preserved in the branch.
- `test_existing_builder_commit_without_leftovers_is_kept`: no empty host commit
  is added when the builder already committed all edits.
- `test_host_commit_failure_stops_before_checks_and_review`: a real Git identity
  failure cannot proceed to checks or approval.
- `test_host_commit_includes_deletions_and_excludes_ignored_files`: tracked
  deletions are committed and ignored new files stay out of the branch.
- `test_interrupted_host_commit_requires_owner`: interrupted host commit work is
  never inferred to have succeeded or replayed automatically.
- `test_builder_rewind_is_refused_before_host_commit`: non-descendant history
  cannot be accepted or hidden by the host commit.
- The full fake-CLI subprocess test also leaves builder edits uncommitted, so it
  exercises host staging/committing through the public CLI.

Check commands still execute builder-written code without a sandbox. Running
checks inside the harness sandbox and giving shell-free reviewers full-diff
access above the inline cap remain follow-ups, as required by the adapter review.

## Owner-supplied role skills

All skill tests are in `tests/test_skills.py`; model calls use fake adapters only.

| Work-order step | Implementation | Verification |
| --- | --- | --- |
| 1. Config and CLI | `config.resolve`, `__main__.parser` | `test_cli_replaces_each_roles_list`, `test_cli_preserves_unoverridden_role`, `test_invalid_config_lists` |
| 2. Validate and freeze | `skills.collect`, `skills.freeze`, `core._create` | `test_invalid_sources_refused_before_worktree_creation`, `test_duplicates_and_role_byte_limits`, `test_role_prompts_frozen_across_rounds_and_resume` |
| 3. Prompt and precedence | `skills.section`, `loop.prompt` | `test_role_prompts_frozen_across_rounds_and_resume`, `test_no_skills_leaves_both_prompts_unchanged` |
| 4. Visibility | `__main__.display`, `loop.finish` | `test_role_prompts_frozen_across_rounds_and_resume` checks status JSON and stop summary |
| 5. Fake-adapter coverage | `tests/test_skills.py` | Tests above, plus `test_corrupt_frozen_copy_stops_before_adapter` |
| 6. Documentation | README's Owner-supplied skills section | Relative sibling-checkout TOML and CLI examples; trusted-input and freezing behavior documented |
