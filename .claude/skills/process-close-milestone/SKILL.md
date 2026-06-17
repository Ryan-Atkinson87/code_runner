---
name: process-close-milestone
description: End-to-end process for closing a milestone after all its issues are closed. Covers QA, accessibility, responsiveness, the Social Media Context sync, and unblocking the next milestone. Orchestrator only. Run this when every issue in a milestone is closed.
---

Run this process when every issue in a milestone has been merged and closed (each PR closed its issue directly via `Closes #N`). Do not mark a milestone complete without working through these steps.

## Step 1: Confirm every issue is closed

```
gh issue list --repo Ryan-Atkinson87/code_runner --milestone "<milestone name>" --state open --json number,title
```

This should return empty — every issue closes on PR merge in this project's GitHub flow. If anything is still open, the milestone isn't ready yet; wait for `process-review-pr` to finish it.

## Step 2: Close out the milestone

Apply `workflow-milestone-completion`. This will cascade into:
- `workflow-deployment-verification` — confirms the local Docker Compose stack is healthy on the latest `main` before QA begins
- `workflow-qa` — end-to-end testing of every area changed in this milestone
- `workflow-accessibility-testing` and `workflow-responsiveness-testing` — if the milestone includes any `orchestrator-ui` changes
- The mandatory Social Media Context update

`workflow-milestone-completion` will surface any critical bugs that block completion. If critical bugs are found, assign them to the implementor, wait for fixes, then restart this process from Step 1.

## Step 3: Update the build plan

Open `docs/BUILD_PLAN.md`.

- Confirm every issue under this milestone's "Issues" heading is checked off (`- [x]`) — if any
  remain unchecked, this milestone isn't actually done; return to Step 1
- In the phases table, change this milestone's status from `⬜` (or `🔄`) to `✅`
- If the next milestone's dependencies are now all `✅`, move its status from `⬜` to `🔄`

Save the file. This is the single source of truth for build progress.

## Step 4: Close the GitHub milestone

GitHub does not close milestones automatically — `workflow-milestone-completion` Step 7 covers this. Confirm it shows as `closed`:

```
gh api repos/Ryan-Atkinson87/code_runner/milestones/<number> | jq '{title: .title, state: .state}'
```

## Step 5: Unblock the next milestone's issues

Confirm `workflow-milestone-completion` Step 6 ran — any issue that declared `Depends on: #N` against an issue in this milestone should have its `blocked` label removed. Notify the backend and/or frontend implementor agents that they can start `process-implement-milestone` for the next milestone.

## Step 6: Write the dev diary entry

Append an entry to `docs/CLAUDE_DEV_DIARY.md` for the milestone that just closed. This is a human-readable narrative — not a changelog or bullet dump. Structure it as:

```markdown
## Milestone N: <milestone name> — <date completed (YYYY-MM-DD)>

### What was done

Plain-language summary of the work completed in this milestone. Describe the features, infrastructure, or capabilities that were built — not individual commits or PRs. A reader who has never seen the codebase should understand what exists now that didn't before.

### Why it was done

The motivation behind this milestone: what problem it solves, what it unblocks, or what spec requirement it satisfies. Reference the relevant Spec sections where useful (e.g. "per Spec §3").

### Effect on the project

How the project is different after this milestone. What can the system do now? What is unblocked for future milestones? Any notable architectural decisions or trade-offs that were made.
```

Guidelines:
- Write in past tense, third person ("The engine gained…", "This milestone introduced…").
- Keep each section to 1–3 short paragraphs. Aim for ~200–400 words total per entry.
- Do not list every issue or PR — summarise the work thematically.
- If this is the first entry, add a top-level heading `# Code Runner — Dev Diary` before the milestone entry.
- If entries already exist, append the new entry at the end of the file.

## Step 7: Plan the next milestone (if not already planned)

If the next milestone has not been planned yet, run `process-plan-milestone` now.
