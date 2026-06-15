# Code Runner — Agent Skills

These skills implement the orchestrator/implementor workflow described in `CLAUDE.md`. Claude
Code auto-discovers them from each `SKILL.md`'s frontmatter `description` — there is no
separate wiring step in `CLAUDE.md`. Where one skill calls another, that's stated explicitly in
the calling skill's steps.

One repo, no GitHub Project board, no admin agent, no per-issue Notion tracking (see
`CLAUDE.md`). Roles:

- **Orchestrator** — plans milestones, reviews PRs, runs QA/accessibility/responsiveness checks,
  closes milestones.
- **Implementor (backend)** — Python/FastAPI/Pydantic orchestration engine.
- **Implementor (frontend)** — React/Vite UI.

## Process skills — start here

Five high-level skills cover the full milestone lifecycle. The `workflow-*` skills are called
automatically from within these — you should not need to invoke them manually.

| Skill | Who | When to run |
|---|---|---|
| `process-plan-milestone` | Orchestrator | At the start of every new milestone |
| `process-implement-milestone` | Implementors (backend / frontend) | Start of every session, and when picking up the next issue |
| `process-review-pr` | Orchestrator | When an implementor opens a PR |
| `process-handle-feedback` | Implementors | When the orchestrator requests changes |
| `process-close-milestone` | Orchestrator | When all PRs in a milestone are merged |

### Milestone lifecycle at a glance

```
Orchestrator                          Implementors
──────────────────────────────────    ────────────────────────────────────────
process-plan-milestone
  └─ issues created, sequenced
                                       process-implement-milestone (backend / frontend)
                                         └─ PR opened against main (Closes #N)
process-review-pr (per PR)
  └─ blocking findings?
                                       process-handle-feedback
                                         └─ PR updated, review re-requested
process-review-pr (again)
  └─ signed off → squash-merged, issue closes automatically
process-close-milestone
  └─ docs/BUILD_PLAN.md updated, next milestone unblocked
```

> `process-close-milestone` calls `workflow-milestone-completion`, which cascades into
> `workflow-deployment-verification` → `workflow-qa` → (UI milestones only)
> `workflow-accessibility-testing` / `workflow-responsiveness-testing`. Trigger only
> `process-close-milestone` — the inner skills run automatically and would otherwise run twice.

---

## Suggested skill execution order

### Orchestrator

| Step | Trigger | Skill |
|---|---|---|
| 1 | Planning a new milestone | `process-plan-milestone` → `workflow-project-planning` |
| 2 | A PR is opened or updated | `process-review-pr` → `workflow-code-review` (+ `workflow-accessibility-testing` and `workflow-responsiveness-testing` for `orchestrator-ui` PRs) |
| 3 | All issues in a milestone are closed | `process-close-milestone` → `workflow-milestone-completion` |
| 4 | A blocker is recorded on an issue | `workflow-blocker-escalation` — resolve it or plan around it |
| 5 | Milestone closes | `workflow-notion-sync` (Social Media Context update — the one mandatory Notion sync) |

### Implementors (backend / frontend)

| Step | Trigger | Skill |
|---|---|---|
| 1 | Start of every session / picking up the next issue | `process-implement-milestone` → `workflow-phase-issues` (entry point) |
| 2 | Start of a new milestone (backend only) | `workflow-env-verification` |
| 3 | Before writing any code | `workflow-dependency-check` |
| 4 | After implementation is complete | `workflow-testing` |
| 5 | Before opening a PR — backend: any `ProviderAdapter`/config/endpoint change; frontend: switching a mock to live | `workflow-api-contract-verification` |
| 6 | Before opening a PR | `workflow-pr-creation` |
| 7 | Review comments received | `process-handle-feedback` → `workflow-feedback-on-tickets` |
| 8 | Unable to proceed | `workflow-blocker-escalation` |
| 9 | Any issue state change | `workflow-notion-sync` (no-op at the per-issue level — see that skill) |

---

## Skill index by role

| Skill | Orchestrator | Backend | Frontend |
|---|---|---|---|
| `process-plan-milestone` | Y | | |
| `process-implement-milestone` | | Y | Y |
| `process-review-pr` | Y | | |
| `process-handle-feedback` | | Y | Y |
| `process-close-milestone` | Y | | |
| `workflow-phase-issues` | | Y | Y |
| `workflow-notion-sync` | Y | Y | Y |
| `workflow-blocker-escalation` | Y | Y | Y |
| `workflow-feedback-on-tickets` | | Y | Y |
| `workflow-api-contract-verification` | | Y | Y |
| `workflow-dependency-check` | | Y | Y |
| `workflow-env-verification` | | Y | |
| `workflow-testing` | | Y | Y |
| `workflow-pr-creation` | | Y | Y |
| `workflow-project-planning` | Y | | |
| `workflow-code-review` | Y | | |
| `workflow-accessibility-testing` | Y | | |
| `workflow-responsiveness-testing` | Y | | |
| `workflow-qa` | Y | | |
| `workflow-deployment-verification` | Y | | |
| `workflow-milestone-completion` | Y | | |
