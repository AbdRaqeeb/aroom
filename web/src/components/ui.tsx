import { Dialog as RDialog, Tabs as RTabs } from 'radix-ui'
import { Check, Copy, Loader2, X } from 'lucide-react'
import {
  forwardRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react'
import { KIND_LABEL, STAGES, STATE_LABEL, kindTone, sectors, stateTone, type Sector } from '@/lib/format'
import type { ProblemKind, Run } from '@/lib/types'

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(' ')
}

// ---------------------------------------------------------------- buttons
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'quiet'
type Size = 'sm' | 'md'

const variants: Record<Variant, string> = {
  primary:
    'bg-accent text-accent-ink border-transparent hover:brightness-110 active:brightness-95 shadow-[0_1px_2px_oklch(0.2_0.02_260/0.18)]',
  secondary: 'bg-surface text-ink border-line-strong hover:bg-sunken active:bg-line/60',
  ghost: 'bg-transparent text-ink-2 border-transparent hover:bg-sunken hover:text-ink',
  danger: 'bg-surface text-bad border-line-strong hover:bg-bad-soft hover:border-bad/40',
  quiet: 'bg-transparent text-accent border-transparent hover:underline px-0!',
}
const sizes: Record<Size, string> = {
  sm: 'h-8 px-3 text-[13px] gap-1.5 rounded-lg',
  md: 'h-10 px-4 text-sm gap-2 rounded-[10px]',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  busy?: boolean
  icon?: ReactNode
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', busy, icon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || busy}
      className={cx(
        'inline-flex shrink-0 items-center justify-center border font-medium whitespace-nowrap transition-[background,filter,border-color,color] duration-150 select-none disabled:cursor-not-allowed disabled:opacity-50',
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {busy ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  )
})

export function IconButton({
  label,
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      aria-label={label}
      title={label}
      className={cx(
        'inline-flex size-9 items-center justify-center rounded-lg text-ink-2 transition-colors hover:bg-sunken hover:text-ink disabled:opacity-40',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}

// ---------------------------------------------------------------- badges
const toneClasses = {
  live: 'text-live bg-live-soft',
  done: 'text-done bg-done-soft',
  wait: 'text-warn-ink bg-wait-soft',
  bad: 'text-bad bg-bad-soft',
  merge: 'text-merge bg-merge-soft',
  idle: 'text-ink-2 bg-sunken',
}

export function Badge({ tone = 'idle', children, className }: { tone?: keyof typeof toneClasses; children: ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        'inline-flex h-6 shrink-0 items-center gap-1.5 rounded-md px-2 text-xs font-medium whitespace-nowrap',
        toneClasses[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function StateBadge({ state, stalled }: { state: string; stalled?: boolean }) {
  const tone = stalled ? 'wait' : stateTone(state)
  return (
    <Badge tone={tone}>
      <StateMark state={stalled ? 'stalled' : state} />
      {stalled ? 'Stalled' : (STATE_LABEL[state] ?? state)}
    </Badge>
  )
}

export function KindBadge({ kind }: { kind: ProblemKind }) {
  return <Badge tone={kindTone(kind)}>{KIND_LABEL[kind] ?? kind}</Badge>
}

/** State as line form: solid live, dashed waiting, struck stopped, doubled attention. */
export function StateMark({ state }: { state?: string }) {
  const tone = stateTone(state)
  const color = {
    live: 'var(--live)', done: 'var(--done)', wait: 'var(--wait)', bad: 'var(--bad)', merge: 'var(--merge)', idle: 'var(--ink-3)',
  }[tone]
  if (state === 'stopped') {
    return <span aria-hidden className="relative inline-block h-3 w-[3px]" style={{ background: color }}><span className="absolute top-1/2 -left-1 h-px w-[11px] -rotate-45" style={{ background: color }} /></span>
  }
  if (tone === 'wait' || tone === 'bad') {
    return <span aria-hidden className="inline-block h-3 w-[5px] border-x" style={{ borderColor: color }} />
  }
  if (tone === 'idle') {
    return <span aria-hidden className="inline-block h-3 w-0 border-l border-dashed" style={{ borderColor: color }} />
  }
  return (
    <span
      aria-hidden
      className={cx('inline-block h-3 w-[3px] rounded-full', tone === 'live' && '[animation:sector-pulse_1.8s_ease-in-out_infinite]')}
      style={{ background: color }}
    />
  )
}

// ---------------------------------------------------------------- pipeline bar (signature)
const sectorStyle: Record<Sector, string> = {
  done: 'bg-done',
  live: 'bg-live [animation:sector-pulse_1.8s_ease-in-out_infinite]',
  pending: 'border border-dashed border-line-strong bg-transparent',
  failed: 'bg-bad',
  stopped: 'bg-ink-3 opacity-60',
}

export function PipelineBar({ run, labels = false, className }: { run: Pick<Run, 'state' | 'step' | 'verdict' | 'checks'>; labels?: boolean; className?: string }) {
  const s = sectors(run)
  const current = s.findIndex((x) => x === 'live' || x === 'failed' || x === 'stopped')
  return (
    <div className={cx('min-w-0', className)} role="img" aria-label={`Pipeline: ${STAGES.map((st, i) => `${st} ${s[i]}`).join(', ')}`}>
      <div className="flex items-center gap-[3px]">
        {s.map((sector, i) => (
          <span
            key={i}
            className={cx(
              'h-[7px] flex-1 rounded-[2px] transition-colors duration-300',
              sectorStyle[sector],
              i === 4 && run.state === 'merging' && 'bg-merge!',
            )}
          />
        ))}
      </div>
      {labels && (
        <div className="mt-1.5 flex gap-[3px] text-[11px] text-ink-3">
          {STAGES.map((st, i) => (
            <span key={st} className={cx('flex-1 truncate', i === current && 'font-medium text-ink')}>
              {st}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- dialogs & sheets
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = 'md',
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  title: ReactNode
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
  size?: 'md' | 'lg' | 'xl' | 'full'
}) {
  const width = { md: 'md:max-w-lg', lg: 'md:max-w-3xl', xl: 'md:max-w-5xl', full: 'md:max-w-[1400px]' }[size]
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="fixed inset-0 z-50 bg-[oklch(0.15_0.01_260/0.45)] backdrop-blur-[2px] [animation:fade-in_.18s_ease-out]" />
        <RDialog.Content
          className={cx(
            'fixed inset-x-0 bottom-0 z-50 flex max-h-[94dvh] flex-col rounded-t-2xl border border-line bg-surface shadow-pop outline-none [animation:sheet-in_.28s_var(--ease-out-expo)]',
            'md:inset-x-auto md:top-1/2 md:bottom-auto md:left-1/2 md:max-h-[90vh] md:w-[calc(100vw-48px)] md:-translate-x-1/2 md:-translate-y-1/2 md:rounded-2xl',
            size === 'full' && 'md:h-[90vh]',
            width,
          )}
        >
          <div className="flex items-start gap-3 border-b border-line px-5 pt-5 pb-4">
            <div className="min-w-0 flex-1">
              <RDialog.Title className="text-[17px] leading-snug font-semibold tracking-[-0.01em] text-ink">{title}</RDialog.Title>
              {description ? (
                <RDialog.Description className="mt-1 text-sm text-ink-2">{description}</RDialog.Description>
              ) : (
                <RDialog.Description className="sr-only">Dialog</RDialog.Description>
              )}
            </div>
            <RDialog.Close asChild>
              <IconButton label="Close" className="-mt-1 -mr-2">
                <X className="size-[18px]" />
              </IconButton>
            </RDialog.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && (
            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-3 pb-[max(12px,env(safe-area-inset-bottom))]">
              {footer}
            </div>
          )}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  )
}

export function SideSheet({
  open,
  onOpenChange,
  children,
  label,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  children: ReactNode
  label: string
}) {
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="fixed inset-0 z-40 bg-[oklch(0.15_0.01_260/0.35)] [animation:fade-in_.18s_ease-out]" />
        <RDialog.Content
          aria-describedby={undefined}
          className="fixed inset-0 z-40 flex flex-col bg-surface shadow-pop outline-none [animation:sheet-in_.28s_var(--ease-out-expo)] md:inset-y-0 md:right-0 md:left-auto md:w-[min(920px,calc(100vw-80px))] md:border-l md:border-line md:[animation:side-in_.28s_var(--ease-out-expo)]"
        >
          <RDialog.Title className="sr-only">{label}</RDialog.Title>
          {children}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  )
}

export const SheetClose = RDialog.Close

// ---------------------------------------------------------------- tabs
export function Tabs({
  value,
  onValueChange,
  items,
  className,
}: {
  value: string
  onValueChange: (v: string) => void
  items: { value: string; label: ReactNode }[]
  className?: string
}) {
  return (
    <RTabs.Root value={value} onValueChange={onValueChange}>
      <RTabs.List className={cx('flex gap-1 overflow-x-auto border-b border-line [scrollbar-width:none]', className)}>
        {items.map((it) => (
          <RTabs.Trigger
            key={it.value}
            value={it.value}
            className="relative -mb-px flex h-10 shrink-0 items-center gap-1.5 border-b-2 border-transparent px-3 text-sm text-ink-2 transition-colors hover:text-ink data-[state=active]:border-accent data-[state=active]:font-medium data-[state=active]:text-ink"
          >
            {it.label}
          </RTabs.Trigger>
        ))}
      </RTabs.List>
    </RTabs.Root>
  )
}

// ---------------------------------------------------------------- misc
export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cx(
        'w-full resize-y rounded-[10px] border border-line-strong bg-bg px-3 py-2.5 text-sm text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none',
        props.className,
      )}
    />
  )
}

export function Code({ children, className }: { children: string; className?: string }) {
  return (
    <pre
      className={cx(
        'overflow-auto rounded-[10px] border border-line bg-sunken p-3 font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap text-ink-2 [overflow-wrap:anywhere]',
        className,
      )}
    >
      {children}
    </pre>
  )
}

export function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <IconButton
      label={done ? 'Copied' : 'Copy'}
      className="size-8"
      onClick={async (e) => {
        e.preventDefault()
        e.stopPropagation()
        try {
          await navigator.clipboard.writeText(text)
          setDone(true)
          setTimeout(() => setDone(false), 1500)
        } catch {
          /* clipboard blocked (http) */
        }
      }}
    >
      {done ? <Check className="size-4 text-done" /> : <Copy className="size-4" />}
    </IconButton>
  )
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-line-strong px-6 py-14 text-center">
      <div className="mb-3 text-ink-3">{icon}</div>
      <h3 className="text-[15px] font-semibold text-ink">{title}</h3>
      {children && <div className="mt-1.5 max-w-md text-sm text-ink-2">{children}</div>}
    </div>
  )
}

export function SectionHead({ title, count, children }: { title: string; count?: number; children?: ReactNode }) {
  return (
    <div className="mt-9 mb-3 flex items-center gap-2 first:mt-0">
      <h2 className="text-[15px] font-semibold tracking-[-0.005em] text-ink">{title}</h2>
      {count !== undefined && <span className="tnum text-sm text-ink-3">{count}</span>}
      <div className="ml-auto flex items-center gap-2">{children}</div>
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx('animate-pulse rounded-lg bg-sunken', className)} />
}

export function Chip({ active, onClick, children }: { active?: boolean; onClick?: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={cx(
        'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors',
        active ? 'border-ink bg-ink text-bg' : 'border-line-strong text-ink-2 hover:border-ink-3 hover:text-ink',
      )}
    >
      {children}
    </button>
  )
}

export function Select({
  value,
  onChange,
  children,
  className,
  ...rest
}: { value: string; onChange: (v: string) => void; children: ReactNode; className?: string } & Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'onChange' | 'value'>) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cx(
        'h-10 w-full rounded-[10px] border border-line-strong bg-bg px-3 text-sm text-ink focus:border-accent focus:outline-none',
        className,
      )}
      {...rest}
    >
      {children}
    </select>
  )
}
