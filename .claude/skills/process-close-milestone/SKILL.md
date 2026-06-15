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

## Step 6: Plan the next milestone (if not already planned)

If the next milestone has not been planned yet, run `process-plan-milestone` now.
