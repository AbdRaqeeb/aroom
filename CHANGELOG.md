# Changelog

## v1.0.0 — 2026-11-24

First stable release.

### Orchestration

- One `aroom` CLI and one dashboard for every registered git repo.
- Per-task git worktrees and branches, with resumable worktrees.
- Markdown checklist, folder-of-files, and GitHub issue task adapters.
- Builder → checks → verifier → fix loop, with acceptance criteria in the brief.
- Separate verifier sessions and optional researcher notes for vendor/LLM work.
- Async scheduler: configurable builder pool and verifier pool, with a serialized
  merge queue and automatic fix-round requeueing.
- Pre-merge integration gate: temporarily merges the current base, runs
  `commands.pre_merge`, and rejects stale branches before they land.
- Per-task locks, manual-run coexistence, merge marker, and push lock.
- Conflict handling: base reset on squash conflict, one automatic builder fix, then
  `needs-human`.
- Stall detection based on actual file activity, model rotation on quota errors, and
  a 15-minute all-models wait.
- Reboot recovery for active builds, verifications and merges.

### Dashboard and operations

- Wide project cards with runs, async lanes, checks, preview links and chat.
- Git detail per card: branch, origin link, upstream ahead/behind, HEAD, push state.
- Git details modal: worktrees, branches, tracking, remotes.
- Task board grouped by status, resume/merge/re-verify/clean actions.
- Preview lifecycle with service links and an OTP/console log view.
- GitHub push after merge (opt-in, never forced, retried by the scheduler).
- systemd user units for the UI and supervisor, with lingering and reboot recovery.

### Quality

- Deterministic `mock` runner for free end-to-end pipeline tests.
- Event streams, run artifacts, diffs and check logs under `.agent/runs/`.
- Documentation for configuration, architecture, operations and troubleshooting.

### Known limitations

- A single project-wide merge queue means merges are serialized.
- Concurrent builders can conflict when tasks edit the same files; keep
  `limits.builders` at 1 for projects with shared ports, databases or migrations.
- The dashboard is local-only by default.
- GitHub task sync is one-way (reads open issues; does not comment back).
