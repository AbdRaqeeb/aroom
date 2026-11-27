import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, GitBranch, GitMerge, Play, RotateCcw, Settings2, Square, Trash2, Wrench, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { ACTIVE, CONFIRM, clock, dur, money, prettyModel, shortPath } from '@/lib/format'
import { useAppState, useRefresh } from '@/lib/hooks'
import { toast } from '@/lib/toast'
import type { RunDetail, RunEvent } from '@/lib/types'
import { openOverlay } from '@/lib/ui-store'
import { Markdown } from './markdown'
import { Button, Code, IconButton, PipelineBar, SheetClose, SideSheet, Skeleton, StateBadge, Tabs, cx } from './ui'

export function RunSheet({ id, onClose }: { id: string; onClose: () => void }) {
  const [project, ...rest] = id.split('/')
  const task = rest.join('/')
  const [tab, setTab] = useState('overview')
  const { data: d, error } = useQuery({
    queryKey: ['run', project, task],
    queryFn: () => api.run(project, task),
    refetchInterval: 3000,
    retry: false,
  })
  const { data: state } = useAppState()
  const problem = state?.projects.find((p) => p.name === project)?.problems?.find((p) => p.task === task)

  return (
    <SideSheet open onOpenChange={(o) => !o && onClose()} label={`Run ${task}`}>
      <header className="border-b border-line px-5 pt-[max(16px,env(safe-area-inset-top))] pb-0">
        <div className="flex items-center gap-2">
          <SheetClose asChild>
            <IconButton label="Close" className="-ml-2 md:hidden">
              <ArrowLeft className="size-5" />
            </IconButton>
          </SheetClose>
          <span className="text-sm text-ink-3">{project}</span>
          <span className="font-mono text-sm font-medium text-ink">{task}</span>
          {d && <StateBadge state={d.state} stalled={d.stalled} />}
          <SheetClose asChild>
            <IconButton label="Close" className="ml-auto hidden md:inline-flex">
              <X className="size-5" />
            </IconButton>
          </SheetClose>
        </div>
        <h2 className="mt-2 text-xl leading-snug font-semibold tracking-[-0.015em] text-ink">{d?.title || task}</h2>
        {d && (
          <div className="mt-4 max-w-xl">
            <PipelineBar run={d} labels />
          </div>
        )}
        <Tabs
          className="mt-4 -mx-2"
          value={tab}
          onValueChange={setTab}
          items={[
            { value: 'overview', label: 'Overview' },
            { value: 'events', label: 'Events' },
            { value: 'verify', label: 'Verifier' },
            { value: 'diff', label: 'Diff' },
            { value: 'checks', label: 'Checks' },
            { value: 'brief', label: 'Brief' },
            { value: 'notes', label: 'Notes' },
          ]}
        />
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        {error && <p className="text-sm text-ink-2">No run record for {task} yet.</p>}
        {!d && !error && (
          <div className="space-y-3">
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-32" />
          </div>
        )}
        {d && tab === 'overview' && <Overview d={d} problemHeadline={problem?.headline} onFix={() => problem && openOverlay({ kind: 'fix', problem })} />}
        {d && tab === 'events' && <Events events={d.events} />}
        {d && tab === 'verify' && <Prose text={d.verify} empty="The verifier has not written a report yet." />}
        {d && tab === 'brief' && <Prose text={d.brief} empty="No brief yet." />}
        {d && tab === 'notes' && <Prose text={d.notes} empty="The agent left no notes." />}
        {d && tab === 'diff' && <Diff text={d.diff} />}
        {d && tab === 'checks' && <Checks d={d} />}
      </div>
      {d && <Actions d={d} project={project} hasProblem={!!problem} onFix={() => problem && openOverlay({ kind: 'fix', problem })} />}
    </SideSheet>
  )
}

