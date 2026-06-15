---
name: workflow-phase-issues
description: Read live issue state for the current milestone and select the next issue to work on, in dependency order. Use at the start of process-implement-milestone, and whenever resuming work after a session boundary. Implementor agents only.
---

This repo has no GitHub Project board (see `CLAUDE.md`). Status is derived directly from issue
state, labels, branches, and PRs — there is no board column to read or write. `docs/BUILD_PLAN.md`
has the full issue checklist for this milestone as a quick reference, but it is not authoritative
for in-progress state — always re-derive status from the live GitHub state below.

## Step 1: List issues in the current milestone

```
gh issue list --repo Ryan-Atkinson87/code_runner --milestone "<milestone>" --state all \
  --json number,title,state,labels,body
```

Closed issues are `Done`. Ignore them. Everything below applies to open issues.

## Step 2: Classify each open issue

For each open issue, check in this order:

1. **`blocked` label** → `Blocked`. Skip, unless the blocker noted on the issue (via
   `workflow-blocker-escalation`) has since been resolved — if so, remove the label before
   continuing.

2. **An open PR references this issue** (`gh pr list --search "#<N> in:body" --state open`) →
   `In Review`. Skip — this is waiting on the orchestrator.

3. **A local branch `issue-<N>-*` exists** with commits ahead of `main` but no open PR →
   started but not finished. Per Spec §18.4, a half-written AI session is discarded, not
   resumed: delete this branch (`git branch -D issue-<N>-*`) and treat the issue as not started.

4. Otherwise → **not started**.

## Step 3: Order remaining "not started" issues by dependency

Read every `Depends on: #N` line in each issue body. An issue is **unblocked** if every issue it
depends on is `Done` (closed). Among unblocked issues, order by issue number (creation order) as
the tiebreaker — this matches the sequencing notes added during planning
(`workflow-project-planning` Step 5: Sequence the issues).

## Step 4: Select

- If at least one unblocked, not-started issue exists → pick the first one (lowest issue
  number). This is the current issue — continue to Step 3 of `process-implement-milestone`.
- If no issues remain in any state (all `Done`) → the milestone is complete. Notify the
  orchestrator to run `process-close-milestone`.
- If remaining issues are only `Blocked` and/or `In Review` → nothing is available to start.
  Report which issues are blocked and why (from the `blocked`-label comment), and which are
  awaiting review. Stop — do not invent work outside the milestone scope.

## Step 5: Mid-milestone discoveries

If implementation on the current issue reveals work that isn't covered by any issue in this
milestone:

- **Small, within the current issue's scope** — include it in this issue's PR and note it in
  the PR description (`workflow-pr-creation` Section 0). Do not open a separate issue for it.
- **Distinct piece of work** — stop, create a new GitHub issue in this repo with acceptance
  criteria and any `Depends on: #N` declarations, assign it to this milestone (or the next one
  if it isn't blocking), and add a row for it under the relevant phase in `docs/BUILD_PLAN.md`.
  Mention it in this session's output so the orchestrator is aware. Then continue the current
  issue — the new issue will be picked up in dependency order on a future pass through Steps 1–4.

Never silently expand the scope of the current issue to absorb discovered work without
documenting it one of these two ways.
