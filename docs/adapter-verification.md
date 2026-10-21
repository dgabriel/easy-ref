# CLI compatibility record

Help and version inspection on 2026-10-21 was performed without model calls.
The reviewer separately reported the smoke run recorded below. Raw help stayed
outside tracked files. Runtime preflight checks that required flags are present,
and records the installed versions in private state.

| CLI version | Help checked | Flags used |
| --- | --- | --- |
| codex-cli 0.154.0 | `codex exec --help` | `exec`, `--sandbox` (`workspace-write`, `read-only`), `--cd`, `--ephemeral`, `--ignore-user-config`, `--output-last-message`, `--output-schema`, `--model`, `--config`, stdin `-` |
| Claude Code 2.1.302 | `claude --help` | `--print`, `--output-format json`, `--json-schema`, `--permission-mode` (`acceptEdits`, `manual`), `--permission-prompts none`, `--restricted`, `--safe-mode`, `--tools`, `--disallowedTools`, `--settings`, `--strict-mcp-config`, `--mcp-config`, `--no-session-persistence`, `--model` |
| Pi 0.87.1 | `pi --help` | `--print`, `--tools`, `--no-session`, `--no-extensions`, `--no-skills`, `--no-prompt-templates`, `--no-themes`, `--model`, `--`, `@file` |

Codex uses its structured-output option for reviews, as described in the
[official OpenAI example](https://developers.openai.com/cookbook/examples/codex/build_iterative_repair_loops_with_codex).
The Git environment overrides are explicitly carried into Codex's shell environment
with `shell_environment_policy.set`, without changing network defaults (see the
[configuration reference](https://developers.openai.com/codex/config-reference/)).
The adapter normalizes a nullable `owner_question` from providers' strict schemas
to the order's conditional field, then the loop validates the result strictly.

Claude uses confined file tools, disables customizations/MCP, and enables the
builder Bash sandbox with `failIfUnavailable=true` and
`allowUnsandboxedCommands=false`, following the
[official sandbox documentation](https://code.claude.com/docs/en/sandboxing).
It refuses error envelopes and permission denials, including errors with a zero
process exit code. JSON is read from stdout separately from stderr diagnostics.
Claude and Pi reviewers have read-only tool allowlists without a general shell;
easy-ref runs independent checks itself. No adapter enables sandbox network
access. Builders edit without committing; easy-ref stages and commits outside
the harness, with Git hooks disabled. A host commit failure stops for the owner;
it never retries with wider harness permissions. Older versions missing any
required option are refused rather than given weaker settings.

Pi remains unsandboxed even with its read-only reviewer tools: opt-in is required
for either role and is recorded in the run summary. Harness changes may require
new compatibility verification; fake executable tests prove invocation and
parsing, not real-model behavior or OS sandbox enforcement.


## Reviewer-reported smoke run

The gatekeeper ran a real smoke test using a throwaway repository under the home
directory, a tiny function-and-unittest order, Codex as builder, Claude Code as
reviewer, and `python3.11 -m unittest` as the check. Building, host committing and
checks succeeded, but Claude Code 2.1.302 rejected `--mcp-config '{}'` because it
requires a `mcpServers` map. The adapter now passes
`json.dumps({"mcpServers": {}})`. The gatekeeper reported rerunning the identical
reviewer command with that value corrected: it exited 0 with a structured
`APPROVE`, no permission denials, and no worktree changes. This is the reviewer's
smoke result, not a new real-model run by this implementation agent. No transcript
is stored in tracked files.
