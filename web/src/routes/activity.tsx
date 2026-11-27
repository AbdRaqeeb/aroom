import { useQuery } from '@tanstack/react-query'
import { Activity as ActivityIcon } from 'lucide-react'
import { useState } from 'react'
import { Page, PageHeader } from '@/components/shell'
import { useOpenRun } from '@/components/tower'
import { Button, Chip, Empty, Select, Skeleton, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { clock, dayLabel } from '@/lib/format'
import { useAppState } from '@/lib/hooks'
import type { ActivityEvent } from '@/lib/types'

const FILTERS = [
  { id: '', label: 'Everything' },
  { id: 'good', label: 'Merged & passed' },
  { id: 'trouble', label: 'Problems' },
  { id: 'info', label: 'Progress' },
] as const

const TONE_COLOR = { good: 'var(--done)', bad: 'var(--bad)', warn: 'var(--wait)', info: 'var(--ink-3)' }

export function ActivityPage() {
  const { data: state } = useAppState()
  const [project, setProject] = useState('')
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['id']>('')
  const [limit, setLimit] = useState(120)
  const { data, isLoading } = useQuery({
    queryKey: ['activity', project],
    queryFn: () => api.activity(project, 400),
    refetchInterval: 10_000,
  })
  const open = useOpenRun()
  const matching = (data?.events ?? []).filter((e) =>
    !filter ? true : filter === 'trouble' ? e.tone === 'bad' || e.tone === 'warn' : e.tone === filter,
  )
  const events = matching.slice(0, limit)
  const days: [string, ActivityEvent[]][] = []
  for (const e of events) {
    const d = dayLabel(e.ts)
    const last = days[days.length - 1]
    if (last && last[0] === d) last[1].push(e)
    else days.push([d, [e]])
  }

  return (
    <Page>
      <PageHeader title="Activity" sub="Every pipeline milestone across your projects, newest first." />
      <div className="mb-6 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <Chip key={f.id} active={filter === f.id} onClick={() => setFilter(f.id)}>
            {f.label}
          </Chip>
        ))}
        <div className="ml-auto w-full sm:w-48">
          <Select value={project} onChange={setProject} aria-label="Project">
            <option value="">All projects</option>
            {(state?.projects ?? []).filter((p) => p.configured).map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </Select>
        </div>
      </div>
      {isLoading && <Skeleton className="h-96" />}
      {!isLoading && !events.length && (
        <Empty icon={<ActivityIcon className="size-7" />} title="No activity yet">
          Starts, briefs, verdicts, merges, conflicts and failures from every run show up here.
        </Empty>
      )}
      <div className="space-y-8">
        {days.map(([day, list]) => (
          <section key={day}>
            <h2 className="sticky top-[57px] z-10 mb-1 bg-bg/95 py-2 text-[13px] font-semibold text-ink backdrop-blur md:top-0">{day}</h2>
            <ol className="relative">
              {list.map((e, i) => (
                <li key={i}>
                  <button
                    onClick={() => open(e.project, e.task)}
                    className="grid w-full grid-cols-[52px_14px_1fr] items-start gap-3 rounded-lg px-2 py-2 text-left hover:bg-sunken"
                  >
                    <span className="tnum pt-px text-[13px] text-ink-3">{clock(e.ts)}</span>
                    <span className="flex justify-center pt-[5px]">
                      <span
                        className={cx('block h-3', e.tone === 'info' ? 'border-l border-dashed' : e.tone === 'good' ? 'w-[3px] rounded-full' : 'w-[5px] border-x')}
                        style={e.tone === 'good' ? { background: TONE_COLOR.good } : { borderColor: TONE_COLOR[e.tone] }}
                      />
                    </span>
                    <span className="min-w-0">
                      <span className="text-[13px] text-ink-3">{e.project} </span>
                      <span className="font-mono text-[13px] font-medium text-ink">{e.task}</span>
                      <span className={cx('block text-sm [overflow-wrap:anywhere]', e.tone === 'bad' ? 'text-bad' : e.tone === 'good' ? 'text-ink' : 'text-ink-2')}>
                        {e.text}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          </section>
        ))}
      </div>
      {matching.length > events.length && (
        <div className="mt-6 flex justify-center">
          <Button onClick={() => setLimit(limit + 200)}>Show more</Button>
        </div>
      )}
    </Page>
  )
}