function Overview({ d, problemHeadline, onFix }: { d: RunDetail; problemHeadline?: string; onFix: () => void }) {
  const facts: [string, React.ReactNode][] = [
    ['Step', d.step || '—'],
    ['Time', <span className="tnum">{dur(d.elapsed_s)}{d.round ? ` · round ${d.round}` : ''}</span>],
    ['Builder', `${d.builder_runner || '—'} · ${prettyModel(d.builder_model)}`],
    ['Verifier', `${d.verifier_runner || '—'} · ${prettyModel(d.verifier_model)}`],
    ['Branch', <span className="font-mono text-[13px]">{d.branch} → {d.base_branch}</span>],
    ['Changes', <span className="tnum">{d.commits ?? 0} commits · {d.files_changed ?? 0} files · <span className="text-done">+{d.insertions ?? 0}</span> <span className="text-bad">−{d.deletions ?? 0}</span></span>],
    ['Cost', <span className="tnum">{money(d.cost_usd)}</span>],
    ['Worktree', <span className="font-mono text-[13px] [overflow-wrap:anywhere]">{shortPath(d.worktree)} {d.worktree_exists === false && <span className="text-ink-3">(removed)</span>}</span>],
  ]
  return (
    <div className="space-y-6">
      {problemHeadline && (
        <button onClick={onFix} className="pit-rule flex w-full items-center gap-3 rounded-xl border border-line bg-wait-soft py-3 pr-3 pl-5 text-left">
          <span className="flex-1">
            <span className="block text-xs font-medium text-warn-ink">Needs you</span>
            <span className="block text-[15px] font-semibold text-ink">{problemHeadline}</span>
          </span>
          <span className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-[13px] font-medium text-accent-ink">
            <Wrench className="size-3.5" /> Fix
          </span>
        </button>
      )}
      <dl className="grid grid-cols-[110px_1fr] gap-x-4 gap-y-2.5 text-sm">
        {facts.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-ink-3">{k}</dt>
            <dd className="min-w-0 text-ink">{v}</dd>
          </div>
        ))}
      </dl>
      {d.error && (
        <div>
          <h3 className="mb-2 text-[13px] font-semibold text-ink">Error</h3>
          <Code className="max-h-60 text-bad">{d.error_detail || d.error}</Code>
        </div>
      )}
      {d.issues && (
        <div>
          <h3 className="mb-2 text-[13px] font-semibold text-ink">Open issues</h3>
          <Prose text={d.issues} empty="" />
        </div>
      )}
      <div>
        <h3 className="mb-2 text-[13px] font-semibold text-ink">Latest events</h3>
        <Events events={d.events.slice(-8)} />
      </div>
    </div>
  )
}

function Events({ events }: { events: RunEvent[] }) {
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [events.length])
  if (!events.length) return <p className="text-sm text-ink-3">No events yet.</p>
  return (
    <ol className="space-y-0.5 text-[13px]">
      {events.map((e, i) => (
        <li key={i} className="grid grid-cols-[48px_88px_1fr] gap-2 rounded-md px-1 py-1 hover:bg-sunken">
          <span className="tnum text-ink-3">{clock(e.ts)}</span>
          <span className={cx('truncate', e.actor === 'agent-room' ? 'text-accent' : 'text-ink-3')}>{e.actor}</span>
          <span
            className={cx(
              'min-w-0 [overflow-wrap:anywhere]',
              e.kind === 'error' ? 'text-bad' : e.kind === 'warn' ? 'text-warn-ink' : ['merged', 'pass'].includes(e.kind) ? 'text-done' : 'text-ink-2',
            )}
          >
            {e.text}
          </span>
        </li>
      ))}
      <div ref={end} />
    </ol>
  )
}

function Prose({ text, empty }: { text: string; empty: string }) {
  if (!text?.trim()) return <p className="text-sm text-ink-3">{empty}</p>
  return <Markdown text={text} className="max-w-[78ch] text-ink-2" />
}

function Diff({ text }: { text: string }) {
  if (!text?.trim()) return <p className="text-sm text-ink-3">No diff yet.</p>
  return (
    <pre className="overflow-auto rounded-xl border border-line bg-sunken py-2 font-mono text-[12px] leading-[1.55]">
      {text.split('\n').map((l, i) => (
        <div
          key={i}
          className={cx(
            'px-3 whitespace-pre-wrap [overflow-wrap:anywhere]',
            l.startsWith('+') && !l.startsWith('+++') && 'bg-done-soft text-ink',
            l.startsWith('-') && !l.startsWith('---') && 'bg-bad-soft text-ink',
            l.startsWith('@@') && 'text-live',
            l.startsWith('diff --git') && 'mt-3 border-t border-line pt-2 font-semibold text-ink',
            !/^[+\-@d]/.test(l) && 'text-ink-2',
          )}
        >
          {l || ' '}
        </div>
      ))}
    </pre>
  )
}

