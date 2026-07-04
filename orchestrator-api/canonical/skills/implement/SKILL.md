---
id: implement
stage: implement
executor: ai
applies_to: neutral
specialities: []
description: Write code against an issue's acceptance criteria, including its own tests.
---

Work against the acceptance criteria in the issue body, not against assumptions about what the
project "probably" wants. If a detail isn't in the criteria, check the project's specification
before inventing one.

- Write the tests the change needs as part of implementing it — a change without test coverage
  is not done.
- Match the existing codebase's patterns and conventions rather than introducing a new one for a
  single issue.
- Implement only what the issue asks for. If you discover adjacent work while implementing, do
  not fold it in silently — surface it so it can be tracked as its own issue.
- Prefer the smallest correct change. No speculative abstraction, no unused configuration, no
  code paths that exist for a future that isn't this issue.
- Leave the repository in a state where the deterministic test/lint/typecheck gate can run
  immediately after — do not hand back partially-working code expecting the gate to catch it.
