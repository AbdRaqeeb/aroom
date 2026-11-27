import { useSyncExternalStore } from 'react'
import type { Problem } from './types'

export type Overlay =
  | { kind: 'fix'; problem: Pick<Problem, 'project' | 'task' | 'kind'> }
  | { kind: 'conflict'; project: string; task: string }
  | { kind: 'models'; project: string }
  | { kind: 'resume'; project: string; task: string }
  | { kind: 'add' }
  | { kind: 'session'; id: string }
  | null

let overlay: Overlay = null
const listeners = new Set<() => void>()

export function openOverlay(next: Overlay) {
  overlay = next
  listeners.forEach((l) => l())
}
export const closeOverlay = () => openOverlay(null)

export function useOverlay(): Overlay {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => overlay,
  )
}
