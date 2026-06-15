---
name: workflow-testing
description: How to run the test suite, interpret failures, and feed results back to the issue. Use this skill after completing implementation on any issue, before raising a PR, and after resolving feedback comments. Implementor agents only (backend, frontend).
---

No PR opens with a failing test.

## Step 1: Run the test suite for the area(s) you changed

**Backend** (`<BACKEND_PATH>`)
```
<BACKEND_TEST_CMD>
```

**Frontend** (`<FRONTEND_PATH>`)
```
<FRONTEND_TEST_CMD>
```

Commands are defined in `CLAUDE.md`. If a change touches shared code — `docs/api.md`, config schemas, or anything both areas depend on — run both suites. If a command is still a placeholder because the tooling hasn't been chosen yet, note that in the PR rather than silently skipping; once filled in, the gate is mandatory.

## Step 2: Interpret results

**All tests pass:** proceed to `workflow-pr-creation`.

**Tests fail:** classify each failure before doing anything:

| Failure type | Definition |
|---|---|
| `caused-by-change` | Test was passing before your change and is now failing because of it |
| `pre-existing` | Test was already failing before your change (confirm by checking out `main` and running the test) |
| `test-is-wrong` | The test is asserting incorrect behaviour that conflicts with the Specification |

**Do not delete or skip a failing test without classifying it first.**

## Step 3: Fix failures

**`caused-by-change`**
Fix the implementation so the test passes. If fixing breaks the acceptance criteria, the test may need updating, but only if the test is asserting behaviour that conflicts with the Specification. Document the reasoning in the PR.

**`pre-existing`**
Do not fix it as part of this issue unless it is directly related. Comment on the issue noting the pre-existing failure and its test name. Create a separate chore issue to fix it and assign it to the current milestone.

**`test-is-wrong`**
Verify against the Specification that the test is asserting the wrong thing. If confirmed, update the test and document the reason in the PR description. If uncertain, apply `workflow-blocker-escalation`.

## Step 4: Write missing tests

If the implementation adds new logic that has no test coverage:
- Write unit tests for any non-trivial function or service method
- Write component tests for any new UI component covering: renders correctly, primary interaction, error state
- Write or update API mocks if new endpoints are introduced (`workflow-api-contract-verification`)
- Do not aim for 100% coverage, aim for the acceptance criteria paths to be fully covered

## Step 5: Feed failures back to the issue

If tests are still failing after Step 3 and cannot be resolved without a decision:

Post a comment on the GitHub issue:

```
## Test failures

**Suite:** [unit / component / e2e]
**Test name:** [exact test name from output]
**Failure message:**
[paste the exact assertion failure]

**Reproduction:**
[exact command to reproduce]

**Classification:** [caused-by-change / pre-existing / test-is-wrong]

**Blocker:** [what decision or change is needed to resolve]
```

Add the `blocked` label. Apply `workflow-blocker-escalation`.

## Step 6: Confirm pass before PR

Run the full suite one final time after all fixes. Confirm all tests pass before opening the PR. This is not optional.
