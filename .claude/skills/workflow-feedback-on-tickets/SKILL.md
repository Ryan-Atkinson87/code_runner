---
name: workflow-feedback-on-tickets
description: Triage every review comment on a PR or issue into an action plan before any fixes are implemented. Use as the first step of process-handle-feedback, or any time review feedback needs to be worked through systematically. Implementor agents only.
---

Reacting to comments one at a time, in the order they arrive, risks acting on a comment that a
later comment supersedes. Classify everything first, then act.

## Step 1: Collect all comments

```
gh pr view <PR> --comments
gh api repos/Ryan-Atkinson87/code_runner/pulls/<PR>/reviews
gh api repos/Ryan-Atkinson87/code_runner/pulls/<PR>/comments
gh issue view <issue> --comments
```

Gather everything since the PR was opened or last re-requested for review — not just the most
recent review.

## Step 2: Classify each comment

| Category | Definition |
|---|---|
| `bug` | Points out behaviour that doesn't meet the acceptance criteria or the Specification |
| `change-request` | Asks for a different approach within scope — not a bug, but not optional |
| `question` | Needs an answer, not a code change |
| `wont-fix` | Out of scope, already covered elsewhere, or a deliberate trade-off — needs a reasoned reply |
| `already-resolved` | A later commit or comment already addresses this |

## Step 3: Sequence and de-duplicate

Read comments in chronological order. If a later comment changes or withdraws an earlier
request, mark the earlier one `already-resolved` and note why. Group comments that point at the
same underlying issue so they're fixed once, not repeatedly.

## Step 4: Produce the action plan

For each remaining comment, write one line: category, file/line if applicable, and the planned
action (`bug`/`change-request` → what will change; `question` → the answer; `wont-fix` → the
reason and whether it needs orchestrator sign-off; `already-resolved` → which commit/comment
resolves it).

Do not start implementing until this plan covers every comment. `process-handle-feedback` Step 2
works through this plan in order.

## Step 5: Resolution summary template

Once fixes are implemented (`process-handle-feedback` Steps 2–4), post this on the PR:

```markdown
## Feedback resolution

- [comment summary] → [fixed in <commit/file> / replied above / already resolved by <ref> / wont-fix: <reason>]
- ...
```
