# easy-ref

A referee for local builder/reviewer agent loops. Give it a work order: easy-ref
creates a separate Git worktree, asks the builder for edits, commits them, runs your
checks independently, and obtains a strict review verdict. It repeats until the
work is approved, a stop condition is reached, or an owner decision is needed.

Requires **Python 3.11+**, Git, and authenticated CLI installations for your chosen
harnesses. The implementation uses only Python's standard library. Supported
platforms are macOS and Unix systems with `fcntl` locks/process groups. The
macOS notifier falls back to terminal output elsewhere.

## Run it

From this checkout, use `./easy-ref` or `python3 -m easy_ref`. To use the command
from other directories, put the checkout on your PATH. No package installation
or third-party Python dependency is required.

```sh
python3 --version
./easy-ref run ../target/work-orders/task.md --repo ../target \
  --builder codex --reviewer claude
./easy-ref status --repo ../target
./easy-ref status RUN_ID --repo ../target
./easy-ref answer RUN_ID "Use the documented behavior" --repo ../target
./easy-ref stop RUN_ID --repo ../target
```

`run` and `answer` execute in the foreground. An owner wait persists to disk and
returns to the terminal; it does not leave an agent process running. `answer`
starts a new call with the saved context. A reviewer question resumes review
with fresh checks, while other owner decisions go to the next builder prompt.
Completed/stopped runs cannot resume, and exhausted builder round limits require
a new run. The existing branch is kept: use a new order slug for a new run.

A successful run returns exit code 0; owner intervention or an input error returns
2; an owner-stopped worker returns 130. `status`/`stop` return 0 when successful.
Status shows saved state, branch, worktree, round count, check exit codes, and any
owner question. Status also detects an interrupted worker using its run lock and
marks it `NEEDS_OWNER`; it does not infer success. `stop` immediately ends an idle
run or requests process-group termination from an active worker.

## Configuration

Place optional `easy-ref.toml` in the **target owner's checkout**. Configuration
is trusted owner input. It is loaded once and frozen in `run.json`; builder edits
to the worktree's config are reported but never change checks for that run.

```toml
builder = "codex"
reviewer = "claude"
# builder_model = "your-codex-model"
# reviewer_model = "your-claude-model"
checks = [["python3", "-m", "unittest"]]
check_sandbox = "auto"  # auto, codex, none
round_limit = 3
timeout = 1800
# builder_timeout = 1800
# reviewer_timeout = 1800
# check_timeout = 1800
notifier = "auto"  # auto, macos, terminal
# worktree_root = "../target-agents"
```

Checks are argument arrays, executed without a shell in the agent worktree.
For pipelines or other shell constructs, explicitly configure a shell invocation;
its script is trusted input too. A nonzero check result counts as a round, skips
review, and feeds the captured output to the next builder. Crashes/timeouts of
agents, or check execution errors/timeouts, stop for the owner. There are no
checks by default, and easy-ref warns that nothing independent was verified.
Its own `easy-ref.toml` runs `python3 -m unittest`.

CLI overrides: `--builder`, `--reviewer`, `--builder-model`, `--reviewer-model`,
`--round-limit`, `--timeout`, `--builder-timeout`, `--reviewer-timeout`,
`--check-timeout`, `--check-sandbox`, `--worktree-root`, `--notifier`. Repeat `--check 'command args'`
to replace the file's checks; quoting splits arguments but does not enable a shell.
Unknown config fields, invalid values, and unknown adapters are refused.

Pi has **no sandbox**. Selecting it for either role requires the explicit
`--allow-unsandboxed` flag on `run`; this decision is frozen for resumes and is
shown in prompts and the stop summary. For example:

```sh
./easy-ref run ../target/work-orders/task.md --repo ../target \
  --builder pi --reviewer claude --allow-unsandboxed
```

## Owner-supplied skills

Attach skills to either role in the owner's `easy-ref.toml`. For a sibling
checkout named `skills`:

```toml
builder_skills = ["../skills/regression-testing"]
reviewer_skills = ["../skills/spec-review"]
```

