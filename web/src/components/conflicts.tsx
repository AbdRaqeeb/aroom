import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleDot, FileWarning, GitMerge, Pencil, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { useRefresh } from '@/lib/hooks'
import { toast } from '@/lib/toast'
import type { ConflictFile, ConflictStatus } from '@/lib/types'
import { Button, Code, Dialog, Skeleton, Tabs, Textarea, cx } from './ui'

function Highlighted({ text }: { text: string }) {
  let zone: '' | 'ours' | 'theirs' = ''
  const lines = text.split('\n')
  return (
    <pre className="h-full overflow-auto rounded-xl border border-line bg-sunken py-3 font-mono text-[12.5px] leading-[1.6] text-ink">
      {lines.map((line, i) => {
        let cls = ''
        let label = ''
        if (/^<{7}( |$)/.test(line)) {
          zone = 'ours'
          cls = 'marker'
          label = "task's version below"
        } else if (/^={7}$/.test(line)) {
          zone = 'theirs'
          cls = 'marker'
          label = "base's version below"
        } else if (/^>{7}( |$)/.test(line)) {
          zone = ''
          cls = 'marker'
        } else cls = zone
        return (
          <div
            key={i}
            className={cx(
              'flex min-h-[1.6em] px-3',
              cls === 'marker' && 'bg-merge-soft font-medium text-merge',
              cls === 'ours' && 'bg-live-soft',
              cls === 'theirs' && 'bg-done-soft',
            )}
          >
            <span className="w-10 shrink-0 pr-3 text-right text-ink-3 select-none">{i + 1}</span>
            <span className="whitespace-pre-wrap [overflow-wrap:anywhere]">
              {line || ' '}
              {label && <span className="ml-3 font-sans text-xs font-normal">← {label}</span>}
            </span>
          </div>
        )
      })}
    </pre>
  )
}

