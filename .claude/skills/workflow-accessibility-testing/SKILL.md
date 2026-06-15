---
name: workflow-accessibility-testing
description: Accessibility review of a frontend PR or the running UI. Use this skill during review of any PR that adds or changes orchestrator-ui, or as part of milestone QA. Orchestrator only.
---

Accessibility findings are raised as labelled GitHub issues so they are tracked and prioritised alongside other work. A finding is not a blocker on PR merge unless it is WCAG 2.1 Level AA critical, but it must be recorded.

## Step 1: Determine scope

Identify which screens or components changed in the PR or milestone. Only assess what has changed. Do not audit the entire application on every run.

## Step 2: Keyboard navigation

For each changed screen or interactive component:
- Tab through all interactive elements in DOM order
- Confirm every interactive element is reachable by keyboard
- Confirm focus is visible at all times
- Confirm modal dialogs trap focus correctly and return focus to the trigger on close
- Confirm any live-updating region (e.g. the live progress feed, Spec §12) doesn't steal focus or disrupt keyboard navigation when it updates

## Step 3: Screen reader semantics

Check the following without relying on visual output:
- All images/icons have descriptive `alt` text, or `alt=""` if purely decorative
- Form inputs are associated with labels via `htmlFor` / `id` or `aria-label`
- Error messages are associated with their input via `aria-describedby`
- Page headings follow a logical hierarchy (`h1` → `h2` → `h3`, no skipping)
- Interactive elements that are not native buttons or links have appropriate ARIA roles
- Live-updating content (run progress, usage gauges, blocker list) announces to screen readers via `aria-live` where appropriate

## Step 4: Colour contrast

Check foreground/background contrast ratios using the project's design tokens:
- Body text on background: minimum 4.5:1 (AA)
- Large text (18pt+ or 14pt bold): minimum 3:1 (AA)
- UI components and focus indicators: minimum 3:1 (AA)

## Step 5: Touch targets (mobile)

For any component rendered below desktop width:
- Interactive elements must be at least 44×44px tap target
- Tap targets must not overlap

## Step 6: Log findings

For each finding, create a GitHub issue in this repo:

**Title:** `[A11y] [component or screen name] — [one line description]`

**Body must include:**
- WCAG 2.1 criterion violated (e.g. `1.4.3 Contrast (Minimum)`, `2.1.1 Keyboard`, `4.1.2 Name, Role, Value`)
- Level: `A`, `AA`, or `AAA`
- Steps to reproduce or location in the DOM
- Expected behaviour
- Actual behaviour
- Screenshot or DOM snippet if helpful

Labels: `accessibility`, `bug` (for AA violations), `enhancement` (for AAA)

Assign to the next available milestone if not blocking. Assign to the current milestone if Level A or AA critical.

Apply `workflow-notion-sync` for each issue created (a no-op at this level — see that skill).
