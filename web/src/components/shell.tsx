import { Link, Outlet, useNavigate, useSearch } from '@tanstack/react-router'
import { Activity, Bell, BellOff, FolderGit2, Inbox, LayoutDashboard, LogOut, Monitor, Moon, Plus, Sun } from 'lucide-react'
import type { ReactNode } from 'react'
import { allProblems, isRunning, towerRows, useAppState, useProblemAlerts, useTheme } from '@/lib/hooks'
import { toast, Toaster } from '@/lib/toast'
import { closeOverlay, openOverlay, useOverlay } from '@/lib/ui-store'
import { ConflictResolver } from './conflicts'
import { AddProjectDialog, ModelsDialog, ResumeDialog, SessionDialog } from './dialogs'
import { FixDialog } from './problems'
import { RunSheet } from './run-sheet'
import { IconButton, cx } from './ui'

function Mark() {
  return (
    <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
      <rect width="32" height="32" rx="8" className="fill-ink" />
      <path d="M8 22V10M13 22V10M18 22V14M23 22V18" className="stroke-bg" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  )
}

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, exact: true },
  { to: '/inbox', label: 'Needs you', icon: Inbox, badge: true },
  { to: '/activity', label: 'Activity', icon: Activity },
  { to: '/projects', label: 'Projects', icon: FolderGit2 },
] as const

function ThemeSwitch() {
  const [theme, setTheme] = useTheme()
  const opts = [
    ['system', Monitor, 'Match system'],
    ['light', Sun, 'Light'],
    ['dark', Moon, 'Dark'],
  ] as const
  return (
    <div className="inline-flex rounded-lg border border-line p-0.5" role="radiogroup" aria-label="Theme">
      {opts.map(([v, Icon, label]) => (
        <button
          key={v}
          role="radio"
          aria-checked={theme === v}
          title={label}
          aria-label={label}
          onClick={() => setTheme(v)}
          className={cx('inline-flex size-7 items-center justify-center rounded-md text-ink-3 hover:text-ink', theme === v && 'bg-surface text-ink shadow-[0_1px_2px_oklch(0.2_0.02_260/0.12)]')}
        >
          <Icon className="size-3.5" />
        </button>
      ))}
    </div>
  )
}

