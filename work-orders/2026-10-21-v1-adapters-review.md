Status: done (commit "fix: commit builder changes from easy-ref")

# Gatekeeper review: v1 adapters, CLI, docs (commits 3–5)

Reviews: `fix: require committed builder work and tolerate reviewer caches` through `docs: document usage, configuration, and safety model` on `codex/v1-loop`.

Verdict: **changes required, one blocker.** Everything from the checkpoint review is fixed, and 76 tests pass on Python 3.11. Every Claude and Codex flag the adapters use exists in the installed CLIs (Claude Code 2.1.302, codex-cli 0.154.0). But the default builder can't do its job.

## Blocker: sandboxed builders can't commit

The reviewer reproduced this with Codex's own sandbox runner (`codex sandbox -P :workspace`), the same sandbox `codex exec --sandbox workspace-write` uses. The test repo was under the home directory, not `/tmp`:

- **Linked worktree** (current design): `git commit` fails. It can't create `<repo>/.git/worktrees/<id>/index.lock` because the main `.git` is outside the writable root.
- **Standalone clone:** also fails. It can't create `<clone>/.git/index.lock`. Codex keeps `.git` read-only even inside the workspace.
- **A `/tmp` repo hides this.** Commits succeed there, because the sandbox always allows writes to `/tmp`. The fake-adapter tests use temporary directories, so they can't catch it.

So every default run (Codex builder) would stop after round 1 with "builder made no new commit". Claude's builder sandbox wasn't tested. It most likely fails the same way for linked worktrees, and the fix below covers it either way.

### Required fix

Commit message: `fix: commit builder changes from easy-ref`

1. **easy-ref commits for the builder.**
   - After a successful builder call, easy-ref stages all non-ignored changes (`git add -A`) and commits them in the worktree, outside any sandbox.
   - The builder prompt says: don't commit. easy-ref commits your changes. Start your hand-back with a one-line commit subject.
   - Use that first line as the subject if it is nonempty, single-line, and 72 characters or fewer. Otherwise use `easy-ref: <order-slug> round <n>`.
   - If a builder did commit (an unsandboxed Pi, say), keep its commits as long as they descend from the round's start. Then commit anything left over.
2. **Builder-controlled hooks never run.** Commit with `--no-verify` and `-c core.hooksPath=/dev/null`. A repo that keeps hooks in tracked files (for example `.husky/`) would otherwise let the builder write a script that easy-ref runs outside the sandbox.
3. **Update the stop condition.** "No new commit" becomes "no changes": the builder produced nothing to commit and made no commits. The post-build cleanliness check stays as an assertion after easy-ref's commit.
4. **Tests.** Fake adapters edit files without committing; easy-ref commits them with the hand-back subject; the subject falls back when it's invalid; a builder-written hook in a tracked `core.hooksPath` doesn't run; "no changes" stops the run; builder commits plus leftover changes are both kept.
5. **Docs.**
   - Explain who commits.
   - State plainly that **check commands run builder-written code without a sandbox.** Running `python -m unittest` runs whatever tests the builder wrote, with the owner's permissions. Treat check commands as trusted, and the code they execute as untrusted.
   - List "run checks inside the harness sandbox" as a follow-up.

## Real-harness smoke test (the reviewer runs it, after the fix)

Don't run real models yourself. After this fix, the reviewer will run easy-ref for real:

- a throwaway repo under the home directory, not `/tmp`
- a tiny order: add a function and its unittest
- `python3.11 -m unittest` as the check
- Codex as builder, Claude Code as reviewer

The reviewer records what happened in the final review. That run decides whether v1 is ready to build its own follow-ups.

## Non-blocking (follow-ups, don't do now)

- **Large diffs.** Claude and Pi reviewers have no shell. Above the 64 KB inline cap they can't see the full diff. Write it to the run directory and grant read access there (Claude `--add-dir`).
- **Sandboxed checks.** On macOS, run checks through `codex sandbox` when it's available.

## Limits

Don't push or open a PR. Don't run real model calls.

## Acceptance criteria

- [ ] All tests pass with Python 3.11+. Paste the output.
- [ ] The tests in item 4 exist. List them.
- [ ] `git grep -n "no-verify\|hooksPath"` shows the commit guard.
- [ ] `git status -sb` is clean and nothing is pushed.

Mark this file `done (commit "fix: commit builder changes from easy-ref")` in the fix commit.
