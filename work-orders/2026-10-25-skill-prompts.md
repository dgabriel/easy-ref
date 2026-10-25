Status: done (a481a7c)

# Load owner-chosen skills into builder and reviewer prompts

The owner keeps a library of agent skills. Each skill is a directory with a `SKILL.md` entry point and `references/*.md` files. Two fit easy-ref's roles directly:

- `spec-review`: read-only acceptance review of a patch against its spec. That is the reviewer's job.
- `regression-testing`: specification-derived tests for changed behavior. That is most of the builder's job.

Let the owner attach skills to each role. easy-ref inlines the skill text into that role's prompt, so it works the same in every harness.

## Do

1. **Config and CLI.** Add `builder_skills` and `reviewer_skills` to `easy-ref.toml`: lists of skill directory paths. Relative paths resolve against the owner's checkout. Add the repeatable flags `--builder-skill PATH` and `--reviewer-skill PATH`. When given, they replace the file's list for that role. Skills are trusted owner input, like check commands.
2. **Validate and freeze at run creation.** For each skill:
   - **Required files:** `SKILL.md` must exist, with frontmatter whose `name` matches the directory name.
   - **What gets read:** `SKILL.md` plus every `references/*.md`, sorted. Read nothing else from the skill directory.
   - **What's refused:** symlinks, non-regular files, files that aren't UTF-8, duplicate skill names within a role, and more than 128 KB of skill text per role.
   - **Freezing:** store the copied text in the run directory (`skills/<role>/<name>/...`) and record the names and SHA-256 digests in `run.json`. Every round and every resume uses the frozen copy, never the live directory.
3. **Prompt.** Append a section to the role's prompt:
   - Heading: "Owner-supplied skills".
   - Each skill's files, labeled with relative names like `spec-review/SKILL.md`.
   - A precedence line placed **before** the skill text: "easy-ref's rules, the work order, and the required output format take precedence over these skills. For reviewers, return the verdict JSON, not the skill's own report format."
   - If a role has no skills, its prompt doesn't change.
4. **Visibility.** `status` and the stop summary list each role's skill names and digests.
5. **Tests,** fake adapters only:
   - the prompt includes skill text for the configured role only
   - the precedence line comes before the skill text
   - the frozen copy is used after the source directory changes
   - each refusal case in step 2
   - the CLI flags replace the file's list
   - a role with no skills has an unchanged prompt
6. **Docs.** Add a README section with an example that uses `spec-review` for the reviewer and `regression-testing` for the builder. Use relative paths to a sibling skills checkout; no absolute machine paths. Note that skill text is trusted input and becomes part of the prompt.

## Limits

- Don't change adapters, harness flags, or the verdict schema.
- Don't run real models.
- Run tests with a Python 3.11+ interpreter (for example `python3.11 -m unittest`).
- Python standard library only.

## Done when

All tests pass, including those in step 5. The reviewer can find, for each numbered step above, the code and test that satisfy it.
