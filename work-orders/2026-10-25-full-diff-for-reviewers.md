Status: done (0a9751d)

# Give reviewers the full diff when it's too large to inline

`prompt()` in `easy_ref/loop.py` inlines the diff since the run's base commit, up to 64 KB. Above that, it sends only `git diff --stat` and says "Inspect the full diff locally." Claude and Pi reviewers have no shell, so they can't run `git diff` and never see the actual changes on a large round.

## Do

1. **Save the full diff each review.** Before every reviewer call, write the complete `git diff <base>` (with `--binary`) to `full.diff` in the round's attempt directory. Above the cap, the reviewer prompt names that absolute path and tells the reviewer to read it, alongside the stat summary. Below the cap, keep inlining as now; still write the file.
2. **Let the Claude reviewer read it.** The round directory lives under the git directory, outside the worktree, and `--restricted` confines Claude's file tools. Pass `--add-dir <round directory>` to the Claude reviewer only. Don't add it for the builder, and don't widen anything else.
3. **Pi and Codex.** Pi's read tool and Codex's read-only sandbox can already read that path. Make no permission changes for them; add a code comment saying so.
4. **Tests,** with fake adapters only:
   - the file is written in both cases, small and over the cap
   - the over-cap prompt names the file
   - the Claude reviewer args include `--add-dir` with the round directory, and the builder args don't
5. **Docs.** Update the README's limitation text about large diffs.

## Limits

- Change nothing else.
- Keep the 64 KB cap.
- Python standard library only.
