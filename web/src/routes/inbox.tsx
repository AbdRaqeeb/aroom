import { Inbox } from 'lucide-react'
import { useMemo, useState } from 'react'
import { ProblemStack } from '@/components/problems'
import { Page, PageHeader } from '@/components/shell'
import { Chip, Empty } from '@/components/ui'
import { KIND_LABEL } from '@/lib/format'
import { allProblems, useAppState } from '@/lib/hooks'
import type { ProblemKind } from '@/lib/types'
import { Loading } from './overview'

const GROUPS: { id: string; label: string; kinds: ProblemKind[] }[] = [
  { id: 'merge', label: 'Merging', kinds: ['merge-conflict', 'integration-failed', 'merge-hook', 'dirty-base', 'push-failed'] },
  { id: 'review', label: 'Rejected work', kinds: ['verification-failed', 'checks-failed', 'needs-human'] },
  { id: 'failed', label: 'Failures', kinds: ['build-failed', 'quota', 'budget', 'stalled', 'stopped'] },
  { id: 'blocked', label: 'Blocked', kinds: ['blocked'] },
]

export function InboxPage() {
  const { data, isLoading } = useAppState()
  const [project, setProject] = useState('')
  const [group, setGroup] = useState('')
  const problems = useMemo(() => allProblems(data), [data])
  if (isLoading || !data) return <Loading />
  const projects = [...new Set(problems.map((p) => p.project))]
  const kinds = GROUPS.find((g) => g.id === group)?.kinds
  const shown = problems.filter((p) => (!project || p.project === project) && (!kinds || kinds.includes(p.kind)))
  const questions = problems.filter((p) => p.question).length

  return (
    <Page>
      <PageHeader
        title="Needs you"
        sub={
          problems.length
            ? `${problems.length} waiting${questions ? ` · ${questions} question${questions === 1 ? '' : 's'} from agents` : ''}. Everything else keeps running.`
            : 'Nothing is waiting on you.'
        }
      />
      {problems.length > 0 && (
        <div className="mb-5 flex flex-wrap gap-2">
          <Chip active={!project && !group} onClick={() => { setProject(''); setGroup('') }}>
            All <span className="tnum opacity-60">{problems.length}</span>
          </Chip>
          {GROUPS.map((g) => {
            const n = problems.filter((p) => g.kinds.includes(p.kind)).length
            return n ? (
              <Chip key={g.id} active={group === g.id} onClick={() => setGroup(group === g.id ? '' : g.id)}>
                {g.label} <span className="tnum opacity-60">{n}</span>
              </Chip>
            ) : null
          })}
          {projects.length > 1 && <span className="mx-1 w-px self-stretch bg-line" />}
          {projects.length > 1 &&
            projects.map((name) => (
              <Chip key={name} active={project === name} onClick={() => setProject(project === name ? '' : name)}>
                {name}
              </Chip>
            ))}
        </div>
      )}
      {shown.length ? (
        <ProblemStack problems={shown} />
      ) : (
        <Empty icon={<Inbox className="size-7" />} title={problems.length ? 'Nothing matches these filters' : 'Inbox zero'}>
          When an agent hits something it can't solve (a merge conflict, a rejected review, a failing check, a question), it lands here
          with the reason, the evidence and the fix. Types you might see: {Object.values(KIND_LABEL).slice(0, 6).join(', ').toLowerCase()}.
        </Empty>
      )}
    </Page>
  )
}
