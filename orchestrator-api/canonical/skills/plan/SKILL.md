---
id: plan
stage: plan
executor: ai
applies_to: neutral
specialities: []
description: Decompose a wave/milestone into dependency-ordered issues with clear acceptance criteria.
---

Decompose the wave into issues small enough that one fresh session can finish each in a single
sitting. Each issue needs:

- A problem statement grounded in the project's specification or the human's request — never an
  invented requirement.
- Acceptance criteria written as a checklist, specific enough that an implementor session with no
  memory of this planning session can verify its own work against it.
- Explicit `Depends on: #N` declarations for any issue that reads or relies on another issue's
  output. Order issues so dependencies are created first.

Do not plan implementation detail — that is the implementor's judgement call, made with the code
in front of it. Do not create issues for work the deterministic engine already does (sequencing,
git operations, test/lint gating, PR mechanics, tracker sync) — planning covers judgement work
only.

If the wave's scope is ambiguous or the request conflicts with the existing specification, stop
and flag it rather than guessing — an ambiguous plan produces issues nobody can implement against.
