---
name: process-review-pr
description: End-to-end process for reviewing a PR from an implementor agent. Covers lint/typecheck, spec compliance, boundary rules, test coverage, accessibility, responsiveness, and merge. Run this for every PR an implementor opens. Orchestrator only.
---

Run this process for every PR an implementor opens. Do not sign off, merge, or request changes without completing all applicable steps.

## Step 0: Lint and type-check

Before reading any code, verify the branch builds clean. This catches broken imports, type errors, and lint violations early — before wasting review effort on a branch that would fail CI.

1. Fetch the PR branch locally:
   ```
   git fetch origin <branch>
   git checkout <branch>
   ```
2. If the dependency manifest for the changed area has changed (lockfile / `pyproject.toml` / `package.json`), install dependencies for that area first — see `CLAUDE.md` for the package manager once chosen.
3. For each area touched, run its lint and typecheck commands from `CLAUDE.md`:
   - Backend: `<BACKEND_LINT_CMD>`, `<BACKEND_TYPECHECK_CMD>`
   - Frontend: `<FRONTEND_LINT_CMD>`, `<FRONTEND_TYPECHECK_CMD>`

   If a command is still a placeholder in `CLAUDE.md`, note that and skip it — once filled in, it's mandatory.
4. Treat any lint **error** (non-zero exit) or typecheck error as a blocker.

If either command exits non-zero, **stop immediately**: post a "Requesting changes" comment (`gh pr comment <PR> --body "..."`) listing the exact errors and the files/lines they appear on. Do not proceed to Step 1 until the implementor fixes them and re-pushes.

If both pass (or are not yet established), proceed.

## Step 1: Code review

Apply `workflow-code-review`. This covers:
- Spec compliance against the Specification and `docs/api.md`
- The production-readiness bar and architecture rules in `CLAUDE.md`
- Boundary rule violations
- Test coverage for the acceptance criteria paths

`workflow-code-review` will tell you to sign off or request changes. If you request changes, stop here and wait for the implementor to apply `process-handle-feedback`. Return to this process when the PR is updated.

## Step 2: Accessibility review (UI PRs only)

If the PR touches `orchestrator-ui`, apply `workflow-accessibility-testing`. This checks keyboard navigation, screen reader semantics, colour contrast, and touch targets for all changed screens.

Skip this step for backend-only PRs.

## Step 3: Responsiveness review (UI PRs only)

If the PR touches `orchestrator-ui`, apply `workflow-responsiveness-testing`. This checks mobile (375px), tablet (768px), and desktop (1280px) breakpoints for all changed screens.

Skip this step for backend-only PRs.

## Step 4: Sign off, merge, and sync

`workflow-code-review` Step 8 (sign off / request changes) and Step 9 (merge + sync) complete the process — once Steps 1–3 above are clean, follow those steps to merge the PR into `main`. Merging closes the linked issue automatically via `Closes #N`.

If `workflow-accessibility-testing` or `workflow-responsiveness-testing` raised non-blocking findings, confirm those issues were created and assigned to the appropriate milestone before merging.
