---
name: process-handle-feedback
description: End-to-end process for actioning review feedback on a PR or issue. Run this when the orchestrator has requested changes or left comments. Covers triaging comments, implementing fixes, retesting, and re-requesting review. Implementor agents only (backend, frontend).
---

Run this process whenever the orchestrator requests changes on a PR or leaves comments that need actioning. Work through every comment before re-requesting review.

## Step 1: Read and triage all feedback

Apply `workflow-feedback-on-tickets`. This will:
- Walk through every comment on the PR and issue
- Classify each as `bug`, `change-request`, `question`, `wont-fix`, or `already-resolved`
- Produce a plan for actioning each one

Do not start implementing fixes until all comments are classified. An earlier comment may be superseded by a later one.

## Step 2: Implement fixes

Action each comment as directed by `workflow-feedback-on-tickets`:
- `bug` and `change-request`: implement the fix. Verify against the Specification before changing anything — if a requested change conflicts with the spec, apply `workflow-blocker-escalation` rather than guessing.
- `question`: reply directly on the PR.
- `wont-fix`: reply with the reason. Tag the orchestrator if the decision needs sign-off.
- `already-resolved`: reply confirming the resolution.

## Step 3: Retest

After all fixes are implemented, apply `workflow-testing`. Run the full suite for every area touched — not just tests for the files you changed. Confirm everything passes before moving on.

## Step 4: Pre-flight re-check

Before re-requesting review, re-run the `workflow-pr-creation` pre-flight checklist in full — including the scope gate (Section 0), AC verification (Section 2), and validation coverage (Section 3). Feedback fixes can inadvertently introduce scope creep or remove validation; confirm the PR still passes every item.

## Step 5: Re-request review

Once all comments are actioned, tests pass, and the pre-flight checklist is clean:
1. Post the feedback resolution summary comment on the PR (`workflow-feedback-on-tickets` Step 5).
2. Apply `workflow-notion-sync`.
3. Re-request review from the orchestrator.

The orchestrator will run `process-review-pr` again from the beginning.
