Status: done (104a8f6)

# Clean up: close the v1 work-order record

PR #1 (v1 loop) merged as `516f884`. Its last commit, `17c40d7`, fixed the Claude MCP config. The work-order record still has three gaps. Fix only these; this is a docs-only change.

## Do

1. `work-orders/2026-10-21-v1-loop.md`: change line 1 from `Status: open` to `Status: done (17c40d7)`.
2. Create `work-orders/2026-10-21-claude-mcp-config.md` with exactly the content below, except change line 1 to `Status: done (17c40d7)`. This order existed only as an uncommitted file and was lost from the record.
3. `docs/design/v1-loop-gate.md`: the last paragraph still says commits 3–5 "await review". Replace that paragraph with one sentence: all v1 commits were reviewed and approved, and v1 merged in PR #1. Keep the "No real-harness run is claimed" sentence only if it's still true. It isn't, because `docs/adapter-verification.md` records a real smoke run. So link that file instead.

## Limits

- Change no code, tests, or other docs.
- Don't edit the other work orders.

## Content for step 2

~~~markdown
Status: open

# Fix: Claude adapter's empty MCP config

The first real-harness smoke run (Codex builder, Claude reviewer, throwaway repo) built, committed, and checked correctly. Then the reviewer exited 1 with:

    Error: Invalid MCP configuration:
    mcpServers: Invalid input: expected record, received undefined

`easy_ref/adapters/claude.py` passes `--mcp-config '{}'`. Claude Code 2.1.302 requires `{"mcpServers":{}}`. The gatekeeper reran the identical reviewer command with that one value changed. It exited 0 with a valid structured `APPROVE`, no permission denials, and no worktree changes.

## Do

1. In `easy_ref/adapters/claude.py`, pass `{"mcpServers":{}}` (via `json.dumps`) instead of `{}`.
2. Add a test to `tests/test_adapters.py` asserting the exact `--mcp-config` value Claude receives.
3. Add the smoke-run result to `docs/adapter-verification.md`. Write one short paragraph covering:
   - what ran
   - the MCP failure and its fix
   - that no transcript is stored

Change nothing else.
~~~
