import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { api, get } from '@/lib/api'
import { clock, prettyModel, shortPath } from '@/lib/format'
import { useAppState, useRefresh } from '@/lib/hooks'
import { toast } from '@/lib/toast'
import { Button, Dialog, Select, Skeleton, Textarea, cx } from './ui'

const ROLES = [
  ['builder', 'Builder', 'Writes the code for each task.'],
  ['verifier', 'Verifier', 'Reviews the diff against the acceptance criteria.'],
  ['researcher', 'Researcher', 'Writes research notes before hard tasks.'],
] as const

export function ModelsDialog({ project, onClose }: { project: string; onClose: () => void }) {
  const { data: state } = useAppState()
  const refresh = useRefresh()
  const p = state?.projects.find((x) => x.name === project)
  const { data: models } = useQuery({ queryKey: ['models'], queryFn: api.models, staleTime: 60_000 })
  const [draft, setDraft] = useState<Record<string, { runner: string; model: string }>>({})
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (p?.agents && !Object.keys(draft).length) setDraft(JSON.parse(JSON.stringify(p.agents)))
  }, [p, draft])
  const runners = Object.keys(models ?? { claude: [], opencode: [] }).concat(['mock']).filter((v, i, a) => a.indexOf(v) === i)
  async function save() {
    setBusy(true)
    try {
      await api.saveAgents(project, draft)
      toast('Models saved. They apply to the next run.')
      refresh()
      onClose()
    } catch (e) {
      toast((e as Error).message, true)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      size="lg"
      title={`Models · ${project}`}
      description="Choose the agent CLI and model for each role. A run that is already going keeps its model."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" busy={busy} onClick={save}>
            Save
          </Button>
        </>
      }
    >
      {!models || !p ? (
        <Skeleton className="h-48" />
      ) : (
        <div className="divide-y divide-line">
          {ROLES.map(([role, label, help]) => {
            const cur = draft[role] ?? { runner: '', model: '' }
            const options = models[cur.runner] ?? []
            const known = options.some((o) => o.id === cur.model)
            return (
              <div key={role} className="grid gap-3 py-4 first:pt-0 md:grid-cols-[180px_160px_1fr] md:items-center">
                <div>
                  <p className="text-sm font-medium text-ink">{label}</p>
                  <p className="text-[13px] text-ink-3">{help}</p>
                </div>
                <Select value={cur.runner} onChange={(v) => setDraft({ ...draft, [role]: { runner: v, model: '' } })} aria-label={`${label} CLI`}>
                  {runners.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </Select>
                <Select value={cur.model} onChange={(v) => setDraft({ ...draft, [role]: { ...cur, model: v } })} aria-label={`${label} model`}>
                  {!known && cur.model && <option value={cur.model}>{prettyModel(cur.model)}</option>}
                  {options.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.label}
                    </option>
                  ))}
                  {!options.length && <option value="">default</option>}
                </Select>
              </div>
            )
          })}
        </div>
      )}
    </Dialog>
  )
}

