import { Link } from '@tanstack/react-router'
import { ArrowRight, CircleCheck, Radio } from 'lucide-react'
import { ProblemStack, stackCount } from '@/components/problems'
import { Page, PageHeader } from '@/components/shell'
import { Tower } from '@/components/tower'
import { Button, Empty, SectionHead, Skeleton } from '@/components/ui'
import { ago, money, shortPath } from '@/lib/format'
import { allProblems, towerRows, useAppState } from '@/lib/hooks'
import { openOverlay } from '@/lib/ui-store'

export function OverviewPage() {
  const { data, isLoading } = useAppState()
  if (isLoading || !data) return <Loading />
  const problems = allProblems(data)
  const rows = towerRows(data.projects, { recent: true })
  const live = rows.filter((r) => r.lane === 'live').length
  const queued = rows.filter((r) => r.lane === 'queued').length
  const ready = rows.filter((r) => r.lane === 'attention').length

  return (
    <Page>
      <PageHeader
        title={problems.length ? `${problems.length} thing${problems.length === 1 ? '' : 's'} need${problems.length === 1 ? 's' : ''} you` : 'All clear'}
        sub={
          <span className="tnum">
            {live} running · {queued} queued{ready ? ` · ${ready} ready to merge` : ''} · {data.totals.todo} open tasks · {money(data.totals.cost_today)} today
          </span>
        }
      />

      {problems.length > 0 ? (
        <section aria-label="Needs you">
          <ProblemStack problems={problems} limit={4} />
          {stackCount(problems) > 4 && (
            <Link to="/inbox" className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline">
              See all {problems.length} in Needs you <ArrowRight className="size-4" />
            </Link>
          )}
        </section>
      ) : (
        <div className="flex items-center gap-3 rounded-2xl border border-line bg-surface px-5 py-4 text-sm text-ink-2">
          <CircleCheck className="size-5 text-done" />
          Nothing is waiting on you. The agents will put anything they can't solve here.
        </div>
      )}

      <SectionHead title="Timing tower" count={rows.length}>
        <span className="hidden text-xs text-ink-3 md:inline">Updated {ago(data.generated)}</span>
      </SectionHead>
      {rows.length ? (
        <Tower rows={rows} />
      ) : (
        <Empty icon={<Radio className="size-7" />} title="No agents are working right now">
          Open a project and press <b>Start loop</b>, or run a single task. Running work shows up here with its pipeline.
        </Empty>
      )}

      {data.external.length > 0 && (
        <>
          <SectionHead title="Live sessions outside your projects" count={data.external.length} />
          <div className="divide-y divide-line rounded-2xl border border-line bg-surface">
            {data.external.map((s) => (
              <div key={s.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <span className={s.busy ? 'size-2 rounded-full bg-live [animation:sector-pulse_1.8s_ease-in-out_infinite]' : 'size-2 rounded-full bg-line-strong'} />
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-[13px] text-ink">{shortPath(s.cwd)}</p>
                  <p className="truncate text-sm text-ink-3">{s.last_text || s.last_tool || s.model}</p>
                </div>
                <Button size="sm" variant="ghost" onClick={() => openOverlay({ kind: 'session', id: s.id })}>
                  Open
                </Button>
              </div>
            ))}
          </div>
        </>
      )}
    </Page>
  )
}

export function Loading() {
  return (
    <Page>
      <Skeleton className="mb-3 h-8 w-64" />
      <Skeleton className="mb-10 h-4 w-80" />
      <Skeleton className="mb-4 h-36" />
      <Skeleton className="h-72" />
    </Page>
  )
}
