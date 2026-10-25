Status: done (4efe17e)

# Restate the output contract after owner-supplied skills

`loop.prompt` appends the "Owner-supplied skills" section at the very end of each prompt. For reviewers, the last text the model reads is now the skill's own instructions. `spec-review`, for example, asks for a PASS/FAIL report. Claude and Codex are held to the verdict JSON by structured output, but Pi parses free text, and no reviewer is reminded of the required format after reading the skill.

## Do

1. **Close with the output contract.** When a role has skills, end its prompt with a short closing line after the skill section that restates the role's output contract:
   - **Reviewer:** return only the strict verdict JSON (verdict, summary, required with id/what/evidence, owner_question only for NEEDS_OWNER), not the skill's report format.
   - **Builder:** don't commit; start the hand-back with a one-line commit subject of 72 characters or fewer.
2. **Leave other prompts alone.** A role with no skills gets a byte-for-byte unchanged prompt.
3. **Tests:**
   - with skills, the closing line is the last non-empty line of the prompt and comes after the skill text, for each role
   - without skills, the prompt is unchanged
   - the precedence line still comes before the skill text

## Limits

- Change only `easy_ref/loop.py`, `easy_ref/skills.py` if needed, and tests.
- Don't change adapters, the verdict schema, or docs.
- Run tests with a Python 3.11+ interpreter (for example `python3.11 -m unittest`).
