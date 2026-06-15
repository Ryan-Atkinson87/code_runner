---
name: workflow-responsiveness-testing
description: Responsiveness review of a frontend PR or the running UI. Use this skill during review of any PR that adds or changes orchestrator-ui, or as part of milestone QA. Orchestrator only.
---

Test every changed screen at three breakpoints: mobile (375px), tablet (768px), and desktop (1280px). If the UI uses a collapsible sidebar or navigation drawer, also test the exact breakpoint where it collapses (one pixel below and at the breakpoint).

## Breakpoint reference

| Context | Width | Expected layout |
|---|---|---|
| Mobile | 375px | Single column, full-width inputs, collapsed/condensed navigation |
| Tablet | 768px | Single column or two-column, wider content area |
| Desktop | 1280px | Multi-column where appropriate, full navigation visible |

## Step 1: Identify changed screens

From the PR diff or milestone scope, list every screen or component that changed. Only test what changed.

## Step 2: Mobile (375px)

For each changed screen:
- Layout does not overflow horizontally (no horizontal scroll)
- Text is readable without zooming (minimum 16px body text)
- Tap targets meet the 44×44px minimum
- Forms stack vertically with full-width inputs
- Any multi-column layout (e.g. usage gauges, blocker list, run list) collapses to a single column or becomes a clearly-scrollable region
- Navigation collapses to its mobile pattern (e.g. drawer or bottom nav) if one is implemented

## Step 3: Tablet (768px)

For each changed screen:
- Layout sits between mobile and desktop correctly, no awkward half-collapsed states
- Content area uses the wider width without excessive line lengths (max ~75 characters for body text)
- If a specific layout behaviour at this width is documented in the issue or Specification, confirm it

## Step 4: Desktop (1280px)

For each changed screen:
- Multi-column layouts are active where appropriate
- Navigation (sidebar/nav bar) is visible and functional
- No content is unnaturally stretched to fill the full width if a max-width container is used

## Step 5: Log findings

For each finding, create a GitHub issue in this repo:

**Title:** `[Responsive] [screen name] [breakpoint] — [one line description]`

**Body must include:**
- Breakpoint and exact viewport width where the issue occurs
- Steps to reproduce
- Expected behaviour (reference the issue or Specification if applicable)
- Actual behaviour
- Screenshot

Labels: `responsive`, `bug`

Severity:
- `critical`: layout is broken or content is inaccessible at the breakpoint
- `major`: layout is degraded but usable
- `minor`: cosmetic misalignment or spacing issue

Assign `critical` and `major` findings to the current milestone. Assign `minor` to the next milestone.

Apply `workflow-notion-sync` for each issue created (a no-op at this level — see that skill).
