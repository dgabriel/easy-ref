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
| No new commit | `test_no_new_commit` |
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

- `test_uncommitted_builder_work_retries_before_checks`: a partial commit with an
  uncommitted needed file triggers a builder retry; only its committed fix can
  reach `DONE`. `test_uncommitted_builder_work_exhausts_limit_without_approval`
  proves it cannot approve if the retry budget is exhausted.
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