export function ConflictResolver({ project, task, onClose }: { project: string; task: string; onClose: () => void }) {
  const qc = useQueryClient()
  const refresh = useRefresh()
  const key = ['conflict', project, task]
  const { data: st, isLoading, error } = useQuery({ queryKey: key, queryFn: () => api.conflict(project, task), retry: false })
  const [file, setFile] = useState<string | null>(null)
  const [tab, setTab] = useState<'combined' | 'ours' | 'theirs'>('combined')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState('')

  const unresolved = st?.files.map((f) => f.path) ?? []
  useEffect(() => {
    if (st?.merging && (!file || !unresolved.includes(file))) setFile(unresolved[0] ?? null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [st])

  const { data: fd } = useQuery({
    queryKey: ['conflict-file', project, task, file],
    queryFn: () => api.conflictFile(project, task, file!),
    enabled: !!file && !!st?.merging,
    retry: false,
  })
  useEffect(() => {
    setEditing(false)
    setDraft(fd?.working ?? '')
    setTab(fd && (fd.binary || fd.working == null) ? 'ours' : 'combined')
  }, [fd])

  async function op(name: string, body: Parameters<typeof api.conflictOp>[0], done?: (r: ConflictStatus) => void) {
    setErr('')
    setBusy(name)
    try {
      const r = await api.conflictOp(body)
      qc.setQueryData(key, r)
      qc.invalidateQueries({ queryKey: ['conflict-file', project, task] })
      done?.(r)
    } catch (e) {
      setErr((e as Error).message)
      toast((e as Error).message, true)
    } finally {
      setBusy(null)
    }
  }

  const total = st?.files.length ?? 0
  const base = st?.base ?? 'base'

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      size={st?.merging ? 'full' : 'lg'}
      title={`Resolve conflicts · ${task}`}
      description={st ? <span className="font-mono text-[12.5px]">{st.branch} ← {base}</span> : project}
      footer={
        st &&
        (st.merging ? (
          <>
            <Button
              variant="danger"
              className="mr-auto"
              busy={busy === 'abort'}
              onClick={() =>
                window.confirm('Undo the merge in the worktree? Your file choices are discarded.') &&
                op('abort', { project, task, op: 'abort' }, () => toast('Merge undone'))
              }
            >
              Abort
            </Button>
            <Button
              disabled={total > 0}
              busy={busy === 'verify'}
              onClick={() =>
                op('verify', { project, task, op: 'finish', then: 'verify' }, () => {
                  toast(`${task} resolved · re-verifying`)
                  refresh()
                  onClose()
                })
              }
            >
              Finish & re-verify
            </Button>
            <Button
              variant="primary"
              disabled={total > 0}
              busy={busy === 'merge'}
              icon={<GitMerge className="size-4" />}
              onClick={() =>
                op('merge', { project, task, op: 'finish', then: 'merge' }, (r) => {
                  refresh()
                  if (r.merge_error) setErr('Resolved and committed, but the merge failed:\n' + r.merge_error)
                  else {
                    toast(`${task} merged`)
                    onClose()
                  }
                })
              }
            >
              Finish & merge
            </Button>
          </>
        ) : (
          <>
            <Button
              variant="ghost"
              className="mr-auto"
              busy={busy === 'agent'}
              onClick={async () => {
                setBusy('agent')
                try {
                  const r = await api.fix(project, task, 'agent-fix')
                  toast(r.message || 'Sent back to the agent')
                  refresh()
                  onClose()
                } catch (e) {
                  setErr((e as Error).message)
                } finally {
                  setBusy(null)
                }
              }}
            >
              Let the agent do it
            </Button>
            <Button variant="primary" busy={busy === 'start'} onClick={() => op('start', { project, task, op: 'start' }, (r) => r.clean && toast('Merged the base cleanly. No conflicts.'))}>
              Start resolving
            </Button>
          </>
        ))
      }
    >
      {isLoading && <Skeleton className="h-60" />}
      {error && <p className="text-sm text-bad">{(error as Error).message}</p>}
      {err && <p className="mb-3 rounded-lg bg-bad-soft px-3 py-2 text-sm whitespace-pre-wrap text-bad">{err}</p>}

      {st && !st.merging && (
        <div className="max-w-[72ch] space-y-4 text-[15px] text-ink-2">
          {st.predicted.length ? (
            <>
              <p>
                <span className="font-medium text-ink">{st.predicted.length} file{st.predicted.length === 1 ? '' : 's'}</span> changed on both{' '}
                <code className="font-mono text-sm">{base}</code> and this task:
              </p>
              <Code className="max-h-48">{st.predicted.join('\n')}</Code>
            </>
          ) : (
            <p>
              Right now <code className="font-mono text-sm">{base}</code> and the branch merge cleanly. Starting brings the base into the branch and finishes on its own.
            </p>
          )}
          <ol className="space-y-2">
            {[
              ['Start', `merges ${base} into the task's own worktree. Your main checkout is not touched.`],
              ['Choose', "for each file: keep the task's version, keep the base's version, or edit the combined file."],
              ['Finish & merge', 'commits the resolution and lands the task. Or finish & re-verify to have the verifier check it first.'],
            ].map(([a, b], i) => (
              <li key={a} className="flex gap-3">
                <span className="tnum flex size-6 shrink-0 items-center justify-center rounded-full bg-sunken text-xs font-semibold text-ink">{i + 1}</span>
                <span>
                  <span className="font-medium text-ink">{a}</span> {b}
                </span>
              </li>
            ))}
          </ol>
          {st.dirty && (
            <div>
              <p className="mb-1.5 text-sm text-warn-ink">The worktree has uncommitted agent work. Start commits it to the branch first:</p>
              <Code className="max-h-32">{st.dirty}</Code>
            </div>
          )}
          {st.base_dirty && (
            <p className="flex items-start gap-2 text-sm text-warn-ink">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" /> The main checkout has uncommitted changes. You can resolve now, but the final merge will wait until they are committed or stashed.
            </p>
          )}
        </div>
      )}

      {st?.merging && (
        <div className="flex h-full min-h-0 flex-col gap-4 md:grid md:grid-cols-[260px_1fr]">
          <nav className="flex shrink-0 gap-1.5 overflow-x-auto md:flex-col md:overflow-y-auto">
            {st.files.map((f) => (
              <button
                key={f.path}
                onClick={() => setFile(f.path)}
                className={cx(
                  'flex shrink-0 items-center gap-2 rounded-lg px-2.5 py-2 text-left font-mono text-[12.5px] transition-colors',
                  f.path === file ? 'bg-accent-soft text-ink' : 'text-ink-2 hover:bg-sunken',
                )}
              >
                <CircleDot className="size-3.5 shrink-0 text-merge" />
                <span className="[overflow-wrap:anywhere]">{f.path}</span>
                {f.markers > 0 && <span className="ml-auto text-ink-3">{f.markers}</span>}
              </button>
            ))}
            {st.resolved.map((p) => (
              <div key={p} className="flex shrink-0 items-center gap-2 px-2.5 py-2 font-mono text-[12.5px] text-ink-3">
                <CheckCircle2 className="size-3.5 shrink-0 text-done" />
                <span className="[overflow-wrap:anywhere]">{p}</span>
              </div>
            ))}
          </nav>
          <section className="flex min-h-[55dvh] min-w-0 flex-col gap-3 md:min-h-0">
            {total === 0 ? (
              <div className="flex flex-1 flex-col items-center justify-center rounded-2xl border border-dashed border-line-strong p-8 text-center">
                <CheckCircle2 className="size-8 text-done" />
                <h3 className="mt-3 text-[15px] font-semibold text-ink">All conflicts resolved</h3>
                <p className="mt-1 max-w-md text-sm text-ink-2">
                  Finish & merge lands the task in <code className="font-mono">{base}</code> now. Finish & re-verify runs the checks and verifier on the combined code first, which is safer if you edited code by hand.
                </p>
              </div>
            ) : !fd ? (
              <Skeleton className="flex-1" />
            ) : (
              <FilePane fd={fd} base={base} tab={tab} setTab={setTab} editing={editing} setEditing={setEditing} draft={draft} setDraft={setDraft} busy={busy}
                onKeep={(mode) => op('keep', { project, task, op: 'resolve', path: fd.path, mode }, () => toast(`${fd.path} resolved`))}
                onSave={() => op('save', { project, task, op: 'resolve', path: fd.path, mode: 'content', content: draft }, () => toast(`${fd.path} saved`))}
              />
            )}
          </section>
        </div>
      )}
    </Dialog>
  )
}

function FilePane(props: {
  fd: ConflictFile
  base: string
  tab: 'combined' | 'ours' | 'theirs'
  setTab: (t: 'combined' | 'ours' | 'theirs') => void
  editing: boolean
  setEditing: (b: boolean) => void
  draft: string
  setDraft: (s: string) => void
  busy: string | null
  onKeep: (m: 'ours' | 'theirs') => void
  onSave: () => void
}) {
  const { fd, base, tab, setTab, editing, setEditing, draft, setDraft, busy, onKeep, onSave } = props
  const oursGone = fd.ours == null
  const theirsGone = fd.theirs == null
  const canCombine = !fd.binary && fd.working != null
  const items = [
    ...(canCombine ? [{ value: 'combined', label: 'Combined' }] : []),
    { value: 'ours', label: oursGone ? "Task's version (deleted)" : "Task's version" },
    { value: 'theirs', label: theirsGone ? `${base} (deleted)` : `${base}'s version` },
  ]
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <FileWarning className="size-4 text-merge" />
        <span className="font-mono text-sm text-ink [overflow-wrap:anywhere]">{fd.path}</span>
      </div>
      <Tabs value={tab} onValueChange={(v) => setTab(v as never)} items={items} />
      <div className="min-h-0 flex-1">
        {tab === 'combined' &&
          (editing ? (
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              spellCheck={false}
              className="h-full min-h-[45dvh] resize-none font-mono text-[12.5px] leading-[1.6] whitespace-pre"
            />
          ) : (
            <Highlighted text={fd.working ?? ''} />
          ))}
        {tab === 'ours' && (oursGone ? <p className="text-sm text-ink-2">The task deleted this file.</p> : <Code className="h-full">{fd.ours!}</Code>)}
        {tab === 'theirs' && (theirsGone ? <p className="text-sm text-ink-2">{base} deleted this file.</p> : <Code className="h-full">{fd.theirs!}</Code>)}
      </div>
      {tab === 'combined' && !editing && (
        <p className="text-xs text-ink-3">
          <span className="mr-3 inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-live" /> task's lines</span>
          <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-done" /> {base}'s lines</span>
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" busy={busy === 'keep'} onClick={() => onKeep('ours')}>
          {oursGone ? 'Delete, as the task did' : "Keep task's version"}
        </Button>
        <Button size="sm" busy={busy === 'keep'} onClick={() => onKeep('theirs')}>
          {theirsGone ? `Delete, as ${base} did` : `Keep ${base}'s version`}
        </Button>
        {canCombine &&
          (editing ? (
            <>
              <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setDraft(fd.working ?? '') }}>
                Cancel edit
              </Button>
              <Button size="sm" variant="primary" busy={busy === 'save'} onClick={onSave}>
                Save this file
              </Button>
            </>
          ) : (
            <Button size="sm" icon={<Pencil className="size-3.5" />} onClick={() => { setTab('combined'); setEditing(true) }}>
              Edit by hand
            </Button>
          ))}
      </div>
    </>
  )
}
