import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearch } from '@tanstack/react-router'
import {
  ArrowUp,
  ExternalLink,
  GitBranch,
  GitMerge,
  Play,
  Repeat,
  RotateCw,
  Search,
  Settings2,
  Square,
  Upload,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ProblemStack } from '@/components/problems'
import { Markdown } from '@/components/markdown'
import { Page } from '@/components/shell'
import { Tower, useOpenRun } from '@/components/tower'
import { Badge, Button, Empty, SectionHead, Skeleton, Tabs, Textarea, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { ago, hostUrl, prettyModel, shortPath } from '@/lib/format'
import { isRunning, towerRows, useAppState, useRefresh } from '@/lib/hooks'
import { toast } from '@/lib/toast'
import type { Project } from '@/lib/types'
import { openOverlay } from '@/lib/ui-store'
import { Loading } from './overview'

type Tab = 'overview' | 'tasks' | 'git' | 'preview' | 'chat'

export function ProjectPage() {
  const { name } = useParams({ strict: false }) as { name: string }
  const search = useSearch({ strict: false }) as { tab?: Tab }
  const navigate = useNavigate()
  const tab: Tab = search.tab ?? 'overview'
  const { data, isLoading } = useAppState()
  if (isLoading || !data) return <Loading />
  const p = data.projects.find((x) => x.name === name)
  if (!p)
    return (
      <Page>
        <Empty icon={<Search className="size-7" />} title={`No project called ${name}`}>
          <Link to="/projects" className="text-accent hover:underline">
            Back to projects
          </Link>
        </Empty>
      </Page>
    )
  const problems = p.problems ?? []
  const setTab = (t: string) => navigate({ to: '.', search: (prev: Record<string, unknown>) => ({ ...prev, tab: t === 'overview' ? undefined : t }) } as never)
  return (
    <Page>
      <Header p={p} />
      <Tabs
        className="mb-7"
        value={tab}
        onValueChange={setTab}
        items={[
          { value: 'overview', label: <>Overview{problems.length ? <Badge tone="wait" className="h-5 px-1.5">{problems.length}</Badge> : null}</> },
          { value: 'tasks', label: <>Tasks <span className="tnum text-ink-3">{p.counts?.todo ?? 0}</span></> },
          { value: 'git', label: 'Git' },
          ...(p.preview?.configured ? [{ value: 'preview', label: 'Preview' }] : []),
          ...(p.configured ? [{ value: 'chat', label: 'Chat' }] : []),
        ]}
      />
      {tab === 'overview' && <ProjectOverview p={p} />}
      {tab === 'tasks' && <TasksTab p={p} />}
      {tab === 'git' && <GitTab p={p} />}
      {tab === 'preview' && <PreviewTab p={p} />}
      {tab === 'chat' && <ChatTab p={p} />}
    </Page>
  )
}

function Header({ p }: { p: Project }) {
  const refresh = useRefresh()
  const [busy, setBusy] = useState<string | null>(null)
  const running = isRunning(p)
  const dirty = p.git.clean === false
  async function go(name: string, fn: () => Promise<unknown>, msg: string, confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return
    setBusy(name)
    try {
      await fn()
      toast(msg)
      refresh()
    } catch (e) {
      toast((e as Error).message, true)
    } finally {
      setBusy(null)
    }
  }
  const agents = p.agents
  return (
    <div className="mb-6">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <h1 className="text-[26px] leading-tight font-semibold tracking-[-0.02em] text-ink">{p.name}</h1>
            {running ? <Badge tone="live">{p.loop?.alive ? 'Loop running' : 'Running'}</Badge> : p.configured ? <Badge>Idle</Badge> : <Badge>Tracked only</Badge>}
          </div>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-2">
            <span className="font-mono text-[13px] text-ink-3">{shortPath(p.path)}</span>
            {p.git.branch && (
              <span className="inline-flex items-center gap-1">
                <GitBranch className="size-3.5 text-ink-3" />
                {p.git.branch}
              </span>
            )}
            {agents && (
              <button onClick={() => openOverlay({ kind: 'models', project: p.name })} className="inline-flex items-center gap-1 hover:text-ink">
                <Settings2 className="size-3.5 text-ink-3" />
                {agents.builder.runner} · {prettyModel(agents.builder.model)}
              </button>
            )}
          </p>
        </div>
        {p.configured && (
          <div className="ml-auto flex flex-wrap gap-2">
            {p.preview?.running && p.preview.url && (
              <a href={hostUrl(p.preview.url)} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-2 rounded-[10px] border border-line-strong px-4 text-sm font-medium text-ink hover:bg-sunken">
                Open app <ExternalLink className="size-4" />
              </a>
            )}
            {running ? (
              <Button variant="danger" busy={busy === 'stop'} icon={<Square className="size-3.5" />} onClick={() => go('stop', () => api.stop(p.name), `Stopping ${p.name}`, `Stop all runs and the loop for ${p.name}?`)}>
                Stop
              </Button>
            ) : (
              <>
                <Button
                  disabled={dirty || !(p.next ?? []).length}
                  title={dirty ? 'Commit or stash changes in the main checkout first' : undefined}
                  busy={busy === 'run'}
                  icon={<Play className="size-4" />}
                  onClick={() => go('run', () => api.start({ project: p.name }), `Started the next ${p.name} task`)}
                >
                  Run next task
                </Button>
                <Button
                  variant="primary"
                  disabled={dirty || !(p.next ?? []).length}
                  title={dirty ? 'Commit or stash changes in the main checkout first' : undefined}
                  busy={busy === 'loop'}
                  icon={<Repeat className="size-4" />}
                  onClick={() =>
                    go('loop', () => api.start({ project: p.name, loop: true, auto_merge: true }), `Loop started for ${p.name}`, `The loop keeps taking ${p.name} tasks and merges each one that passes. Start it?`)
                  }
                >
                  Start loop
                </Button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function ProjectOverview({ p }: { p: Project }) {
  const rows = towerRows([p], { recent: true })
  const problems = p.problems ?? []
  return (
    <>
      {problems.length > 0 && (
        <>
          <SectionHead title="Needs you" count={problems.length} />
          <ProblemStack problems={problems} showProject={false} />
        </>
      )}
      <SectionHead title="Timing tower" count={rows.length}>
        {p.mode === 'async' && (
          <span className="tnum text-xs text-ink-3">
            {p.lanes?.build_capacity} builders · {p.lanes?.capacity} verifiers
          </span>
        )}
      </SectionHead>
      {rows.length ? (
        <Tower rows={rows} showProject={false} />
      ) : (
        <Empty icon={<Play className="size-7" />} title="Nothing running">
          {p.configured ? 'Run the next task, or start the loop to keep working through the plan.' : 'Set this project up for agents from the Projects page.'}
        </Empty>
      )}
      {(p.next ?? []).length > 0 && (
        <>
          <SectionHead title="Up next" />
          <UpNext p={p} />
        </>
      )}
      {p.sessions.length > 0 && (
        <>
          <SectionHead title="Live sessions in this repo" count={p.sessions.length} />
          <div className="divide-y divide-line rounded-2xl border border-line bg-surface">
            {p.sessions.map((s) => (
              <button key={s.id} onClick={() => openOverlay({ kind: 'session', id: s.id })} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-sunken/70">
                <span className={s.busy ? 'size-2 rounded-full bg-live' : 'size-2 rounded-full bg-line-strong'} />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm text-ink">{s.model || 'session'} · {s.status}</span>
                  <span className="block truncate text-[13px] text-ink-3">{s.last_text || s.last_tool}</span>
                </span>
                <span className="text-xs text-ink-3">{ago(s.started)}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </>
  )
}

function UpNext({ p }: { p: Project }) {
  const refresh = useRefresh()
  const dirty = p.git.clean === false
  return (
    <div className="divide-y divide-line rounded-2xl border border-line bg-surface">
      {(p.next ?? []).slice(0, 5).map((t) => (
        <div key={t.id} className="flex items-center gap-3 px-4 py-2.5">
          <span className="inline-block h-3 border-l border-dashed border-ink-3" />
          <span className="font-mono text-[13px] font-medium text-ink">{t.id}</span>
          <span className="min-w-0 flex-1 truncate text-sm text-ink-2">{t.title}</span>
          <Button
            size="sm"
            variant="ghost"
            disabled={dirty}
            onClick={async () => {
              try {
                await api.start({ project: p.name, task: t.id })
                toast(`Started ${t.id}`)
                refresh()
              } catch (e) {
                toast((e as Error).message, true)
              }
            }}
          >
            Run
          </Button>
        </div>
      ))}
    </div>
  )
}

function TasksTab({ p }: { p: Project }) {
  const open = useOpenRun()
  const refresh = useRefresh()
  const [q, setQ] = useState('')
  const [showDone, setShowDone] = useState(false)
  const tasks = (p.tasks ?? []).filter((t) => !q || `${t.id} ${t.title}`.toLowerCase().includes(q.toLowerCase()))
  const active = new Set(p.active_ids ?? [])
  const blocked = p.blocked ?? {}
  const runState = new Map((p.runs ?? []).map((r) => [r.task, r]))
  const problemFor = new Map((p.problems ?? []).map((x) => [x.task, x]))
  const groups = [
    { title: 'In progress', list: tasks.filter((t) => active.has(t.id)) },
    { title: 'Needs you', list: tasks.filter((t) => !active.has(t.id) && (problemFor.has(t.id) || blocked[t.id])) },
    { title: 'Ready to merge', list: tasks.filter((t) => runState.get(t.id)?.state === 'passed' && !active.has(t.id)) },
    { title: 'To do', list: tasks.filter((t) => t.state === ' ' && !active.has(t.id) && !problemFor.has(t.id) && !blocked[t.id] && runState.get(t.id)?.state !== 'passed') },
  ]
  const done = tasks.filter((t) => t.state === 'x')
  return (
    <>
      <div className="mb-5 flex items-center gap-2">
        <div className="relative w-full max-w-sm">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter tasks"
            className="h-10 w-full rounded-[10px] border border-line-strong bg-surface pr-3 pl-9 text-sm text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
          />
        </div>
        <span className="tnum ml-auto text-sm text-ink-3">
          {p.counts?.done}/{p.counts?.total} done
        </span>
      </div>
      {groups.map((g) =>
        g.list.length ? (
          <section key={g.title} className="mb-7">
            <SectionHead title={g.title} count={g.list.length} />
            <div className="divide-y divide-line rounded-2xl border border-line bg-surface">
              {g.list.map((t) => {
                const prob = problemFor.get(t.id)
                const run = runState.get(t.id)
                return (
                  <div key={t.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3">
                    <span className="w-24 shrink-0 font-mono text-[13px] font-medium text-ink">{t.id}</span>
                    <span className="min-w-0 flex-1 text-sm text-ink">
                      {t.title}
                      {(prob || blocked[t.id]) && (
                        <span className="block text-[13px] text-warn-ink">{prob ? prob.headline : `Blocked: ${blocked[t.id].reason.slice(0, 160)}`}</span>
                      )}
                    </span>
                    <span className="flex gap-1.5">
                      {prob && (
                        <Button size="sm" variant="primary" onClick={() => openOverlay({ kind: 'fix', problem: prob })}>
                          Fix
                        </Button>
                      )}
                      {!prob && blocked[t.id] && (
                        <Button size="sm" variant="primary" onClick={() => openOverlay({ kind: 'fix', problem: { project: p.name, task: t.id, kind: 'blocked' } })}>
                          Fix
                        </Button>
                      )}
                      {run?.state === 'passed' && (
                        <Button
                          size="sm"
                          variant="primary"
                          icon={<GitMerge className="size-3.5" />}
                          onClick={async () => {
                            try {
                              await api.merge(p.name, t.id)
                              toast(`${t.id} merged`)
                              refresh()
                            } catch (e) {
                              toast((e as Error).message, true)
                            }
                          }}
                        >
                          Merge
                        </Button>
                      )}
                      {g.title === 'To do' && (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={p.git.clean === false}
                          onClick={async () => {
                            try {
                              await api.start({ project: p.name, task: t.id })
                              toast(`Started ${t.id}`)
                              refresh()
                            } catch (e) {
                              toast((e as Error).message, true)
                            }
                          }}
                        >
                          Run
                        </Button>
                      )}
                      {run && (
                        <Button size="sm" variant="ghost" onClick={() => open(p.name, t.id)}>
                          Open
                        </Button>
                      )}
                    </span>
                  </div>
                )
              })}
            </div>
          </section>
        ) : null,
      )}
      <section>
        <SectionHead title="Done" count={done.length}>
          <Button size="sm" variant="ghost" onClick={() => setShowDone(!showDone)}>
            {showDone ? 'Hide' : 'Show'}
          </Button>
        </SectionHead>
        {showDone && (
          <div className="divide-y divide-line rounded-2xl border border-line bg-surface">
            {done.map((t) => (
              <div key={t.id} className="flex items-center gap-3 px-4 py-2.5 text-sm text-ink-3">
                <span className="w-24 shrink-0 font-mono text-[13px]">{t.id}</span>
                <span className="min-w-0 flex-1 truncate line-through decoration-line-strong">{t.title}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  )
}

function GitTab({ p }: { p: Project }) {
  const { data } = useQuery({ queryKey: ['git', p.name], queryFn: () => api.git(p.name), refetchInterval: 15_000 })
  const refresh = useRefresh()
  const g = p.git
  const push = p.push
  const facts: [string, React.ReactNode][] = [
    ['Branch', <span className="font-mono text-[13px]">{g.branch}</span>],
    ['Status', g.clean ? 'Clean' : <span className="text-warn-ink">{g.changes} uncommitted change{g.changes === 1 ? '' : 's'}</span>],
    ['Head', <span><span className="font-mono text-[13px]">{g.short}</span> {g.subject} <span className="text-ink-3">· {g.when}</span></span>],
    ['Remote', g.remote_link ? <a href={g.remote_link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">{g.remote_label} <ExternalLink className="size-3.5" /></a> : g.remote || 'none'],
    ['Upstream', g.upstream ? <span>{g.upstream} · {g.ahead || g.behind ? `${g.ahead} ahead, ${g.behind} behind` : 'in sync'}</span> : 'not pushed'],
    ['Push', push?.enabled ? (push.ok ? <span className="text-done">OK · checked {ago(push.checked)}</span> : <span className="text-bad">Failed: {push.error}</span>) : 'Off'],
  ]
  return (
    <div className="space-y-8">
      <dl className="grid grid-cols-[100px_1fr] gap-x-4 gap-y-3 rounded-2xl border border-line bg-surface p-5 text-sm">
        {facts.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-ink-3">{k}</dt>
            <dd className="min-w-0 text-ink [overflow-wrap:anywhere]">{v}</dd>
          </div>
        ))}
      </dl>
      {push?.enabled && (
        <Button
          icon={<Upload className="size-4" />}
          onClick={async () => {
            try {
              const r = await api.fix(p.name, '', 'push')
              toast(r.message || 'Pushed')
              refresh()
            } catch (e) {
              toast((e as Error).message, true)
            }
          }}
        >
          Push now
        </Button>
      )}
      <section>
        <SectionHead title="Worktrees" count={data?.worktrees.length} />
        {!data ? <Skeleton className="h-32" /> : (
          <div className="divide-y divide-line rounded-2xl border border-line bg-surface">
            {data.worktrees.map((w) => (
              <div key={w.path} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 px-4 py-2.5 text-sm">
                <span className="font-mono text-[13px] text-ink">{w.branch || '(detached)'}</span>
                <span className="font-mono text-xs text-ink-3">{w.head}</span>
                <span className="w-full truncate font-mono text-xs text-ink-3 md:ml-auto md:w-auto">{shortPath(w.path)}</span>
              </div>
            ))}
          </div>
        )}
      </section>
      <section>
        <SectionHead title="Branches" count={data?.branches.length} />
        {!data ? <Skeleton className="h-48" /> : (
          <div className="divide-y divide-line rounded-2xl border border-line bg-surface">
            {data.branches.map((b) => (
              <div key={b.name} className="grid gap-x-4 px-4 py-2.5 text-sm md:grid-cols-[220px_1fr_auto]">
                <span className={cx('truncate font-mono text-[13px]', b.current ? 'font-semibold text-ink' : 'text-ink')}>{b.name}</span>
                <span className="truncate text-ink-2">{b.subject}</span>
                <span className="text-xs text-ink-3">{b.when}{b.track ? ` · ${b.track}` : ''}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function PreviewTab({ p }: { p: Project }) {
  const pv = p.preview!
  const refresh = useRefresh()
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const { data } = useQuery({ queryKey: ['preview-log', p.name], queryFn: () => api.previewLog(p.name, 600), refetchInterval: 3000 })
  const lines = useMemo(() => (data?.log ?? '').split('\n').filter((l) => !filter || l.toLowerCase().includes(filter.toLowerCase())), [data, filter])
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!filter) end.current?.scrollIntoView({ block: 'nearest' })
  }, [lines.length, filter])
  async function act(a: 'start' | 'stop' | 'restart') {
    setBusy(a)
    try {
      const r = await api.preview(p.name, a)
      toast(r.note || `Preview ${a === 'stop' ? 'stopped' : a === 'restart' ? 'restarting' : 'starting'}`)
      refresh()
    } catch (e) {
      toast((e as Error).message, true)
    } finally {
      setBusy(null)
    }
  }
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        {(pv.services ?? [{ name: 'app', url: pv.url ?? '', port: pv.port ?? 0, open: !!pv.running }]).map((s) => (
          <a
            key={s.name}
            href={hostUrl(s.url)}
            target="_blank"
            rel="noreferrer"
            className={cx('inline-flex h-10 items-center gap-2 rounded-[10px] border px-4 text-sm font-medium', s.open ? 'border-line-strong text-ink hover:bg-sunken' : 'border-dashed border-line-strong text-ink-3')}
          >
            <span className={cx('size-2 rounded-full', s.open ? 'bg-done' : 'bg-line-strong')} />
            {s.name}
            <span className="tnum font-mono text-xs text-ink-3">:{s.port}</span>
            <ExternalLink className="size-3.5" />
          </a>
        ))}
        <span className="ml-auto flex gap-2">
          {pv.running ? (
            <>
              <Button busy={busy === 'restart'} icon={<RotateCw className="size-4" />} onClick={() => act('restart')}>
                Restart
              </Button>
              <Button variant="danger" busy={busy === 'stop'} onClick={() => act('stop')}>
                Stop
              </Button>
            </>
          ) : (
            <Button variant="primary" busy={busy === 'start'} icon={<Play className="size-4" />} onClick={() => act('start')}>
              Start preview
            </Button>
          )}
        </span>
      </div>
      <section>
        <SectionHead title="Console">
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter (e.g. otp, error)"
            className="h-8 w-44 rounded-lg border border-line-strong bg-surface px-2.5 text-[13px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
          />
        </SectionHead>
        {(data?.highlights ?? []).length > 0 && (
          <div className="mb-3 rounded-xl bg-live-soft px-4 py-3 text-sm text-ink">
            {data!.highlights!.map((h, i) => (
              <p key={i} className="font-mono text-[13px]">{h}</p>
            ))}
          </div>
        )}
        <div className="max-h-[60vh] overflow-auto rounded-xl border border-line bg-sunken p-3 font-mono text-[12px] leading-[1.55] text-ink-2">
          {lines.map((l, i) => (
            <div key={i} className={cx('whitespace-pre-wrap [overflow-wrap:anywhere]', /error|failed|exception/i.test(l) && 'text-bad')}>
              {l || ' '}
            </div>
          ))}
          <div ref={end} />
        </div>
      </section>
    </div>
  )
}

function ChatTab({ p }: { p: Project }) {
  const { data, refetch } = useQuery({ queryKey: ['chat', p.name], queryFn: () => api.chat(p.name), refetchInterval: 2000 })
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  const thinking = data?.status === 'running'
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [data?.messages.length, thinking])
  async function send() {
    const m = text.trim()
    if (!m) return
    setSending(true)
    try {
      await api.sendChat(p.name, m)
      setText('')
      refetch()
    } catch (e) {
      toast((e as Error).message, true)
    } finally {
      setSending(false)
    }
  }
  return (
    <div className="flex flex-col rounded-2xl border border-line bg-surface">
      <div className="min-h-[40vh] space-y-4 p-4 md:max-h-[62vh] md:overflow-y-auto md:p-6">
        {!data?.messages.length && (
          <p className="mx-auto max-w-md py-10 text-center text-sm text-ink-2">
            Ask the {p.name} agent anything about the repo: how something works, what a failing task needs, or to make a quick change. It runs in the main checkout with the project's builder model.
          </p>
        )}
        {data?.messages.map((m, i) => (
          <div key={i} className={cx('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
            {m.role === 'user' ? (
              <div className="max-w-[85%] rounded-2xl bg-accent px-4 py-2.5 text-[14.5px] leading-relaxed whitespace-pre-wrap text-accent-ink">{m.text}</div>
            ) : (
              <div className="max-w-[92%] min-w-0 rounded-2xl bg-sunken px-4 py-3 text-ink">
                <Markdown text={m.text} />
              </div>
            )}
          </div>
        ))}
        {thinking && <p className="text-sm text-ink-3">Thinking…</p>}
        <div ref={end} />
      </div>
      <div className="sticky bottom-[calc(60px+env(safe-area-inset-bottom))] flex items-end gap-2 rounded-b-2xl border-t border-line bg-surface p-3 md:static">
        <Textarea
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
          placeholder={thinking ? 'The agent is replying…' : `Message the ${p.name} agent`}
          className="max-h-40 min-h-10 resize-none!"
        />
        <Button variant="primary" busy={sending} disabled={!text.trim() || thinking} onClick={send} aria-label="Send" className="size-10 px-0">
          <ArrowUp className="size-[18px] shrink-0" strokeWidth={2.4} />
        </Button>
      </div>
      {data && (
        <p className="px-4 pb-3 text-xs text-ink-3">
          {data.runner} · {prettyModel(data.model)}
        </p>
      )}
    </div>
  )
}