export function Shell() {
  const { data } = useAppState()
  const problems = allProblems(data)
  const alerts = useProblemAlerts(problems)
  const search = useSearch({ strict: false }) as { run?: string }
  const navigate = useNavigate()

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[248px_1fr]">
      {/* Sidebar (desktop) */}
      <aside className="sticky top-0 hidden h-dvh flex-col border-r border-line bg-rail md:flex">
        <div className="flex items-center gap-2.5 px-5 pt-5 pb-6">
          <Mark />
          <span className="text-[15px] font-semibold tracking-[-0.01em] text-ink">Agent Room</span>
        </div>
        <nav className="space-y-0.5 px-3">
          {NAV.map((n) => (
            <NavItem key={n.to} to={n.to} exact={'exact' in n} icon={<n.icon className="size-[18px]" />} label={n.label} count={'badge' in n ? problems.length : undefined} />
          ))}
        </nav>
        <div className="mt-7 flex items-center px-5 pb-1.5">
          <span className="text-xs font-medium text-ink-3">Projects</span>
          <IconButton label="Add project" className="ml-auto size-7" onClick={() => openOverlay({ kind: 'add' })}>
            <Plus className="size-4" />
          </IconButton>
        </div>
        <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-3">
          {(data?.projects ?? []).map((p) => {
            const n = p.problems?.length ?? 0
            const live = isRunning(p)
            return (
              <Link
                key={p.name}
                to="/projects/$name"
                params={{ name: p.name }}
                className="flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-sm text-ink-2 hover:bg-sunken hover:text-ink [&.active]:bg-surface [&.active]:font-medium [&.active]:text-ink [&.active]:shadow-[0_1px_2px_oklch(0.2_0.02_260/0.08)]"
              >
                <span className={cx('size-2 shrink-0 rounded-full', live ? 'bg-live [animation:sector-pulse_1.8s_ease-in-out_infinite]' : p.configured ? 'bg-line-strong' : 'border border-dashed border-ink-3')} />
                <span className="truncate">{p.name}</span>
                {n > 0 && <span className="tnum ml-auto rounded-md bg-wait-soft px-1.5 text-xs font-medium text-warn-ink">{n}</span>}
              </Link>
            )
          })}
        </div>
        <div className="space-y-3 border-t border-line px-5 py-4">
          {data && (
            <div className="flex items-center gap-2 text-[13px] text-ink-2" title={data.supervisor.alive ? 'Keeps loops running and recovers failures' : 'Start it with: aroom supervise --detach'}>
              <span className={cx('size-2 rounded-full', data.supervisor.alive ? 'bg-done' : 'bg-bad')} />
              Supervisor {data.supervisor.alive ? 'running' : 'stopped'}
            </div>
          )}
          <div className="flex items-center gap-1.5">
            <ThemeSwitch />
            {alerts.supported && (
              <IconButton
                label={alerts.enabled ? 'Turn off notifications' : 'Notify me when something needs me'}
                className="size-8"
                onClick={async () => {
                  const r = await alerts.toggle()
                  if (r === 'denied') toast('Notifications are blocked for this site in your browser settings.', true)
                  else if (r === 'on') toast("You'll get a notification when something new needs you")
                }}
              >
                {alerts.enabled ? <Bell className="size-4 text-accent" /> : <BellOff className="size-4" />}
              </IconButton>
            )}
            {data?.auth && (
              <form method="post" action="/logout" className="ml-auto">
                <IconButton label="Sign out" className="size-8" type="submit">
                  <LogOut className="size-4" />
                </IconButton>
              </form>
            )}
          </div>
        </div>
      </aside>

      {/* Phone top bar */}
      <header className="sticky top-0 z-30 flex items-center gap-2.5 border-b border-line bg-bg/90 px-4 pt-[max(10px,env(safe-area-inset-top))] pb-2.5 backdrop-blur-md md:hidden">
        <Mark />
        <span className="text-[15px] font-semibold text-ink">Agent Room</span>
        {data && (
          <span className="ml-auto flex items-center gap-1.5 text-xs text-ink-2">
            <span className={cx('size-2 rounded-full', data.supervisor.alive ? 'bg-done' : 'bg-bad')} />
            {towerRows(data.projects).filter((r) => r.lane === 'live').length} running
          </span>
        )}
        <span className={data ? '' : 'ml-auto'}>
          <ThemeSwitch />
        </span>
      </header>

      <main className="min-w-0 pb-[calc(84px+env(safe-area-inset-bottom))] md:pb-16">
        <Outlet />
      </main>

      {/* Phone tab bar */}
      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-line bg-bg/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden">
        {NAV.map((n) => (
          <Link
            key={n.to}
            to={n.to}
            activeOptions={{ exact: 'exact' in n }}
            className="relative flex h-[60px] flex-col items-center justify-center gap-1 text-[11px] text-ink-3 [&.active]:font-medium [&.active]:text-ink"
          >
            <n.icon className="size-[22px]" />
            {n.label}
            {'badge' in n && problems.length > 0 && (
              <span className="tnum absolute top-1.5 left-[calc(50%+6px)] min-w-[18px] rounded-full bg-wait px-1 text-center text-[11px] leading-[18px] font-semibold text-[oklch(0.25_0.05_80)]">
                {problems.length}
              </span>
            )}
          </Link>
        ))}
      </nav>

      <Overlays />
      {search.run && (
        <RunSheet
          key={search.run}
          id={search.run}
          onClose={() => navigate({ to: '.', search: (prev: Record<string, unknown>) => ({ ...prev, run: undefined }) } as never)}
        />
      )}
      <Toaster />
    </div>
  )
}

function NavItem({ to, icon, label, count, exact }: { to: string; icon: ReactNode; label: string; count?: number; exact?: boolean }) {
  return (
    <Link
      to={to}
      activeOptions={{ exact: !!exact }}
      className="flex h-9 items-center gap-3 rounded-lg px-2.5 text-sm text-ink-2 transition-colors hover:bg-sunken hover:text-ink [&.active]:bg-surface [&.active]:font-medium [&.active]:text-ink [&.active]:shadow-[0_1px_2px_oklch(0.2_0.02_260/0.08)]"
    >
      {icon}
      {label}
      {!!count && <span className="tnum ml-auto rounded-md bg-wait px-1.5 text-xs font-semibold text-[oklch(0.25_0.05_80)]">{count}</span>}
    </Link>
  )
}

function Overlays() {
  const o = useOverlay()
  if (!o) return null
  if (o.kind === 'fix') return <FixDialog problem={o.problem} onClose={closeOverlay} />
  if (o.kind === 'conflict') return <ConflictResolver project={o.project} task={o.task} onClose={closeOverlay} />
  if (o.kind === 'models') return <ModelsDialog project={o.project} onClose={closeOverlay} />
  if (o.kind === 'resume') return <ResumeDialog project={o.project} task={o.task} onClose={closeOverlay} />
  if (o.kind === 'add') return <AddProjectDialog onClose={closeOverlay} />
  if (o.kind === 'session') return <SessionDialog id={o.id} onClose={closeOverlay} />
  return null
}

export function PageHeader({ title, sub, children }: { title: ReactNode; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-7 flex flex-wrap items-end gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="text-[26px] leading-tight font-semibold tracking-[-0.02em] text-ink">{title}</h1>
        {sub && <div className="mt-1 text-sm text-ink-2">{sub}</div>}
      </div>
      {children && <div className="ml-auto flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  )
}

export function Page({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return <div className={cx('mx-auto px-4 pt-6 md:px-10 md:pt-10', wide ? 'max-w-[1400px]' : 'max-w-[1180px]')}>{children}</div>
}