function Checks({ d }: { d: RunDetail }) {
  const entries = Object.entries(d.checks || {})
  if (!entries.length) return <p className="text-sm text-ink-3">No checks have run.</p>
  return (
    <div className="space-y-3">
      {entries.map(([cmd, info]) => (
        <details key={cmd} open={info.state === 'fail'} className="group rounded-xl border border-line">
          <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-2.5 text-sm">
            <span className={cx('font-medium', info.state === 'pass' ? 'text-done' : info.state === 'fail' ? 'text-bad' : 'text-warn-ink')}>
              {info.state === 'pass' ? 'Pass' : info.state === 'fail' ? 'Fail' : 'Running'}
            </span>
            <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-ink">{cmd}</span>
            <span className="tnum text-xs text-ink-3">{info.duration_s ? `${info.duration_s}s` : ''}</span>
          </summary>
          {info.tail && <Code className="mx-3 mb-3 max-h-[50vh] text-xs">{info.tail}</Code>}
        </details>
      ))}
    </div>
  )
}

function Actions({ d, project, hasProblem, onFix }: { d: RunDetail; project: string; hasProblem: boolean; onFix: () => void }) {
  const refresh = useRefresh()
  const [busy, setBusy] = useState<string | null>(null)
  const running = ACTIVE.has(d.state) && d.pid_alive
  const mergeRetry = d.state === 'needs-human' && String(d.step || '').startsWith('merge')
  const kept = d.worktree_exists && d.branch_exists
  async function go(name: string, fn: () => Promise<unknown>, done: string) {
    const c = CONFIRM[name]
    if (c && !window.confirm(c)) return
    setBusy(name)
    try {
      await fn()
      toast(done)
      refresh()
    } catch (e) {
      toast((e as Error).message, true)
    } finally {
      setBusy(null)
    }
  }
  return (
    <footer className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3 pb-[max(12px,env(safe-area-inset-bottom))]">
      <Button variant="ghost" size="sm" icon={<Settings2 className="size-4" />} onClick={() => openOverlay({ kind: 'models', project })}>
        Models
      </Button>
      <span className="mr-auto hidden items-center gap-1.5 text-xs text-ink-3 md:inline-flex">
        <GitBranch className="size-3.5" /> {d.branch}
      </span>
      {hasProblem && (
        <Button size="sm" variant="primary" icon={<Wrench className="size-4" />} onClick={onFix}>
          Fix
        </Button>
      )}
      {running && (
        <Button size="sm" variant="danger" busy={busy === 'stop'} icon={<Square className="size-3.5" />} onClick={() => go('stop', () => api.stop(project), 'Stopping')}>
          Stop
        </Button>
      )}
      {d.state === 'passed' && (
        <Button size="sm" variant="primary" busy={busy === 'merge'} icon={<GitMerge className="size-4" />} onClick={() => go('merge', () => api.merge(project, d.task), `${d.task} merged`)}>
          Merge
        </Button>
      )}
      {mergeRetry && !hasProblem && (
        <Button size="sm" busy={busy === 'merge'} onClick={() => go('merge', () => api.merge(project, d.task, true), `${d.task} merged`)}>
          Retry merge
        </Button>
      )}
      {kept && !running && !['passed', 'merged'].includes(d.state) && !mergeRetry && (
        <>
          <Button size="sm" busy={busy === 'verify'} icon={<RotateCcw className="size-3.5" />} onClick={() => go('verify', () => api.verify(project, d.task), `Re-verifying ${d.task}`)}>
            Re-verify
          </Button>
          <Button size="sm" icon={<Play className="size-3.5" />} onClick={() => openOverlay({ kind: 'resume', project, task: d.task })}>
            Resume
          </Button>
          <Button size="sm" variant="danger" busy={busy === 'clean'} icon={<Trash2 className="size-3.5" />} onClick={() => go('clean', () => api.clean(project, d.task), 'Worktree removed')}>
            Discard
          </Button>
        </>
      )}
    </footer>
  )
}
