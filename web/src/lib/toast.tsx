import { CheckCircle2, CircleAlert } from 'lucide-react'
import { useSyncExternalStore } from 'react'

interface Toast {
  id: number
  text: string
  bad?: boolean
}

let toasts: Toast[] = []
let seq = 0
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())

export function toast(text: string, bad = false) {
  const id = ++seq
  toasts = [...toasts, { id, text: text.split('\n')[0].slice(0, 220), bad }].slice(-4)
  emit()
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id)
    emit()
  }, bad ? 6500 : 3800)
}

export function Toaster() {
  const list = useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => toasts,
  )
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-3 bottom-[calc(76px+env(safe-area-inset-bottom))] z-[80] flex flex-col items-center gap-2 md:inset-x-auto md:right-5 md:bottom-5 md:items-end"
    >
      {list.map((t) => (
        <div
          key={t.id}
          role={t.bad ? 'alert' : 'status'}
          className="pointer-events-auto flex max-w-md items-start gap-2.5 rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm text-ink shadow-pop [animation:sheet-in_.25s_var(--ease-out-expo)]"
        >
          {t.bad ? (
            <CircleAlert className="mt-0.5 size-4 shrink-0 text-bad" />
          ) : (
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-done" />
          )}
          <span>{t.text}</span>
        </div>
      ))}
    </div>
  )
}
