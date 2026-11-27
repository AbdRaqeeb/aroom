import type { ProblemKind, Run, RunState } from './types'

export const ACTIVE: ReadonlySet<string> = new Set([
  'queued', 'briefing', 'researching', 'building', 'checking', 'verifying', 'fixing', 'merging',
])

export function ago(iso?: string | null): string {
  if (!iso) return ''
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const s = Math.max(0, Math.round((Date.now() - t) / 1000))
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

export function dur(sec?: number | null): string {
  if (!sec || sec < 1) return '0s'
  if (sec < 60) return `${Math.round(sec)}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${String(Math.round(sec % 60)).padStart(2, '0')}s`
  return `${Math.floor(sec / 3600)}h ${String(Math.floor((sec % 3600) / 60)).padStart(2, '0')}m`
}

export function money(v?: number | null): string {
  return `$${Number(v || 0).toFixed(2)}`
}

export function shortPath(p?: string): string {
  if (!p) return ''
  return p.replace(/^\/home\/[^/]+/, '~').replace(/^\/Users\/[^/]+/, '~')
}

export function clock(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
}

export function dayLabel(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const y = new Date()
  y.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === y.toDateString()) return 'Yesterday'
  return d.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' })
}

/** Preview URLs are configured as localhost:<port>; from a phone point them at this host. */
export function hostUrl(u?: string): string {
  if (!u) return ''
  const here = location.hostname
  if (['localhost', '127.0.0.1', '::1', '[::1]'].includes(here)) return u
  try {
    const parsed = new URL(u)
    if (['localhost', '127.0.0.1', '0.0.0.0', '[::1]'].includes(parsed.hostname)) {
      parsed.hostname = here
      return parsed.toString()
    }
  } catch {
    /* not a URL */
  }
  return u
}

export function prettyModel(model?: string): string {
  if (!model) return 'default'
  return model.replace(/^opencode-go\//, '').replace(/^claude-/, '')
}

export const STAGES = ['brief', 'build', 'check', 'verify', 'merge'] as const
export type Sector = 'done' | 'live' | 'pending' | 'failed' | 'stopped'

/** Map a run to the five sectors of the pipeline bar. */
export function sectors(run: Pick<Run, 'state' | 'step' | 'verdict' | 'checks'>): Sector[] {
  const idx: Record<string, number> = {
    queued: 0, briefing: 0, researching: 1, building: 1, fixing: 1, checking: 2, built: 3,
    verifying: 3, merging: 4, passed: 4, merged: 5,
  }
  const state = run.state as RunState
  if (state === 'merged') return ['done', 'done', 'done', 'done', 'done']
  if (state === 'passed') return ['done', 'done', 'done', 'done', 'pending']
  if (state === 'needs-human' || state === 'failed' || state === 'stopped') {
    const step = String(run.step || '')
    let at = 1
    if (step.startsWith('merge')) at = 4
    else if (/verif|integration/.test(step)) at = 3
    else if (/check/.test(step)) at = 2
    else if (/brief/.test(step)) at = 0
    const mark: Sector = state === 'stopped' ? 'stopped' : 'failed'
    return STAGES.map((_, i) => (i < at ? 'done' : i === at ? mark : 'pending'))
  }
  const at = idx[state] ?? 0
  const waiting = state === 'queued' || state === 'built'
  return STAGES.map((_, i) => (i < at ? 'done' : i === at ? (waiting ? 'pending' : 'live') : 'pending'))
}

export function stateTone(state?: string): 'live' | 'done' | 'wait' | 'bad' | 'merge' | 'idle' {
  if (!state) return 'idle'
  if (['merged', 'passed'].includes(state)) return 'done'
  if (['failed'].includes(state)) return 'bad'
  if (['needs-human', 'stalled', 'blocked'].includes(state)) return 'wait'
  if (['merging'].includes(state)) return 'merge'
  if (['queued', 'built', 'stopped'].includes(state)) return 'idle'
  return 'live'
}

export const STATE_LABEL: Record<string, string> = {
  queued: 'Queued', briefing: 'Briefing', researching: 'Researching', building: 'Building', checking: 'Checking',
  verifying: 'Verifying', fixing: 'Fixing', built: 'Waiting for verifier', merging: 'Merging', passed: 'Ready to merge',
  merged: 'Merged', 'needs-human': 'Needs you', failed: 'Failed', stopped: 'Stopped',
}

export const KIND_LABEL: Record<ProblemKind, string> = {
  'merge-conflict': 'Merge conflict',
  'integration-failed': 'Integration',
  'merge-hook': 'Hook rejected merge',
  'dirty-base': 'Uncommitted changes',
  'verification-failed': 'Verifier rejected',
  'checks-failed': 'Checks failing',
  'build-failed': 'Build failed',
  'needs-human': 'Decision needed',
  quota: 'Account / quota',
  budget: 'Budget reached',
  blocked: 'Blocked',
  stalled: 'Stalled',
  stopped: 'Stopped',
  'push-failed': 'Push failed',
}

export function kindTone(kind: ProblemKind): 'bad' | 'wait' | 'merge' | 'live' {
  if (['merge-conflict', 'integration-failed', 'merge-hook'].includes(kind)) return 'merge'
  if (['verification-failed', 'checks-failed', 'build-failed', 'budget'].includes(kind)) return 'bad'
  if (['quota', 'push-failed'].includes(kind)) return 'live'
  return 'wait'
}

export const ACTION_LABEL: Record<string, string> = {
  resolve: 'Resolve conflicts',
  'agent-fix': 'Send back to agent',
  answer: 'Answer the agent',
  'retry-merge': 'Retry merge',
  'mark-merged': 'Mark merged',
  merge: 'Merge',
  resume: 'Resume',
  reverify: 'Re-verify',
  unblock: 'Unblock',
  'run-fresh': 'Start over',
  clean: 'Discard work',
  stash: 'Stash changes',
  'commit-base': 'Commit changes',
  push: 'Retry push',
  stop: 'Stop',
  open: 'Open run',
}

export const CONFIRM: Partial<Record<string, string>> = {
  clean: "Delete this task's worktree and branch? The agent's work on it is lost.",
  'run-fresh': 'Discard the current branch and start this task again from scratch?',
  stash: 'Stash all uncommitted changes in the main checkout? Restore them later with `git stash pop`.',
  'mark-merged': 'Only use this if you already committed the merge into the base by hand. Mark it merged?',
  stop: 'Stop this run?',
}
