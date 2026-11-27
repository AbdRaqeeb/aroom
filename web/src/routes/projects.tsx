import { Link } from '@tanstack/react-router'
import { ExternalLink, FolderGit2, Plus } from 'lucide-react'
import { useState } from 'react'
import { Page, PageHeader } from '@/components/shell'
import { Badge, Button, Empty } from '@/components/ui'
import { api } from '@/lib/api'
import { hostUrl, shortPath } from '@/lib/format'
import { isRunning, useAppState, useRefresh } from '@/lib/hooks'
import { toast } from '@/lib/toast'
import type { Project } from '@/lib/types'
import { openOverlay } from '@/lib/ui-store'
import { Loading } from './overview'

export function ProjectsPage() {
  const { data, isLoading } = useAppState()
  if (isLoading || !data) return <Loading />
  return (
    <Page>
      <PageHeader title="Projects" sub={`${data.projects.length} registered. They can live anywhere on this machine.`}>
        <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => openOverlay({ kind: 'add' })}>
          Add project
        </Button>
      </PageHeader>
      {data.projects.length === 0 ? (
        <Empty icon={<FolderGit2 className="size-7" />} title="No projects yet">
          Add any git repository. Agent Room detects its task list, checks and base branch, then you can run tasks or start a loop.
        </Empty>
      ) : (
        <div className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
          {data.projects.map((p) => (
            <ProjectRow key={p.name} p={p} />
          ))}
        </div>
      )}
    </Page>
  )
}

function ProjectRow({ p }: { p: Project }) {
  const refresh = useRefresh()
  const [busy, setBusy] = useState(false)
  const counts = p.counts ?? { todo: 0, done: 0, total: 0 }
  const pct = counts.total ? Math.round((counts.done / counts.total) * 100) : 0
  const live = (p.lanes?.builders.length ?? 0) + (p.lanes?.verifiers.length ?? 0)
  const queued = p.lanes?.queued.length ?? 0
  const problems = p.problems?.length ?? 0
  if (!p.configured) {
    return (
      <div className="flex flex-wrap items-center gap-4 px-5 py-4">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-ink">{p.name}</p>
          <p className="truncate font-mono text-[12.5px] text-ink-3">{shortPath(p.path)}</p>
          <p className="mt-1 text-sm text-ink-2">Tracked only. No task config yet{p.sessions.length ? ` · ${p.sessions.length} live session` : ''}.</p>
        </div>
        <Button
          size="sm"
          busy={busy}
          onClick={async () => {
            setBusy(true)
            try {
              await api.addProject(p.path)
              toast(`${p.name} set up`)
              refresh()
            } catch (e) {
              toast((e as Error).message, true)
            } finally {
              setBusy(false)
            }
          }}
        >
          Set up for agents
        </Button>
      </div>
    )
  }
  return (
    <Link to="/projects/$name" params={{ name: p.name }} className="grid gap-x-6 gap-y-3 px-5 py-4 transition-colors hover:bg-sunken/70 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_auto] md:items-center">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className={isRunning(p) ? 'size-2 rounded-full bg-live [animation:sector-pulse_1.8s_ease-in-out_infinite]' : 'size-2 rounded-full bg-line-strong'} />
          <span className="text-[15px] font-semibold text-ink">{p.name}</span>
          {p.mode === 'async' && <Badge>async</Badge>}
          {problems > 0 && <Badge tone="wait">{problems} need{problems === 1 ? 's' : ''} you</Badge>}
        </div>
        <p className="mt-0.5 truncate font-mono text-[12.5px] text-ink-3">{shortPath(p.path)}</p>
      </div>
      <div className="min-w-0">
        <div className="tnum flex justify-between text-[13px] text-ink-2">
          <span>
            {counts.done} of {counts.total} tasks done
          </span>
          <span className="text-ink-3">{pct}%</span>
        </div>
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-sunken">
          <div className="h-full rounded-full bg-done" style={{ width: `${pct}%` }} />
        </div>
        <p className="tnum mt-1.5 text-[13px] text-ink-3">
          {live} running · {queued} queued · {p.loop?.alive ? 'loop on' : 'loop off'} · {p.git.branch}
          {p.git.clean === false ? ` · ${p.git.changes} uncommitted` : ''}
        </p>
      </div>
      <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
        {p.preview?.running && p.preview.url && (
          <a href={hostUrl(p.preview.url)} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line-strong px-3 text-[13px] font-medium text-ink hover:bg-sunken">
            Open app <ExternalLink className="size-3.5" />
          </a>
        )}
      </div>
    </Link>
  )
}
