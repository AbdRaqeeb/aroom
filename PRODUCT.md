# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Dashboard frontend: React 19 + TypeScript, Vite, Tailwind CSS v4, TanStack Router and TanStack Query, Radix primitives, lucide icons — matching the owner's other projects (aworin, sureplug). Source lives in `web/`; the built bundle is committed into the Python package (`agentroom/assets/app/`) so `curl … | bash` installs on a VPS still need no Node. The backend stays Python stdlib (`agentroom/ui.py`) serving the bundle and a JSON API.

## Users

One developer (the owner) running several coding projects at once through AI agents (Claude Code, OpenCode). They check in from a laptop and, increasingly, from a phone while away, against an instance running on a VPS. Their job in the dashboard: unblock the agents, decide on finished work, and keep queues moving without sitting at a terminal.

## Product Purpose

Agent Room orchestrates coding agents across many git repos: tasks come from each repo's plan, a builder agent implements each in its own worktree, checks and a verifier agent review it, and passing work is squash-merged and pushed. The dashboard is where the human sees state across every project and resolves whatever the pipeline cannot: merge conflicts, rejected work, failing checks, quota limits, blocked tasks, an agent's question. Success: the owner opens it, immediately sees what needs them, fixes it in a couple of taps, and the agents keep going.

## Positioning

Not an agent framework or chat app: state is plain git branches and JSON files in each repo, and the human is the escalation path for a pipeline that otherwise runs unattended. The dashboard's distinctive job is turning a stuck pipeline step into a plain-language diagnosis with the evidence and the exact fix (including resolving merge conflicts in the task's worktree).

## Operating Context

- Projects: aworin, sureplug (active, async builder/verifier pools), masaa (track-only Claude session). Projects can live anywhere on disk.
- Runs: brief → research → build → checks → verify → fix loop → integration gate → merge → push. States: queued, briefing, researching, building, checking, verifying, fixing, built, merging, passed, merged, needs-human, failed, stopped.
- A supervisor keeps loops running unattended; async mode runs parallel builders and verifiers with a serialized merge queue.
- Per-project preview servers (app/api/queues on unique ports), per-role runner/model selection, project chat with an agent, git/push status, external live sessions (Claude Code / OpenCode) detected on the machine.
- Used over Tailscale or HTTPS behind an access token.

## Capabilities and Constraints

- All existing API endpoints must keep working: `/api/state`, `/api/run`, `/api/problem`, `/api/fix`, `/api/conflict`, `/api/conflict/file`, `/api/activity`, `/api/git`, `/api/models`, `/api/session`, `/api/chat`, `/api/preview`, `/api/preview/log`, `/api/project/config`, `/api/projects`, `/api/track`, run/stop/verify/resume/merge/adopt/clean/unblock, `/login`, `/logout`.
- Dashboard polls `/api/state` (~2s); no websockets.
- Must work well on a phone (390px) and desktop; deep links must work.

## Brand Commitments

Name "Agent Room", CLI `aroom` (alias `ar`). No logo beyond the "AR" mark. Voice: plain, direct, specific — say what happened and what to do; never just "needs a human".

## Evidence on Hand

Real run data in the owner's projects; no testimonials or metrics to show. Demo states in development come from a throwaway fixture repo.

## Product Principles

1. What needs the human comes first; everything else is context.
2. Every problem explains itself: what happened, why, the evidence, the fix.
3. A fix is one or two taps away, on a phone as well as a laptop.
4. Calm by default: colour carries status, not decoration.
5. Never hide state: running work, queues and git status stay one glance away.

## Accessibility & Inclusion

Owner's stated preferences (confirmed 2026-11-26): open on "what needs me"; light and dark themes (follow system); calm, serious tool feel with colour reserved for status; not dense or terminal-like (no walls of monospace or tiny text).
