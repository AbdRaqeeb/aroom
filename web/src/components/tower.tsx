import { useNavigate } from '@tanstack/react-router'
import { GitMerge } from 'lucide-react'
import { ago, dur, money, prettyModel } from '@/lib/format'
import type { TowerRow } from '@/lib/hooks'
import { api } from '@/lib/api'
import { toast } from '@/lib/toast'
import { useRefresh } from '@/lib/hooks'
import { Button, PipelineBar, StateBadge, StateMark, cx } from './ui'

const LANE_TITLE: Record<TowerRow['lane'], string> = {
  live: 'On track',
  attention: 'Ready to merge',
  waiting: 'Built, waiting for a verifier',
  queued: 'Queued for a builder',
  done: 'Finished recently',
}

export function useOpenRun() {
  const navigate = useNavigate()
  return (project: string, task: string) =>
    navigate({ to: '.', search: (prev: Record<string, unknown>) => ({ ...prev, run: `${project}/${task}` }) } as never)
}

export function Tower({ rows, showProject = true }: { rows: TowerRow[]; showProject?: boolean }) {
  const lanes = (['live', 'attention', 'waiting', 'queued', 'done'] as const).map((lane) => ({
    lane,
    rows: rows.filter((r) => r.lane === lane),
  }))
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface">
      <div
        className="tower-grid hidden border-b border-line px-4 py-2 text-xs font-medium text-ink-3 md:grid md:items-center md:gap-4"
      >
        <span>Task</span>
        <span className="flex gap-[3px]">
          {['brief', 'build', 'check', 'verify', 'merge'].map((st) => (
            <span key={st} className="flex-1 truncate font-normal">{st}</span>
          ))}
        </span>
        <span>Step</span>
        <span className="text-right">Time</span>
        <span>Model</span>
        <span className="text-right">Cost</span>
      </div>
      {lanes.map(({ lane, rows }) =>
        rows.length ? (
          <section key={lane}>
            <h3 className="flex items-center gap-2 border-b border-line bg-sunken/60 px-4 py-1.5 text-xs font-medium text-ink-2">
              {LANE_TITLE[lane]}
              <span className="tnum text-ink-3">{rows.length}</span>
            </h3>
            {lane === 'queued' ? (
              <QueuedLine rows={rows} showProject={showProject} />
            ) : (
              rows.map((r) => <TowerRowView key={`${r.project}:${r.run.task}`} row={r} showProject={showProject} />)
            )}
          </section>
        ) : null,
      )}
    </div>
  )
}

function TowerRowView({ row, showProject }: { row: TowerRow; showProject: boolean }) {
  const open = useOpenRun()
  const refresh = useRefresh()
  const r = row.run
  const model = /verif/.test(r.state) ? r.verifier_model || r.verifier_runner : r.builder_model || r.builder_runner
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => open(row.project, r.task)}
      onKeyDown={(e) => e.key === 'Enter' && open(row.project, r.task)}
      className={cx(
        'tower-grid grid cursor-pointer gap-x-4 gap-y-2 border-b border-line px-4 py-3 transition-colors last:border-b-0 hover:bg-sunken/70 md:items-center',
        row.lane === 'done' && 'opacity-70',
      )}
    >
      <div className="flex min-w-0 items-start gap-2.5">
        <span className="pt-1.5">
          <StateMark state={r.stalled ? 'stalled' : r.state} />
        </span>
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            {showProject && <span className="text-[13px] text-ink-3">{row.project}</span>}
            <span className="font-mono text-[13px] font-medium text-ink">{r.task}</span>
          </div>
          <p className="truncate text-sm text-ink-2">{r.title || r.last_event || ''}</p>
        </div>
      </div>
      <PipelineBar run={r} className="md:pt-0.5" />
      <div className="flex min-w-0 items-center gap-2 text-sm text-ink-2">
        <span className="md:hidden">
          <StateBadge state={r.state} stalled={r.stalled} />
        </span>
        <span className="truncate">
          {row.lane === 'done' ? `Merged ${ago(r.finished)}` : r.step || ''}
          {r.round && r.round > 1 ? <span className="text-ink-3"> · round {r.round}</span> : null}
        </span>
        {row.lane === 'attention' && (
          <Button
            size="sm"
            variant="primary"
            className="ml-auto md:ml-2"
            icon={<GitMerge className="size-3.5" />}
            onClick={async (e) => {
              e.stopPropagation()
              try {
                await api.merge(row.project, r.task)
                toast(`${r.task} merged`)
                refresh()
              } catch (err) {
                toast((err as Error).message, true)
              }
            }}
          >
            Merge
          </Button>
        )}
      </div>
      <span className="tnum hidden text-right text-sm text-ink-2 md:block">{dur(r.elapsed_s)}</span>
      <span className="hidden truncate text-[13px] text-ink-3 md:block">{prettyModel(model)}</span>
      <span className="tnum hidden text-right text-[13px] text-ink-3 md:block">{r.cost_usd ? money(r.cost_usd) : '—'}</span>
      <div className="tnum flex gap-3 text-xs text-ink-3 md:hidden">
        <span>{dur(r.elapsed_s)}</span>
        <span>{prettyModel(model)}</span>
        {r.cost_usd ? <span>{money(r.cost_usd)}</span> : null}
      </div>
    </div>
  )
}

function QueuedLine({ rows, showProject }: { rows: TowerRow[]; showProject: boolean }) {
  const open = useOpenRun()
  return (
    <div className="flex flex-wrap gap-x-1 gap-y-1 border-b border-line px-3 py-2.5 last:border-b-0">
      {rows.map((r) => (
        <button
          key={`${r.project}:${r.run.task}`}
          onClick={() => open(r.project, r.run.task)}
          title={r.run.title}
          className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[13px] text-ink-2 hover:bg-sunken hover:text-ink"
        >
          <span className="inline-block h-3 border-l border-dashed border-ink-3" />
          {showProject && <span className="text-ink-3">{r.project}</span>}
          <span className="font-mono">{r.run.task}</span>
        </button>
      ))}
    </div>
  )
}