export function ResumeDialog({ project, task, onClose }: { project: string; task: string; onClose: () => void }) {
  const { data: state } = useAppState()
  const refresh = useRefresh()
  const b = state?.projects.find((x) => x.name === project)?.agents?.builder
  const [note, setNote] = useState('')
  const [lockfile, setLockfile] = useState(false)
  const [busy, setBusy] = useState(false)
  async function go() {
    setBusy(true)
    try {
      await api.resume({ project, task, note: note.trim(), allow_lockfile: lockfile })
      toast(`Resuming ${task}`)
      refresh()
      onClose()
    } catch (e) {
      toast((e as Error).message, true)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Resume ${task}`}
      description={`The builder (${b?.runner ?? '?'} · ${prettyModel(b?.model)}) continues from the existing worktree and keeps its work.`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" busy={busy} onClick={go}>
            Resume
          </Button>
        </>
      }
    >
      <label className="mb-1.5 block text-sm font-medium text-ink" htmlFor="resume-note">
        Guidance for the builder <span className="font-normal text-ink-3">(optional)</span>
      </label>
      <Textarea id="resume-note" rows={4} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. The verifier is right about the missing test; add it and keep the API as is." />
      <label className="mt-4 flex items-start gap-3 text-sm text-ink-2">
        <input type="checkbox" checked={lockfile} onChange={(e) => setLockfile(e.target.checked)} className="mt-0.5 size-4 accent-[var(--accent)]" />
        <span>
          <span className="font-medium text-ink">Allow lockfile changes</span>
          <span className="block text-ink-3">For tasks that add or upgrade dependencies.</span>
        </span>
      </label>
    </Dialog>
  )
}

export function AddProjectDialog({ onClose }: { onClose: () => void }) {
  const [path, setPath] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const refresh = useRefresh()
  const navigate = useNavigate()
  async function go() {
    setBusy(true)
    setErr('')
    try {
      const r = (await api.addProject(path.trim())) as { project?: string }
      toast('Project added')
      refresh()
      onClose()
      if (r.project) navigate({ to: '/projects/$name', params: { name: r.project } })
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Add a project"
      description="Any git repository on this machine. Agent Room reads its .agent/config.json, or creates one from the commands it detects."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" busy={busy} disabled={!path.trim()} onClick={go}>
            Add project
          </Button>
        </>
      }
    >
      <label htmlFor="add-path" className="mb-1.5 block text-sm font-medium text-ink">
        Path to the repository
      </label>
      <input
        id="add-path"
        autoFocus
        value={path}
        onChange={(e) => setPath(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && path.trim() && go()}
        placeholder="~/code/my-app"
        spellCheck={false}
        autoComplete="off"
        className="h-10 w-full rounded-[10px] border border-line-strong bg-bg px-3 font-mono text-sm text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
      />
      {err && <p className="mt-2 text-sm whitespace-pre-wrap text-bad">{err}</p>}
    </Dialog>
  )
}

interface SessionDetail {
  id: string
  name?: string
  cwd: string
  model?: string
  status?: string
  started?: string
  events: { ts: string; role: string; text: string }[]
}

export function SessionDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, error } = useQuery({
    queryKey: ['session', id],
    queryFn: () => get<SessionDetail>(`/api/session?id=${encodeURIComponent(id)}`),
    refetchInterval: 3000,
  })
  const [tracking, setTracking] = useState(false)
  const refresh = useRefresh()
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      size="lg"
      title={data ? `Session in ${shortPath(data.cwd)}` : 'Session'}
      description={data ? `${data.model || 'model unknown'} · ${data.status}` : undefined}
      footer={
        data && (
          <Button
            busy={tracking}
            onClick={async () => {
              setTracking(true)
              try {
                await api.track(data.cwd)
                toast('Now tracking this repository')
                refresh()
                onClose()
              } catch (e) {
                toast((e as Error).message, true)
              } finally {
                setTracking(false)
              }
            }}
          >
            Track this repository
          </Button>
        )
      }
    >
      {error && <p className="text-sm text-ink-2">This session has ended.</p>}
      {!data && !error && <Skeleton className="h-60" />}
      {data && (
        <ol className="space-y-2">
          {data.events.map((e, i) => (
            <li key={i} className="grid grid-cols-[48px_72px_1fr] gap-2 text-[13px]">
              <span className="tnum text-ink-3">{clock(e.ts)}</span>
              <span className={cx(e.role === 'user' ? 'text-live' : e.role === 'assistant' ? 'text-done' : 'text-ink-3')}>{e.role}</span>
              <span className={cx('min-w-0 whitespace-pre-wrap [overflow-wrap:anywhere]', e.role === 'tool' ? 'font-mono text-xs text-ink-3' : 'text-ink-2')}>
                {e.text}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Dialog>
  )
}
