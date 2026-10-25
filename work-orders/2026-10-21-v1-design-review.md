Status: done (commit "docs: add v1 design note and review")

# Gatekeeper review: v1 design note

Reviews: the design note for [2026-10-21-v1-loop.md](2026-10-21-v1-loop.md).

Verdict: **approved with four amendments.** Start implementation and fold these in. No second design round is needed.

The design note goes beyond the order in useful ways, and those additions are approved:

- strict verdict schema with duplicate-key rejection
- fingerprinting dirty and untracked files instead of trusting `git status`
- persist-intent-before-subprocess, with interrupted runs going to `NEEDS_OWNER`
- process-group cleanup
- refusing to resume completed or stopped runs

## Amendments (required)

1. **Say where agent worktrees live.** The note creates them but doesn't say where.
   - Default to a sibling directory, `<repo-parent>/<repo-name>.easy-ref/<run-id>/`, configurable.
   - Never inside the owner's tracked tree, and not under `.git`, because harnesses treat `.git` paths specially.
   - Record the path in `run.json`.
   - v1 doesn't delete worktrees. The summary says where the worktree is and how to remove it.

2. **Freeze the checks at run start.** The builder can edit `easy-ref.toml` in its worktree, which would let it change or remove the checks that judge it.
   - Load the configuration once, from the owner's checkout when the run starts, and store the resolved copy in `run.json`.
   - Every round uses that frozen copy.
   - If the builder changes `easy-ref.toml`, say so in the next reviewer prompt and the summary. It doesn't change the checks for this run.

3. **Publishing boundary: your proposal is accepted for v1, with two additions.** Configuration is trusted owner input; full OS and network isolation is a documented follow-up. Add these guardrails. They aren't a security boundary, and the docs should say so:
   - **Block git pushes.** Every agent and check subprocess gets environment-level git config (`GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_n` / `GIT_CONFIG_VALUE_n`) that sets each remote's `pushurl` to an invalid URL. Don't write git config files.
   - **Detect pushes after the fact.** Snapshot `git for-each-ref refs/remotes` before and after each agent call and each check run. Any change stops the run with `NEEDS_OWNER`, and the summary says what moved.
   - **Leave sandbox defaults alone.** Don't turn on harness network access that is off by default.

4. **Commit this design.** The note is untracked in `design/` inside a `/tmp` worktree, where a reboot can delete it.
   - Commit it as `docs/design/v1-loop.md`, with this review file, as `docs: add v1 design note and review`. Do this before commit 1.
   - Change its heading from "awaiting reviewer approval" to "approved with amendments", and link this review.
   - Set this review's status to `done (commit "docs: add v1 design note and review")`.

## Non-blocking (note only)

- **Large diffs.** Inline the diff only up to a size cap. Above it, give the reviewer the stat summary and the base and HEAD commits to inspect itself.
- **Repeated findings.** Exact `what` matching will miss reworded repeats. The round limit catches those, so this is fine for v1. List it as a follow-up.

## Commits

The design commit above, then the order's five commits unchanged. The amendments go into the commits where their code lives: amendments 1 and 2 in commit 1, amendment 3 in commits 1 and 3.

## Acceptance criteria (added to the order's)

- [ ] Tests cover: worktree path outside the tracked tree and `.git`; a builder edit to `easy-ref.toml` doesn't change the run's checks; a remote-tracking ref change during a fake agent call → `NEEDS_OWNER`; the push-block environment is present on agent and check subprocesses.
- [ ] Docs state that the publishing guardrails are best-effort, not isolation.
