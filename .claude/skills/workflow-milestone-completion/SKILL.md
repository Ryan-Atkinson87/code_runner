---
name: workflow-milestone-completion
description: What to do when all issues in a milestone are closed. Use this skill when the last issue in a milestone is merged and closed. Orchestrator only.
---

A milestone is not complete when the last issue closes. It is complete when QA passes and the Social Media Context page reflects reality. Work through these steps before closing the milestone on GitHub.

## Step 1: Verify all issues are closed

```
gh issue list --repo Ryan-Atkinson87/code_runner --milestone "<milestone name>" --state open --json number,title
```

Confirm this returns empty. If any issue is still open, the milestone is not yet ready — return to `process-implement-milestone` (implementor) or `process-review-pr` (orchestrator) to finish it.

Confirm no issue was closed as `wont-fix`/`duplicate` without a replacement issue created and assigned to this or a later milestone.

## Step 2: Run QA

Apply `workflow-qa` for the milestone scope. Do not proceed until QA passes (no `critical` bugs outstanding).

## Step 3: Run accessibility and responsiveness checks

If the milestone includes any `orchestrator-ui` changes:
- Apply `workflow-accessibility-testing`
- Apply `workflow-responsiveness-testing`

Any `critical` findings block milestone completion. `Major` findings should be fixed; if not, create follow-up issues in the next milestone and document the decision. `Minor` findings go to the next milestone automatically.

## Step 4: Update the Social Media Context page (mandatory)

Apply `workflow-notion-sync` at the milestone level. This updates the **📣 Social Media Context** Notion page — Current Status, Recent Milestones, What's Coming Next — per Spec §5.4 step 6, idempotently. Do not skip this step.

## Step 5: Note Open Items resolved

Read Specification §15 (Open items to resolve). For any item resolved by this milestone's work, note the resolution as a comment on the relevant issue or PR — do not edit the Specification page itself. If the resolution is notable, mention it in the Social Media Context update in Step 4.

If new open items were discovered during the milestone and are blocking, apply `workflow-blocker-escalation`. If non-blocking, create a backlog issue for a later milestone.

## Step 6: Confirm dependent issues are unblocked

Check whether any open issues in this repo declared `Depends on: #N` against an issue closed in this milestone. Remove their `blocked` label if present — `workflow-phase-issues` will pick them up automatically in the next milestone. No board to update.

## Step 7: Close the milestone on GitHub

```
gh api repos/Ryan-Atkinson87/code_runner/milestones \
  | jq '.[] | select(.title == "<milestone name>") | {number: .number, title: .title, state: .state}'

gh api repos/Ryan-Atkinson87/code_runner/milestones/<number> -X PATCH -f state=closed

gh api repos/Ryan-Atkinson87/code_runner/milestones/<number> | jq '{title: .title, state: .state}'
```

## Step 8: Output a milestone summary

- Milestone name
- Total issues closed
- QA findings: how many bugs raised, how many resolved before completion, how many deferred
- Accessibility findings summary (if applicable)
- Responsiveness findings summary (if applicable)
- Open Items resolved (Step 5)
- Dependent issues unblocked for the next milestone (Step 6)
