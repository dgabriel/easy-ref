Status: done (17c40d7)

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