Or pass repeatable flags on `run`:

```sh
./easy-ref run ../target/work-orders/task.md --repo ../target \
  --builder-skill ../skills/regression-testing \
  --reviewer-skill ../skills/spec-review
```

Paths resolve against the owner's checkout, including paths passed on the CLI.
Flags replace the configured list for that role; an omitted flag preserves it.
Both lists default to empty, leaving the role's prompt unchanged.

Skill text is **trusted owner input** and becomes part of the role's prompt.
Each directory must contain `SKILL.md` with `---` frontmatter and a `name:`
matching the directory name (a plain or quoted scalar). easy-ref copies that file
and all direct `references/*.md` files in sorted order; it reads no other skill
files. Selected files must be regular UTF-8 files. Symlinks in selected paths,
duplicate names within a role, and more than 128 KiB of total UTF-8 text per role
are refused. The same skill may be used by both roles.

At run creation, text is frozen under `skills/<role>/<name>/` in the private run
directory. `run.json` records names, file lists, and SHA-256 digests. A skill's
digest covers the sorted filename-to-file-SHA-256 mapping encoded as compact JSON.
Every round and resume reads and verifies the frozen files, never the sources;
source edits require a new run. Missing or changed frozen files stop the loop.
`status` and stop summaries show each role's names and digests.

The prompt labels each file and places a precedence instruction before the skill
text: easy-ref rules, the work order, and the required output format take
precedence. Reviewers still return the required verdict JSON.

## Safety and limitations

Agent work happens on `ref/<order-slug>` from the target's starting HEAD, in
`<repo-parent>/<repo-name>.easy-ref/<run-id>/` by default. A configured root must
remain outside the target checkout and Git directories. Existing branches or
worktree paths are refused, and only one unfinished run per target checkout is
allowed. The owner's tracked checkout is never the agent's working directory.

The builder edits files and must not commit. easy-ref stages all non-ignored
changes with `git add -A` and commits them outside the harness sandbox before
checks/review. The first line of the hand-back supplies the commit subject when
it is nonempty, printable, and at most 72 characters; otherwise easy-ref uses
`easy-ref: <order-slug> round <n>`. Any builder-created commits are kept if they
descend from the round's starting HEAD, and easy-ref commits leftover edits.
No changes and no builder commits stops for the owner. The worktree must be clean
after the commit, ignoring ignored files; a failed commit or dirty assertion
stops for the owner. Host Git operations disable hooks with
`-c core.hooksPath=/dev/null`, and commits also use `--no-verify`, so a
builder-written tracked hook cannot execute during these operations. Reviewer
changes to tracked/non-ignored files, the index,
or HEAD stop for the owner. Changed ignored files, such as Python caches, are
reported in summaries and later prompts and do not block approval.

Strict verdict parsing rejects malformed/missing fields, duplicate keys,
conflicting fenced verdict blocks, unsupported values, and approval with failed
checks. Codex and Claude use structured output; Pi uses the last fenced JSON
block. Any required finding repeated with the exact same `what` text stops the
loop; reworded repeats are bounded by the round limit (default 3).

There is no runtime operation for pushing, opening PRs, merging, deploying, or
deleting branches. Every agent/check process gets environment-only Git config
that resets each named remote's push URLs to an invalid URL. Remote-tracking refs
are compared around every agent/check invocation, even on failure. A change
stops for the owner and records before/after refs.

These publishing guardrails are **best-effort, not isolation**:

- An agent can bypass the named-remote block with `git push <url>`. That may not
  move local remote-tracking refs, so the ref monitor does not reliably detect it.
- `git fetch` can move remote-tracking refs and therefore stops the run, even
  though it did not publish anything. Avoid fetching during an active run.
- New remotes, altered environment/config, commands that restore original refs
  or files, hooks, and arbitrary trusted check scripts can evade snapshot checks.
- Ignored files never reach the branch and are tolerated, but may still affect
  subsequent checks. Review the ignored-path report before relying on a run.
