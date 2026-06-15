---
name: workflow-blocker-escalation
description: Record and surface a blocker when work cannot proceed without a decision outside the current session's remit — an unmet dependency, a spec ambiguity, a contract conflict, or an environment issue. Use whenever another skill says to apply this. Both orchestrator and implementor agents.
---

A blocker does not stop the milestone. It stops *this issue*. Record it clearly, label it, and
move on to other unblocked work (Spec §9.1).

## Step 1: Classify the blocker

| Type | Definition |
|---|---|
| `dependency` | Another issue this one depends on isn't done, and no adequate stub/interface exists to proceed against |
| `spec-ambiguity` | The Specification (or issue acceptance criteria) doesn't cover a decision needed to proceed |
| `contract-conflict` | The implementation would have to violate a documented contract (`workflow-api-contract-verification`) to satisfy the acceptance criteria as written |
| `environment` | A local environment / config / secret issue outside this session's ability to fix (`workflow-env-verification`) |
| `decision-needed` | A genuine product/architecture choice that the human should make |

## Step 2: Record it on the issue

Post a comment on the GitHub issue:

```markdown
## Blocker

**Type:** [dependency / spec-ambiguity / contract-conflict / environment / decision-needed]
**Blocked on:** [issue #N, Spec §N, or description of the missing input]
**What's blocked:** [what this issue can't do until this is resolved]
**What's needed to unblock:** [the specific decision, merge, or fix required, and who makes it]
```

## Step 3: Label and park

Add the `blocked` label (create it if it doesn't exist — see `CLAUDE.md`). Leave the issue open
and unassigned from active work. Do not delete any branch that has useful exploratory context,
but do not continue building on it either — per Spec §18.4, a fresh session will discard and
restart once unblocked.

## Step 4: Continue other work

Implementor: re-run `workflow-phase-issues` to pick the next unblocked issue in this milestone.
Orchestrator (during planning): do not plan issues for the affected scope — create the blocker
issue first, then plan the rest of the milestone around it (`workflow-project-planning`).

## Step 5: Surface it now, not at milestone end

State the blocker plainly in this session's output to the human — issue link, type, and exactly
what decision is needed. Don't wait for milestone close to mention it. If a hand-off / milestone
summary is being written in this same session (`process-close-milestone`), also list it under
"Parked blockers" there (Spec §5.4).

## Step 6: Resuming

Once the blocking decision is made and recorded (e.g. the dependency issue closes, or the human
replies with a decision — record that reply as a comment on the blocked issue for traceability),
remove the `blocked` label. `workflow-phase-issues` will pick the issue up normally on the next
pass.
