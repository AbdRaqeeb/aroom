# Design — Agent Room dashboard

Recorded from the shipped build in `web/` (v1.2.0). The world is a **timing tower**: every task is a car on the tower, and work that needs the human is a pit call pinned above the field.

## Principles

- What needs the human leads every screen that can show it.
- Calm shell; colour does state work only.
- State also reads by line form, so it never depends on colour alone.
- Familiar web controls: buttons, tabs, selects, dialogs and sheets. The world shows up only in type, palette, density and the pipeline bar.

## Colour (OKLCH, `web/src/styles.css`)

Themes follow the system unless the user picks one (`data-theme` on `<html>`, saved in `localStorage['aroom-theme']`).

| Role | Light | Dark | Use |
| --- | --- | --- | --- |
| `bg` | 0.975 0.003 95 | 0.185 0.006 260 | page |
| `surface` | 0.995 0.002 95 | 0.215 0.007 260 | panels, tables, dialogs |
| `rail` | 0.955 0.004 250 | 0.165 0.007 260 | sidebar (cooler second neutral) |
| `sunken` | 0.955 0.003 95 | 0.17 0.006 260 | code, hover rows, lane headers |
| `line` / `line-strong` | 0.89 / 0.80 | 0.29 / 0.37 | hairlines / control borders |
| `ink` / `ink-2` / `ink-3` | 0.22 / 0.42 / 0.55 | 0.945 / 0.78 / 0.64 | text tiers |
| `accent` | 0.47 0.16 262 | 0.74 0.12 262 | primary action, focus, selection |

State colours, each with a `-soft` fill for badges and callouts: `live` blue 258 (running), `done` green 152, `wait` amber 75–80 (needs you, stalled, blocked), `bad` red 25 (failed, rejected), `merge` violet 300 (merging, conflicts).

## Line-form state (`StateMark`)

- **Solid bar** (pulsing): live.
- **Doubled hairline**: needs attention or failed.
- **Dashed hairline**: waiting or queued.
- **Struck bar**: stopped.

The **pit rule** is a doubled 1px rule on a problem's leading edge, coloured by kind. It is the only left-edge mark in the system.

## Type

- One system UI stack (`ui-sans-serif, -apple-system, Segoe UI Variable…`); mono (`ui-monospace…`) only for task ids, paths, branches, logs and diffs.
- Base size 15px. Scale: 12/13/14/15/17/20/26. Page titles are 26px semibold at −0.02em; section heads 15px semibold.
- `.tnum` (tabular numerals) on every time, count and cost.
- Inputs are 16px on phones so iOS doesn't zoom.

## Shape and depth

- Radii: 6 (badges), 8–10 (controls), 12 (callouts), 16 (panels and tables), 16 top-only for phone sheets.
- Hairlines are 1px everywhere.
- One shadow, `--shadow-pop`, used only on floating layers: dialogs, sheets and toasts.

## Signature: pipeline bar

Five equal sectors (brief · build · check · verify · merge), 7px tall with a 3px gap:

- done = `done` fill
- live = `live` fill, pulsing
- pending = dashed `line-strong` outline
- failed = `bad`
- stopped = `ink-3` at 60%
- merging = `merge` on the last sector

In tables, the stage labels sit in the column header; in the run sheet, they sit under the bar.

## Layout

- **Desktop:** 248px sidebar (nav, project list with live dots and problem counts, supervisor status, theme switch, notifications, sign-out). Content is capped at 1180px with 40px gutters.
- **Phone (<768px):** a sticky top bar plus a 4-tab bottom bar with a needs-you badge. Dialogs become bottom sheets; the run sheet goes full screen.
- **Tower grid (`.tower-grid`):** `1.6fr 200px 1fr 76px 110px 60px` on desktop, stacked on phone. Lanes run in this order: on track, ready to merge, built/waiting, queued (one quiet line of chips), finished recently.
- **Apparatus by rank:** pit calls get the most room (badge, headline, summary, evidence, actions); running rows a medium row; queued tasks a single chip.

## Motion

- 150–250ms colour transitions. Sheets and dialogs enter with a 12–24px slide on `--ease-out-expo` (0.28s).
- A 1.8s pulse on live marks only.
- `prefers-reduced-motion` turns all of it off.

## Components (`web/src/components`)

| File | Contents |
| --- | --- |
| `ui.tsx` | Button (primary/secondary/ghost/danger), IconButton, Badge, StateBadge, KindBadge, StateMark, PipelineBar, Dialog, SideSheet, Tabs, Textarea, Code, CopyButton, Empty, SectionHead, Skeleton, Chip, Select |
| `problems.tsx` | PitCall, PitGroup (same cause across tasks, with bulk actions), ProblemStack, FixDialog |
| `conflicts.tsx` | ConflictResolver |
| `tower.tsx` | Tower |
| `run-sheet.tsx` | RunSheet |
| `dialogs.tsx` | Models, Resume, AddProject and Session dialogs |
| `shell.tsx` | Shell, PageHeader, Page |