- easy-ref commits outside the harness sandbox so builders do not need write
  access to Git metadata. It never widens harness permissions or enables sandbox
  network access to make a commit succeed.

Codex uses workspace-write/read-only sandboxes. Claude confines file tools and
requires a sandbox for builder shell commands, with unsandboxed fallback disabled.
Claude and Pi reviewers have read-only tool allowlists without a general shell;
independent configured checks run through easy-ref. Checks run in the Codex
`:workspace` sandbox when available on macOS. This profile blocks writes outside
the worktree and temporary directories, and blocks `.git` writes. It is not
network or OS isolation beyond that profile; easy-ref adds no writable roots and
does not enable network access.

`check_sandbox = "auto"` (the default) verifies `codex sandbox --help` at run
creation. If macOS, Codex, or the required options are unavailable, checks run
unsandboxed and a warning is recorded. `codex` requires those prerequisites and
refuses run creation otherwise; `none` explicitly runs unsandboxed with a warning.
The resolved mode and executable are frozen in `run.json` across resumes and
shown in status, stop summaries, and the reviewer's check section. Neither help
verification nor fake tests prove that the native sandbox can start on a host;
a sandbox execution failure stops the run with `NEEDS_OWNER`, without fallback.

A small trusted Python launcher runs inside the sandbox without a shell. It
starts the check argument array and reports its exit code separately from Codex's
exit code. A missing completion receipt or failed sandbox process stops for the
owner; an ordinary nonzero check exit still feeds the builder. The launcher uses
Python isolated mode, DEVNULL input, and the same process group as Codex for
cleanup. Push-block variables are supplied explicitly using
`shell_environment_policy.set`, even if Codex filters inherited variables.

Choosing `none` or falling back restores the risk of executing builder-written
code with the owner's permissions. For example, `python -m unittest` executes
whatever tests the builder wrote. Treat check commands as trusted configuration
and the code they execute as untrusted.
Harnesses still need normal service authentication/networking. See the [verified adapter flags and versions](docs/adapter-verification.md).
There has been no real-model validation; tests use fake adapters/executables.

## Records and cleanup

Private records live at `<git-dir>/easy-ref/runs/<run-id>/`: the original order,
versioned `run.json`, owner decisions, stop summary, and per-round/per-attempt
prompts, logs, hand-backs, check results and verdicts. Resumed review attempts
preserve earlier records. Logs may contain sensitive data and are never copied
into tracked files automatically. If the target has `work-orders/`, required
reviews generate portable fix orders there, which easy-ref commits with the
builder's fix. Raw review logs remain private.

Every stop writes a summary with reason, rounds, branch, worktree location,
check results, question, config changes, ignored paths, and any remote-ref movement.
The notifier prints it and optionally invokes macOS `osascript`. Runtime record
directories are created private to the user. Do not commit or share raw runtime
records or credentials.

No worktree or branch is deleted automatically. The summary supplies a manual
`git worktree remove` command. Inspect and preserve anything needed before using
it; remove private run records yourself only after you no longer need them.

## Development and review

```sh
python3 -m unittest
```

Tests use temporary Git repositories, scripted fake adapters, fake CLI processes,
and local Python/Git check commands. The push-block regression test attempts a
blocked push only to an isolated temporary local bare remote. It never publishes
the project or calls a real model. See [test coverage](docs/test-coverage.md).

The [v1 work order](work-orders/2026-10-21-v1-loop.md) remains open pending final
review. The [checkpoint review](work-orders/2026-10-21-v1-loop-checkpoint-review.md)
is addressed by its designated fix commit. Historical work orders are records,
not instructions to act on.

Every review saves the complete binary-capable patch as `full.diff` in its private
round attempt directory. Diffs up to 64 KB are inlined; larger diffs are supplied
as an absolute file path alongside a stat summary. Shell-free reviewers can read
the file; Claude receives read access to that attempt directory.

Follow-ups: stronger OS/network isolation, semantic repeated-finding detection,
and broader platform support. Parallel orders, publishing/PR/merge workflows,
CI integration, a web UI, and cost/budget tracking are outside v1.
