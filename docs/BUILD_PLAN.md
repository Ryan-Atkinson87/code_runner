# Build Plan

Code Runner's local equivalent of a GitHub Project board — this repo doesn't use one (see
"GitHub conventions" in `CLAUDE.md`). This file is the single source of truth for build
progress and has two parts:

1. A **phase table** tracking the Spec §14 build phases through `⬜` → `🔄` → `✅`.
2. A **per-phase issue checklist** — every issue created for that milestone, in the order
   they'll be worked, checked off when its PR merges and the issue closes.

## Keeping this file current

| When | Who | What |
|---|---|---|
| A phase is about to be planned | Orchestrator (`process-plan-milestone` Step 1) | Confirm the phase's dependencies are `✅` and the phase table still matches reality |
| A new issue is created for a milestone | Orchestrator (`workflow-project-planning` Steps 4-6) | Add `- [ ] #N — Title` under that phase's "Issues" heading, in dependency order |
| A PR merges and closes an issue | Orchestrator (`workflow-code-review` Step 9) | Check off the corresponding row |
| A milestone closes | Orchestrator (`process-close-milestone` Step 3) | Set the phase's status to `✅`; if the next phase's dependencies are now all `✅`, set its status to `🔄` |

## Status legend

| Symbol | Meaning |
|---|---|
| ⬜ | Not started — a dependency isn't `✅` yet |
| 🔄 | Ready / in progress — dependencies met, milestone planned or being implemented |
| ✅ | Complete — milestone closed |

## Phases (Spec §14)

| # | Phase | Status | Depends on |
|---|---|---|---|
| 1 | Foundations | 🔄 | — |
| 2 | Git/PR engine | ⬜ | 1 |
| 3 | Claude adapter + wave loop | ⬜ | 1, 2 |
| 4 | Usage monitor | ⬜ | 3 |
| 5 | Trackers + notifications | ⬜ | 3 |
| 6 | Observability + UI | ⬜ | 3, 4, 5 |
| 7 | Multi-provider | ⬜ | 3 |

---

## 1. Foundations

Container + egress proxy + filesystem binding; FastAPI skeleton + auth; SQLite state; config
schema + `project.yaml` loader.

**Status:** 🔄

### Issues

_Not yet planned — run `process-plan-milestone`._

---

## 2. Git/PR engine

Branch lifecycle (agent branch, feature branches, local-only flow, hand-off push + PR);
test/lint/typecheck gates.

**Status:** ⬜ (depends on Phase 1)

### Issues

_Not yet planned._

---

## 3. Claude adapter + wave loop

Full end-to-end on Trive with one provider. Instruction-file generation. Internal review loop.

**Status:** ⬜ (depends on Phases 1, 2)

### Issues

_Not yet planned._

---

## 4. Usage monitor

Meters, 80%-most-restrictive rule, hard pause/resume, peak-hour throttle, override, Agent SDK
credit handling.

**Status:** ⬜ (depends on Phase 3)

### Issues

_Not yet planned._

---

## 5. Trackers + notifications

GitHub<->Notion sync; Telegram two-way + Resend; blocker escalation.

**Status:** ⬜ (depends on Phase 3)

### Issues

_Not yet planned._

---

## 6. Observability + UI

Langfuse integration, two-layer logging, efficiency reports; React UI wiring it all together.

**Status:** ⬜ (depends on Phases 3, 4, 5)

### Issues

_Not yet planned._

---

## 7. Multi-provider

Codex and Gemini adapters behind the existing interface.

**Status:** ⬜ (depends on Phase 3)

### Issues

_Not yet planned._
