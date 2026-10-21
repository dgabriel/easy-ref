# v1 loop design — approved with amendments

Approved by [design review](../../work-orders/2026-10-21-v1-design-review.md).

Scope: the open v1 loop order. This note precedes implementation; no loop code
will be written until the reviewer approves it. Python 3.11+, standard library
only. Work takes place on `codex/v1-loop` in a separate worktree.

## Module layout

- `easy_ref/cli.py`, `__main__.py`: run, status, answer, stop; argument validation.
- `config.py`: TOML loading, explicit CLI overrides, check commands, models,
  limits, timeouts, notifier, and unsandboxed opt-in.
- `state.py`: versioned run records, atomic writes, exclusive mutation lock,
  transition validation, and restart recovery.
- `git.py`: worktree creation and identity checks, base/HEAD/status capture,
  diffs, and builder-commit verification. No publish or merge operations.
- `loop.py`: persisted build/check/review/verify/decide transitions.
- `checks.py`, `verdict.py`, `notify.py`: independent subprocess checks, strict
  verdict validation, and pluggable notification with terminal fallback.
- `adapters/base.py`, `codex.py`, `claude.py`, `pi.py`: harness protocol and
  implementations, selected through configuration and a small registry.
- `tests/`: temporary Git repositories and scripted fake adapters only.

## Adapter interface

`invoke(role, prompt, worktree, run_dir, timeout) -> AdapterResult`, with the
configured model and permission policy supplied when constructing the adapter.
`AdapterResult` contains `exit_code`, `final_message`, and `log_path`.
Crashes, timeouts, nonzero exits, or missing output become explicit failures,
never verdicts. The caller records them and transitions to `NEEDS_OWNER`.
Subprocesses use argument arrays, a bounded timeout, and process-group cleanup.

Before implementing each adapter, record the installed CLI version and inspect
its help for every used option. Prefer structured output; otherwise use the
specified fenced-JSON fallback. Refuse unsupported permission configurations.
Pi requires explicit `--allow-unsandboxed` and a summary warning. No bypass flags.

## Verdict format and verification

Require exactly `verdict`, `summary`, `required`, plus `owner_question` only for
`NEEDS_OWNER`. Verdict is one of the three specified strings; summary and all
finding fields are nonempty strings. Each finding has exactly `id`, `what`, and
`evidence`, with unique IDs. `APPROVE` requires an empty required list;
`CHANGES_REQUIRED` requires at least one finding; `NEEDS_OWNER` requires a
nonempty question. Reject duplicate JSON keys, unknown fields, incorrect types,
invalid JSON, or conflicting/ambiguous verdict payloads. For text fallback,
parse the last fenced JSON block and reject conflicting verdict blocks.

Failed checks skip review and feed their captured output into the next builder
round. The decision function independently rejects approval with failed checks.
Before and after review, compare HEAD and porcelain status and fingerprint
working-tree/index contents, including untracked files: status alone cannot
detect edits to an already dirty file. Any observed change stops for the owner.
Permission controls and snapshots cannot prove that a reviewer never temporarily
changed and restored a file; this limitation will be documented.

## Run-state layout

Resolve the target repository's Git directory with Git, then store:

```text
<git-dir>/easy-ref/runs/<run-id>/
  run.json
  summary.txt
  decisions.jsonl
  rounds/001/
    builder-prompt.txt
    builder.log
    hand-back.txt
    checks.json
    checks/001.log
    reviewer-prompt.txt
    reviewer.log
    verdict.json
```

`run.json` includes schema version, run ID, repository/worktree identity, base
commit, branch, resolved configuration, order snapshot reference, round count,
phase, stop reason, pending question and its origin, resume phase, and check
results. Save the original order inside the run directory. Runtime paths and
logs remain outside tracked content. Use atomic replacement for state and a
per-run exclusive lock; refuse simultaneous active runs for the target repo.

Persist intent before each subprocess and results afterward. An interrupted
in-flight operation becomes `NEEDS_OWNER` on recovery; never infer success or
silently rerun it. `answer` records a decision and resumes only an owner-waiting
run: review for a reviewer question, otherwise build. Invalidation of saved
checks or Git identity requires fresh checks or owner intervention. Completed
and explicitly stopped runs cannot be resumed by accident. `stop` persists a
stop request that the active process observes while waiting for subprocesses.

On creation, refuse existing `ref/<order-slug>` branches or worktrees; record the
current HEAD as the immutable base. Each builder round must advance HEAD to a
new descendant commit. Default round limit is three and agent timeout is thirty
minutes. Compare exact `what` strings across consecutive reviews for repeated
findings. Every terminal/waiting transition writes the required summary and
notifies through the configured notifier.

If `work-orders/` exists, create a uniquely named open fix order inside the
agent worktree after `CHANGES_REQUIRED`, with only review findings and portable
evidence; tell the builder to commit it with the fix. Do not copy raw logs,
session IDs, credentials, or absolute machine paths into tracked files.

## Verification plan and review questions

Implement all twelve fake-adapter scenarios listed in the order, plus strict
parser cases, dirty-file reviewer edits, interrupted-state recovery, stop during
an agent call, and invalid resume transitions. Add the repository's unittest
check configuration. Run `python3 -m unittest` at each implementation commit
and paste actual output, alongside the requested Git safety checks. No real
model calls are planned for tests; CLI help/version inspection is not a harness
run.

One safety clarification needs approval: arbitrary configured check commands and
general-purpose builder tools can themselves execute Git/network commands.
The standard library and harness workspace permissions do not enforce a hard
ban on publishing. v1 should expose no publishing operation, explicitly forbid
publishing in agent prompts, and treat repository configuration as trusted owner
input; stronger OS/network isolation is a follow-up. Please confirm this boundary
or require stronger isolation before adapter implementation.

Review gate: approve or amend this design before implementation begins. The
source work order stays open until the final reviewer approval.

## Approved amendments

Worktrees default to `<repo-parent>/<repo-name>.easy-ref/<run-id>/`, configurable,
outside both the tracked tree and Git directory. Record their path; never delete
them automatically, and include manual removal instructions in summaries.
Freeze resolved owner-checkout configuration in run.json at creation. Report
builder config edits without changing checks. Every agent/check process receives
environment Git configuration overriding each remote pushurl with an invalid URL;
snapshot remote-tracking refs around each call and stop if they move. Preserve
harness network defaults. These are best-effort guardrails, not isolation.
Cap inline diffs; supply stat/base/HEAD above the cap. Reworded repeated findings
and full OS/network isolation remain follow-ups.
