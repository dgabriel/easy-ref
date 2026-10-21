# Implementation gate: commits 1 and 2

The design was approved with the amendments in the design review. The design
and review were committed before implementation. The v1 work order remains open.

Implemented: persisted run records, sibling worktree isolation and configurable
location, frozen configuration, push-block environment, remote-ref monitoring,
strict verdict parsing, independent checks, loop stop conditions, summaries,
and injected fake-adapter tests. Library-level answer/resume and stop requests
exist to exercise the state machine; CLI integration and platform notifications
remain for commit 4. The CLI currently exposes help and refuses execution.
There are no live harness adapters; the protocol requires the policy environment,
timeout and stop handling via the shared subprocess runner. Live CLI flag/version
verification belongs to commit 3 and has not been performed.

Checks are configured as argument arrays, never shell strings. Resumed reviews
rerun the frozen checks and keep earlier artifacts in separate attempt directories.
A worktree/branch identity change or interrupted operation stops for the owner.
No worktree is automatically removed. Every stop summary includes its location
and a manual removal command. Runs without checks explicitly warn that nothing
independent was verified.

The publishing guardrails are best-effort, not isolation. Subprocess environment
configuration first resets each remote's multi-valued pushurl list, then supplies
an invalid URL, without editing Git config files. Remote-tracking refs are compared
before and after each agent/check call, including failed calls. Explicit URLs,
new remotes, environment overrides, remote operations that leave no local ref
movement, or temporary edits that are restored can evade these guardrails.
Configuration is trusted owner input. Full OS/network isolation and semantic
matching of reworded repeated findings remain follow-ups. Future adapters must
preserve default sandbox network settings.

Fix orders contain requirements and a pointer to private evidence instead of
copying raw review logs into tracked files. Path-like and labelled sensitive
values in requirements are redacted. Full verdicts, prompts, checks and logs
remain in private run storage. Existing historical work orders are never acted
on automatically.

## Test coverage at this gate

All tests use temporary Git repositories and scripted fake adapters; subprocess
checks run only local Python/Git commands, with no model calls.

- Approve in round one; changes then approve and commit the generated fix order.
- Failed checks feed the builder and skip review; failed checks exhaust rounds.
- Malformed verdict; duplicate keys, invalid fields/types, ambiguous fenced JSON.
- Reviewer changes a dirty file, ignored untracked file, or HEAD.
- Approval with failing checks is rejected independently by the decision function.
- No new commit; repeated finding; round limit; adapter timeout/crash/nonzero exit.
- Reviewer and builder answer/resume; fresh checks; preserved review artifacts;
  completed/stopped/exhausted runs and empty answers cannot resume.
- Existing branch refused; external default/configured worktree location; paths
  inside the repository or a Git directory refused; unfinished runs block starts.
- Builder config edits do not change checks; agent/check push-block environment;
  multiple existing push URLs are reset without editing configuration files.
- Agent/check remote-tracking ref movement, including an adapter crash, stops.
- Interrupted in-flight recovery; active run lock; stop before/during agent work;
  actual local subprocess timeout and cancellation.
- Large diff cap; symlink fix-order directory refused; branch changes stop.

No real-harness run is claimed. Commit 3 (harnesses), commit 4 (CLI completion and
notifications), and commit 5 (full usage/safety documentation) await review.
