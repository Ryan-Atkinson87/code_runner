---
name: workflow-notion-sync
description: Keep this project's Notion presence consistent with GitHub issue/PR state. Use whenever another skill says "apply workflow-notion-sync". Both orchestrator and implementor agents.
---

This project has no per-issue Notion tracking database (see `CLAUDE.md`). GitHub issues are the
technical tasks directly, and Spec §15 is the open-items list. Notion sync for this project is
therefore narrow — most invocations of this skill are a deliberate no-op.

## Per-issue / per-PR calls (most invocations)

Examples: after opening a PR, after a merge, after creating new issues during planning, after
logging an accessibility/responsiveness/QA finding.

**Action: none.** Note "Notion: no per-issue tracking page for this project — nothing to sync"
and move on. Do **not** create a Technical Tasks or User Stories database to have somewhere to
sync to — `CLAUDE.md` is explicit that this should not be added speculatively.

## Milestone-level calls (from `workflow-milestone-completion` / `process-close-milestone`)

Update the 📣 Social Media Context page (link in `CLAUDE.md`), following the template in Spec
§5.4 step 6:

- **Current Status** — one or two sentences on where the project stands now: what's built, what
  just shipped, what's next.
- **Recent Milestones** — bullet list of what this milestone delivered, framed so it could
  become a build-in-public post.
- **What's Coming Next** — bullet list headlining the next milestone's work.

This update is **mandatory** at every milestone close — it is the one Notion sync that always
applies. Make it idempotent: read the current page content first and replace/append the
relevant sections rather than blindly appending, so re-running after a partial failure
(Spec §18.5) leaves the page correct, not duplicated.

## If new Notion tracking is added later

If a future milestone introduces a Technical Tasks / User Stories database for this project,
update this skill (and `CLAUDE.md`) to describe the per-issue sync rules — mirroring the
original Trive `workflow-notion-sync` pattern: each GitHub issue maps to one Notion task row,
status mirrors the GitHub issue state, and the row links back to the GitHub issue URL.
