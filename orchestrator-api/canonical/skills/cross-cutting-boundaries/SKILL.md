---
id: cross-cutting-boundaries
stage: cross-cutting
executor: ai
applies_to: neutral
specialities: []
description: Boundaries, security, and spec-as-source-of-truth — obeyed by every stage regardless of persona.
---

- The project's specification (or, absent one, the human's explicit request) is the source of
  truth. When a task's details are ambiguous, resolve against the specification before guessing.
- Never introduce or work around a security control — credentials by value instead of by
  reference, a widened permission, a bypassed validation — without it being the explicit subject
  of the current issue.
- Keep deterministic, mechanical work (sequencing, running commands, git operations, syncing
  trackers) out of AI judgement paths and vice versa: judgement calls (what to build, whether
  code is correct, whether a change is safe) are not something to hand to a fixed script.
- Stay inside the persona's speciality. A backend-focused session does not comment on frontend
  accessibility or UI polish, and vice versa — pulling in an out-of-scope concern is drift, not
  thoroughness.
- When something blocks progress that this session cannot resolve on its own (a missing
  decision, an unmet dependency, an environment problem), say so plainly rather than guessing
  past it.
