Status: done (1282adb)

# Run check commands inside the Codex sandbox

Today, check commands run builder-written code with the owner's full permissions. For example, `python -m unittest` executes whatever tests the builder wrote. The README lists "running checks inside the harness sandbox" as a follow-up. This order does it for macOS through `codex sandbox`, the same sandbox Codex builders already run in.

## What the gatekeeper verified with codex-cli 0.154.0

Inside a git worktree under the home directory, `codex sandbox -P :workspace -c <key=value> -C <dir> -- sh -c '...'`:

- **ran** the command
- **denied** writes to the home directory and to the owner's main checkout
- **allowed** writes to `/tmp`
- **denied** writes to `.git`, even inside the workspace

Two details to watch:
- The CLI reports a usage error unless `--config` is given alongside `-P`, so a harmless `-c` value is needed.
- `-P workspace-write` (without the colon) fails.

Re-verify everything from `codex sandbox --help` before relying on it.

## Do

1. **Config.** Add `check_sandbox` to `easy-ref.toml` and the CLI flag `--check-sandbox`, with three values:
   - `auto` (default): use `codex sandbox` when on macOS and `codex` is installed and its help confirms the options you use. Otherwise run checks unsandboxed, as now, and record a warning.
   - `codex`: require the sandbox. Refuse to create the run if it isn't available.
   - `none`: run unsandboxed, as now. Record a warning.

   Resolve the mode once when the run is created and freeze it in `run.json`, like the rest of the config. Show it in `status`, in the stop summary, and in the reviewer prompt's check section.
2. **Wrap check commands** as `codex sandbox -P :workspace -c <harmless key=value> -C <worktree> -- <check argv>`. Keep everything else unchanged:
   - argument arrays with no shell
   - timeouts and process-group cleanup through `process.execute`
   - `stdin` set to DEVNULL
   - the push-block environment
   - remote-ref checks before and after

   Don't enable network access, and add no writable roots.
3. **The push-block environment must reach the check.** Check whether `codex sandbox` passes the `GIT_CONFIG_*` variables through. If it doesn't, pass them explicitly, for example through the same `shell_environment_policy.set` mechanism the Codex adapter uses. Prove it with a test.
4. **A sandbox failure is not a check failure.** If `codex sandbox` itself can't start, the run stops with `NEEDS_OWNER`. It is not a failing check fed back to the builder. Ordinary nonzero exits from the check command keep today's behavior.
5. **Tests use a fake `codex` executable** on `PATH`, no real sandbox:
   - argv shape for each mode
   - `auto` falls back with a warning when `codex` is missing
   - `codex` mode refuses run creation when `codex` is missing
   - the mode is frozen across resume
   - push-block variables are present in the wrapped command's environment
   - sandbox start failure → `NEEDS_OWNER`
6. **Docs.** In the README safety section, say that checks run in the Codex `:workspace` sandbox when available. Spell out what it blocks (writes outside the worktree and temp, `.git` writes) and what it doesn't (it's still not network or OS isolation beyond that profile). Say that `none` or a fallback brings back today's risk. Remove "running checks inside the harness sandbox" from the follow-ups.

## Limits

- Don't change the builder or reviewer adapters.
- Don't run real models.
- Run tests with a Python 3.11+ interpreter (for example `python3.11 -m unittest`). The default `python3` may be older.
- Python standard library only.

## Done when

All tests pass, including those in step 5. The reviewer can find, for each numbered step above, the code and test that satisfy it.
