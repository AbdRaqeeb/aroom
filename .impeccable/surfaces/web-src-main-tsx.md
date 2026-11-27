---
version: 1
slug: "web-src-main-tsx"
primary_target: "web/src/main.tsx"
related_targets: ["agentroom/assets/app/index.html"]
---

# Surface: Agent Room dashboard (web/ → agentroom/assets/app)

Mode: Operate. Audience: the owner, checking agents from laptop or phone. Job: see what needs them, fix it in a tap, keep queues moving, glance at what's running.

## Direction contract

seed: 77e14b94 (assigned, timing tower)

THESIS: Agent Room is a race timing tower for coding agents. The screen owns one idea: every task in every project is a car on the tower, and the ones that need the human are pit calls pinned above the field. It refuses the category default of a grid of project cards with status pills.

OWN-WORLD: Calm graphite (dark) / paper (light) shell with a cooler second neutral for the sidebar. One system UI sans at a tight 1.125 scale; tabular numerals for times, counts and costs; mono only for ids, paths and logs. Colour does state work only: green done, blue live, amber waiting/attention, red failed, violet merging. State is also line form: solid live, dashed pending, struck stopped, doubled = pit call.

STORY: Open the app → pit calls tell you exactly what needs you and offer the fix; below, the field shows everything running with where each task is in the pipeline and for how long; tap any row for the full run; projects, activity and tasks are one tap away in the sidebar/tab bar.

FIRST VIEWPORT: Desktop: sidebar (Overview, Needs you with count, Activity, Projects, project list with live dots) + main column: page header with live counters, Pit calls block (each a doubled-left-rule row: kind, project·task, headline, primary fix button), then the Timing tower table. Phone: same content stacked, bottom tab bar, no sidebar.

SIGNATURE: The 5-sector pipeline bar (brief · build · check · verify · merge) on every task row: segments fill as stages complete, the live sector pulses subtly, sector width is proportional to time spent, pending sectors are dashed hairlines.

RISK: The tower could read as a spreadsheet; it must keep generous row height, clear hierarchy, and the pit-call block must feel like the screen's lead.

Raises from declined challengers: rank by apparatus (lexicon): pit calls get full apparatus, running rows medium, queued rows one quiet line. State as line form (emission rail): dashed/solid/struck so state reads without colour. Hairline module discipline (high-density web): one hairline weight and one radius family across every surface.
