Status: done (commit "fix: require committed builder work and tolerate reviewer caches")

# Gatekeeper review: v1 loop checkpoint (commits 1–2)

Reviews: commits `feat: add run state, worktree isolation, and CLI skeleton` and `feat: add loop, verdict parsing, and stop conditions with fake-adapter tests` on `codex/v1-loop`, against [2026-10-21-v1-loop.md](2026-10-21-v1-loop.md) and [2026-10-21-v1-design-review.md](2026-10-21-v1-design-review.md).

Verdict: **changes required, three fixes, then continue to the adapters.** The loop is well built. Every fail-closed path the order and design asked for is present and tested.

## What the reviewer verified

- **47 tests pass** on Python 3.11 and 3.13, at each of the two commits, run from an isolated archive.
- **Design-review amendments are in:**
  - the worktree sits outside the repo and `.git`
  - checks are frozen at run start
  - config changes are reported
  - push-block environment variables are set
  - remote-ref movement stops the run, including when the adapter crashes
- **Push block works against a real remote.** The reviewer pushed to a local bare remote by name with `push_env`, and the push failed (`remote helper 'invalid' aborted`).

## Required (one commit before the adapters)

Commit message: `fix: require committed builder work and tolerate reviewer caches`

1. **Approved work can be missing from the branch.** The reviewer reproduced this with the fake adapter:
   - The builder commits one file and leaves another file uncommitted.
   - The check (`test -f needed`) passes because of that uncommitted file, and the reviewer approves.
   - The run ends `DONE`, but `needed` is not on `ref/<slug>`.

   Fix: after each builder call, the worktree must be clean, ignoring gitignored files. If it isn't, skip checks and review. The next round's required fix lists the uncommitted paths, and the round counts toward the limit. Add a test.

2. **A reviewer running the tests stops the run.** The reviewer reproduced this as well:
   - A fake reviewer imports a module, the way running tests does. Python writes `__pycache__`, which is gitignored.
   - The run stops with `reviewer changed worktree or HEAD`.

   With Claude Code or Pi as reviewer, running tests during review is normal, so most real runs would stop here. Fix: leave gitignored files out of the stop condition. List any changed ignored paths in the summary and the next prompt instead. Changes to tracked files, non-ignored untracked files, the index, or HEAD still stop the run. Update `test_reviewer_edits_ignored_untracked_file` to match, and add a test that a tracked or non-ignored edit still stops. This reverses a deliberate choice of yours. The reason is that ignored files never reach the branch, but blocking them breaks the default reviewer.

3. **Subprocesses can block on input.** `process.execute` doesn't set `stdin`, so agents and checks inherit the terminal. An unattended agent waiting on a prompt hangs until the 30-minute timeout. Pass `stdin=subprocess.DEVNULL` by default. Adapters that need stdin can opt in explicitly.

## Non-blocking (fold into later commits)

- **Fix orders mangle relative paths.** `portable()` turns `src/app/range.py` into `src[path omitted]`. Redact only absolute paths and home-directory paths. Relative repository paths are allowed and useful. (Commit 3 or 4.)
- **`stop` on a waiting run.** `request_stop` only touches a file. An idle `NEEDS_OWNER` run never becomes `STOPPED`, so it blocks new runs forever. In commit 4, `stop` on a run with no active process should mark it `STOPPED` directly.
- **Python version.** The owner's default `python3` is 3.10, so imports fail on `tomllib` with an unhelpful error. Add a clear version check in `easy_ref/__init__.py`, and state the requirement in the docs. (Commit 4 or 5.)
- **Document these limits in commit 5:**
  - Pushing to an explicit URL (`git push <url>`) bypasses the push block and doesn't move remote-tracking refs. The reviewer verified this.
  - Agents running `git fetch` will trip remote-ref detection. That fails closed, but it will surprise people.
- **Add a test with a real bare remote.** `test_push_environment` only reads config. Add a real push to a bare remote, as the reviewer did, so the guardrail is proven by a test.

## Limits

Don't push or open a PR. Don't change the order or the design review.

## Acceptance criteria

- [ ] New tests for fixes 1–3 pass, and every existing test passes or is updated as described. Paste the output, run with Python 3.11+.
- [ ] The uncommitted-work scenario ends in a builder retry, not `DONE`.
- [ ] A fake reviewer writing `__pycache__` doesn't stop the run, and the ignored path is reported.
- [ ] `git status -sb` is clean and nothing is pushed.

Then continue with the order's commits 3–5. Mark this file `done (commit "fix: require committed builder work and tolerate reviewer caches")` in the fix commit.
