import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { ArrowRight, ChevronRight, MessageCircleQuestion, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { api } from '@/lib/api'
import { ACTION_LABEL, CONFIRM, ago, kindTone } from '@/lib/format'
import { useRefresh } from '@/lib/hooks'
import { toast } from '@/lib/toast'
import type { FixAction, Problem, ProblemDetail } from '@/lib/types'
import { closeOverlay, openOverlay } from '@/lib/ui-store'
import { Button, Code, CopyButton, Dialog, KindBadge, Skeleton, Textarea, cx } from './ui'

const PIT_COLOR = { bad: 'var(--bad)', wait: 'var(--wait)', merge: 'var(--merge)', live: 'var(--live)' }

/** Actions that need text from the person, or a dedicated screen, before they can run. */
const NEEDS_PANEL = new Set<FixAction>(['answer', 'commit-base'])

export function useRunFix() {
  const refresh = useRefresh()
  const navigate = useNavigate()
  const [busy, setBusy] = useState<string | null>(null)
  async function run(p: Pick<Problem, 'project' | 'task' | 'kind'>, action: FixAction, note = '') {
    if (action === 'resolve') return openOverlay({ kind: 'conflict', project: p.project, task: p.task })
    if (action === 'open') {
      closeOverlay()
      return navigate({ to: '.', search: (prev: Record<string, unknown>) => ({ ...prev, run: `${p.project}/${p.task}` }) } as never)
    }
    if (NEEDS_PANEL.has(action) && !note && action === 'answer') return openOverlay({ kind: 'fix', problem: p })
    const confirmText = CONFIRM[action]
    if (confirmText && !window.confirm(confirmText)) return
    setBusy(action)
    try {
      const res = await api.fix(p.project, p.task, action, note)
      toast(res.message || `${ACTION_LABEL[action]} done`)
      refresh()
      return true
    } catch (e) {
      toast((e as Error).message, true)
      throw e
    } finally {
      setBusy(null)
    }
  }
  return { run, busy }
}

/** A pit call: one problem, with the apparatus it has earned. */
export function PitCall({ problem: p, compact = false, showProject = true }: { problem: Problem; compact?: boolean; showProject?: boolean }) {
  const { run, busy } = useRunFix()
  const tone = kindTone(p.kind)
  const acts = p.actions.filter((a) => a !== 'open')
  const primary = acts[0]
  const secondary = compact ? [] : acts.slice(1, 3)
  const where = [showProject ? p.project : '', p.task].filter(Boolean).join(' · ')
  return (
    <article
      className="pit-rule grid gap-x-6 gap-y-2 border-b border-line py-4 pr-1 pl-5 last:border-b-0 md:grid-cols-[1fr_auto]"
      style={{ ['--pit' as string]: PIT_COLOR[tone] }}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <KindBadge kind={p.kind} />
          <span className="font-mono text-[12.5px] text-ink-2">{where}</span>
          {p.title && <span className="truncate text-[13px] text-ink-3">{p.title}</span>}
          {p.since && <span className="tnum text-xs text-ink-3">{ago(p.since)}</span>}
        </div>
        <button
          onClick={() => openOverlay({ kind: 'fix', problem: p })}
          className="mt-1.5 block text-left text-[15px] leading-snug font-semibold text-ink hover:underline"
        >
          {p.headline}
        </button>
        {!compact && <p className="mt-1 max-w-[72ch] text-sm text-ink-2">{p.summary}</p>}
        {!compact && p.question && (
          <div className="mt-2.5 flex max-w-[72ch] gap-2.5 rounded-[10px] bg-live-soft px-3 py-2.5 text-sm text-ink">
            <MessageCircleQuestion className="mt-0.5 size-4 shrink-0 text-live" />
            <p className="whitespace-pre-wrap">{p.question}</p>
          </div>
        )}
        {!compact && !p.question && p.excerpt && (
          <Code className="mt-2.5 max-h-[6.5em] max-w-[72ch] overflow-hidden text-xs">{p.excerpt}</Code>
        )}
        {!compact && p.warning && (
          <p className="mt-2 flex items-center gap-1.5 text-[13px] text-warn-ink">
            <TriangleAlert className="size-3.5" />
            {p.warning}
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-start gap-2 md:max-w-[340px] md:justify-end md:pt-0.5">
        {primary && (
          <Button
            variant="primary"
            size="sm"
            busy={busy === primary}
            onClick={() => (NEEDS_PANEL.has(primary) ? openOverlay({ kind: 'fix', problem: p }) : run(p, primary).catch(() => {}))}
          >
            {ACTION_LABEL[primary]}
          </Button>
        )}
        {secondary.map((a) => (
          <Button
            key={a}
            size="sm"
            busy={busy === a}
            onClick={() => (NEEDS_PANEL.has(a) ? openOverlay({ kind: 'fix', problem: p }) : run(p, a).catch(() => {}))}
          >
            {ACTION_LABEL[a]}
          </Button>
        ))}
        <Button size="sm" variant="ghost" onClick={() => openOverlay({ kind: 'fix', problem: p })}>
          Details <ChevronRight className="size-4" />
        </Button>
      </div>
    </article>
  )
}

export function FixDialog({ problem, onClose }: { problem: Pick<Problem, 'project' | 'task' | 'kind'>; onClose: () => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['problem', problem.project, problem.task, problem.kind],
    queryFn: () => api.problem(problem.project, problem.task, problem.kind),
    retry: false,
  })
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const { run, busy } = useRunFix()
  const d = data as ProblemDetail | undefined
  const acts = (d?.actions ?? []).filter((a) => a !== 'open')
  const takesNote = acts.some((a) => ['agent-fix', 'answer', 'resume', 'commit-base'].includes(a))
  const hint = acts.includes('answer')
    ? 'Your answer for the agent. It goes back with the task.'
    : acts.includes('commit-base')
      ? 'Commit message (optional)'
      : 'Optional guidance for the agent, e.g. "keep the base\'s API and rename the new field"'

  async function act(a: FixAction) {
    setErr('')
    if (a === 'answer' && !note.trim()) {
      setErr('Write your answer first.')
      return
    }
    try {
      const ok = await run(problem, a, note.trim())
      if (ok || a === 'resolve' || a === 'open') onClose()
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      size="lg"
      title={d ? d.headline : isLoading ? 'Loading…' : 'Already resolved'}
      description={
        d ? (
          <span className="flex flex-wrap items-center gap-2">
            <KindBadge kind={d.kind} />
            <span className="font-mono text-[12.5px]">{[d.project, d.task].filter(Boolean).join(' · ')}</span>
            {d.title && <span className="text-ink-3">{d.title}</span>}
          </span>
        ) : undefined
      }
      footer={
        d && (
          <>
            {d.has_run ? (
              <Button variant="ghost" className="mr-auto" onClick={() => act('open')}>
                Open run
              </Button>
            ) : null}
            {acts
              .slice()
              .reverse()
              .map((a) => (
                <Button
                  key={a}
                  variant={a === acts[0] ? 'primary' : ['clean', 'run-fresh'].includes(a) ? 'danger' : 'secondary'}
                  busy={busy === a}
                  onClick={() => act(a)}
                >
                  {ACTION_LABEL[a]}
                </Button>
              ))}
          </>
        )
      }
    >
      {isLoading && (
        <div className="space-y-3">
          <Skeleton className="h-5 w-3/4" />
          <Skeleton className="h-16" />
          <Skeleton className="h-40" />
        </div>
      )}
      {error && <p className="text-sm text-ink-2">{(error as Error).message}. It may have been fixed already.</p>}
      {d && (
        <div className="space-y-4">
          <p className="max-w-[72ch] text-[15px] text-ink-2">{d.summary}</p>
          {d.question && (
            <div className="flex gap-2.5 rounded-xl bg-live-soft px-3.5 py-3 text-sm text-ink">
              <MessageCircleQuestion className="mt-0.5 size-4 shrink-0 text-live" />
              <div>
                <p className="font-medium">The agent asks</p>
                <p className="mt-0.5 whitespace-pre-wrap">{d.question}</p>
              </div>
            </div>
          )}
          {d.next && (
            <div className="flex gap-2.5 rounded-xl border border-line bg-sunken px-3.5 py-3 text-sm">
              <ArrowRight className="mt-0.5 size-4 shrink-0 text-accent" />
              <p>
                <span className="font-medium text-ink">What to do: </span>
                <span className="text-ink-2">{d.next}</span>
              </p>
            </div>
          )}
          {d.warning && (
            <p className="flex items-center gap-1.5 text-sm text-warn-ink">
              <TriangleAlert className="size-4" /> {d.warning}
            </p>
          )}
          {takesNote && <Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder={hint} />}
          {err && <p className="text-sm whitespace-pre-wrap text-bad">{err}</p>}
          <div>
            <h3 className="mt-2 mb-2 text-[13px] font-semibold text-ink">Everything recorded</h3>
            <div className="divide-y divide-line overflow-hidden rounded-xl border border-line">
              {d.sections.length === 0 && <p className="px-4 py-3 text-sm text-ink-3">Nothing else was recorded.</p>}
              {d.sections.map((s, i) => (
                <details key={s.label + i} open={i < 2} className="group">
                  <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 text-sm font-medium text-ink hover:bg-sunken">
                    <ChevronRight className="size-4 text-ink-3 transition-transform group-open:rotate-90" />
                    {s.label}
                    <span className="ml-auto">
                      <CopyButton text={s.text} />
                    </span>
                  </summary>
                  <div className="px-4 pb-4">
                    {s.kind === 'code' ? (
                      <Code className="max-h-[45vh]">{s.text}</Code>
                    ) : (
                      <p className="max-w-[72ch] text-sm whitespace-pre-wrap text-ink-2">{s.text}</p>
                    )}
                  </div>
                </details>
              ))}
            </div>
          </div>
        </div>
      )}
    </Dialog>
  )
}

export function ProblemList({ problems, showProject = true, limit }: { problems: Problem[]; showProject?: boolean; limit?: number }) {
  const shown = limit ? problems.slice(0, limit) : problems
  return (
    <div className={cx('rounded-2xl border border-line bg-surface px-4')}>
      {shown.map((p) => (
        <PitCall key={p.id} problem={p} showProject={showProject} />
      ))}
    </div>
  )
}

type Item = { type: 'one'; p: Problem } | { type: 'group'; key: string; list: Problem[] }

/** Same project, same kind, same headline: one cause, shown once with every task it hit. */
export function groupProblems(problems: Problem[]): Item[] {
  const buckets = new Map<string, Problem[]>()
  for (const p of problems) {
    const key = p.task ? `${p.project}|${p.kind}|${p.headline}` : p.id
    buckets.set(key, [...(buckets.get(key) ?? []), p])
  }
  const out: Item[] = []
  const seen = new Set<string>()
  for (const p of problems) {
    const key = p.task ? `${p.project}|${p.kind}|${p.headline}` : p.id
    if (seen.has(key)) continue
    seen.add(key)
    const list = buckets.get(key)!
    out.push(list.length > 1 ? { type: 'group', key, list } : { type: 'one', p })
  }
  return out
}

export function ProblemStack({ problems, showProject = true, limit }: { problems: Problem[]; showProject?: boolean; limit?: number }) {
  const items = groupProblems(problems)
  const shown = limit ? items.slice(0, limit) : items
  return (
    <div className="rounded-2xl border border-line bg-surface px-4">
      {shown.map((it) =>
        it.type === 'one' ? (
          <PitCall key={it.p.id} problem={it.p} showProject={showProject} />
        ) : (
          <PitGroup key={it.key} list={it.list} showProject={showProject} />
        ),
      )}
    </div>
  )
}

export function stackCount(problems: Problem[]) {
  return groupProblems(problems).length
}

function PitGroup({ list, showProject }: { list: Problem[]; showProject: boolean }) {
  const refresh = useRefresh()
  const [busy, setBusy] = useState<string | null>(null)
  const first = list[0]
  const tone = kindTone(first.kind)
  const acts = first.actions.filter((a) => a !== 'open' && !NEEDS_PANEL.has(a) && a !== 'resolve')
  async function runAll(a: FixAction) {
    const c = CONFIRM[a]
    if (c && !window.confirm(`${c}\n\nThis applies to ${list.length} tasks.`)) return
    setBusy(a)
    let ok = 0
    const failed: string[] = []
    for (const p of list) {
      try {
        await api.fix(p.project, p.task, a)
        ok++
      } catch (e) {
        failed.push(`${p.task}: ${(e as Error).message.split('\n')[0]}`)
      }
    }
    setBusy(null)
    refresh()
    if (failed.length) toast(`${ACTION_LABEL[a]}: ${ok} done, ${failed.length} failed (${failed[0]})`, true)
    else toast(`${ACTION_LABEL[a]} done for ${ok} tasks`)
  }
  return (
    <article className="pit-rule grid gap-x-6 gap-y-2 border-b border-line py-4 pr-1 pl-5 last:border-b-0 md:grid-cols-[1fr_auto]" style={{ ['--pit' as string]: PIT_COLOR[tone] }}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <KindBadge kind={first.kind} />
          <span className="font-mono text-[12.5px] text-ink-2">{showProject ? `${first.project} · ` : ''}{list.length} tasks</span>
          {first.since && <span className="tnum text-xs text-ink-3">{ago(first.since)}</span>}
        </div>
        <button onClick={() => openOverlay({ kind: 'fix', problem: first })} className="mt-1.5 block text-left text-[15px] leading-snug font-semibold text-ink hover:underline">
          {first.headline}
        </button>
        <p className="mt-1 max-w-[72ch] text-sm text-ink-2">{first.summary}</p>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {list.map((p) => (
            <button
              key={p.id}
              onClick={() => openOverlay({ kind: 'fix', problem: p })}
              title={p.title}
              className="inline-flex h-7 items-center rounded-md border border-line-strong px-2 font-mono text-xs text-ink hover:bg-sunken"
            >
              {p.task}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-start gap-2 md:max-w-[340px] md:justify-end md:pt-0.5">
        {acts.slice(0, 2).map((a, i) => (
          <Button key={a} size="sm" variant={i === 0 ? 'primary' : 'secondary'} busy={busy === a} onClick={() => runAll(a)}>
            {ACTION_LABEL[a]} all {list.length}
          </Button>
        ))}
        <Button size="sm" variant="ghost" onClick={() => openOverlay({ kind: 'fix', problem: first })}>
          Details <ChevronRight className="size-4" />
        </Button>
      </div>
    </article>
  )
}
