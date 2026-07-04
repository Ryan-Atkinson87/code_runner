---
id: review
stage: review
executor: ai
applies_to: neutral
specialities: []
description: Judge an implementor's PR against the issue's acceptance criteria and the project's boundaries.
---

Review is a spec-compliance check, a boundary check, and a quality check — not a style
preference pass unless style affects correctness or maintainability.

- Read the linked issue and every acceptance criterion before reading the diff. Confirm each one
  is actually met, not "close enough".
- Check the diff against the project's specification for anything the issue's criteria didn't
  cover explicitly.
- Confirm the change respects this project's architectural boundaries (e.g. deterministic logic
  staying deterministic, provider- or framework-specific code staying behind its designated
  abstraction) — a correct-looking change that leaks across a boundary is still a defect.
- Confirm test coverage exists for the behaviour the issue describes, not just that existing
  tests still pass.
- If changes are needed, leave specific, actionable comments tied to a file and line — enough
  for a fresh implementor session with no memory of this review to act on without asking for
  clarification.
- Approve only when every acceptance criterion and boundary check passes. Do not approve
  conditionally on trust that a small fix will follow.
