export type RunState =
  | 'queued'
  | 'briefing'
  | 'researching'
  | 'building'
  | 'checking'
  | 'verifying'
  | 'fixing'
  | 'built'
  | 'merging'
  | 'passed'
  | 'merged'
  | 'needs-human'
  | 'failed'
  | 'stopped'

export interface CheckInfo {
  state: 'pass' | 'fail' | 'run' | string
  exit?: number
  duration_s?: number
  log?: string
  tail?: string
}

export interface Run {
  run_id: string
  kind: string
  project: string
  task: string
  title?: string
  state: RunState
  step?: string
  round?: number
  started?: string
  updated?: string
  finished?: string | null
  branch?: string
  base_branch?: string
  pid?: number
  cost_usd?: number
  checks?: Record<string, CheckInfo>
  verdict?: 'PASS' | 'FAIL' | null
  error?: string | null
  error_detail?: string
  merge?: { sha: string; ticked?: boolean; at?: string } | null
  files_changed?: number | null
  insertions?: number | null
  deletions?: number | null
  commits?: number | null
  last_event?: string
  run_dir?: string
  worktree?: string
  output?: string | null
  research?: string | null
  builder_runner?: string
  builder_model?: string
  verifier_runner?: string
  verifier_model?: string
  issues?: string | null
  elapsed_s: number
  pid_alive: boolean
  stalled: boolean
  worktree_exists?: boolean
  branch_exists?: boolean
  events?: RunEvent[]
}

export interface RunEvent {
  ts: string
  actor: string
  kind: string
  text: string
}

export interface RunDetail extends Run {
  events: RunEvent[]
  brief: string
  verify: string
  diff: string
  notes: string
  checks: Record<string, CheckInfo>
}

export type ProblemKind =
  | 'merge-conflict'
  | 'integration-failed'
  | 'merge-hook'
  | 'dirty-base'
  | 'verification-failed'
  | 'checks-failed'
  | 'build-failed'
  | 'needs-human'
  | 'quota'
  | 'budget'
  | 'blocked'
  | 'stalled'
  | 'stopped'
  | 'push-failed'

export type FixAction =
  | 'resolve'
  | 'agent-fix'
  | 'answer'
  | 'retry-merge'
  | 'mark-merged'
  | 'merge'
  | 'resume'
  | 'reverify'
  | 'unblock'
  | 'run-fresh'
  | 'clean'
  | 'stash'
  | 'commit-base'
  | 'push'
  | 'stop'
  | 'open'

export interface Problem {
  id: string
  project: string
  task: string
  title?: string
  kind: ProblemKind
  state: string
  step?: string
  headline: string
  summary: string
  next?: string
  actions: FixAction[]
  primary?: FixAction
  question?: string
  warning?: string
  excerpt?: string
  since?: string | null
  has_run?: boolean
  worktree_exists?: boolean
  blocked?: { reason: string; at?: string }
}

export interface ProblemDetail extends Problem {
  sections: { label: string; text: string; kind: 'text' | 'code' }[]
  labels: Record<string, string>
  conflicts?: string[]
}

export interface GitSummary {
  branch?: string
  head?: string
  short?: string
  subject?: string
  when?: string
  clean?: boolean
  changes?: number
  remote?: string
  remote_name?: string
  remote_link?: string
  remote_label?: string
  branch_count?: number
  upstream?: string
  ahead?: number
  behind?: number
  worktrees?: number
}

export interface PreviewService {
  name: string
  url: string
  port: number
  open: boolean
}

export interface PreviewStatus {
  configured: boolean
  url?: string
  port?: number
  running?: boolean
  pid_alive?: boolean
  external?: boolean
  started?: string
  services?: PreviewService[]
}

export interface AgentRole {
  runner: string
  model: string
}

export interface Session {
  id: string
  cwd: string
  tool?: string
  model?: string
  status?: string
  busy?: boolean
  started?: string
  last_text?: string
  last_tool?: string
  tokens_in?: number
}

export interface Lanes {
  builders: Run[]
  builder: Run | null
  verifiers: Run[]
  waiting: Run[]
  queued: Run[]
  capacity: number
  build_capacity: number
}

export interface TaskItem {
  id: string
  title: string
  state: ' ' | 'x' | 'blocked' | string
  acceptance: number
}

export interface Project {
  name: string
  path: string
  configured: boolean
  error?: string
  git: GitSummary
  sessions: Session[]
  base_branch?: string
  tasks_file?: string
  agents?: Record<'builder' | 'verifier' | 'researcher', AgentRole>
  preview?: PreviewStatus
  chat?: { status: string; messages: number }
  counts?: { todo: number; done: number; total: number }
  blocked?: Record<string, { reason: string; at?: string }>
  tasks?: TaskItem[]
  next?: { id: string; title: string; acceptance: number }[]
  loop?: { pid: number; started: string; mode: string; alive: boolean } | null
  runs?: Run[]
  push?: { enabled: boolean; ok?: boolean; pushed?: boolean; error?: string | null; checked?: string; remote?: string } | null
  cost_today?: number
  mode?: 'async' | 'sync'
  lanes?: Lanes
  active_ids?: string[]
  problems?: Problem[]
  current?: Run | null
  attention?: Run | null
}

export interface AppState {
  generated: string
  totals: { projects: number; running: number; todo: number; done: number; cost_today: number }
  supervisor: { pid?: number; alive: boolean }
  projects: Project[]
  external: Session[]
  auth?: boolean
}

export interface ConflictFileState {
  path: string
  markers: number
  resolved: boolean
}

export interface ConflictStatus {
  project: string
  task: string
  base: string
  branch: string
  worktree: string
  merging: boolean
  files: ConflictFileState[]
  resolved: string[]
  predicted: string[]
  dirty: string
  base_dirty: boolean
  clean?: boolean
  finished?: boolean
  merge_error?: string
}

export interface ConflictFile {
  path: string
  ours: string | null
  theirs: string | null
  ancestor: string | null
  working: string | null
  binary: boolean
  too_big: boolean
}

export interface ActivityEvent {
  ts: string
  project: string
  task: string
  title: string
  actor: string
  kind: string
  text: string
  tone: 'good' | 'bad' | 'warn' | 'info'
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
  ts?: string
}

export interface ChatState {
  status: string
  messages: ChatMessage[]
  pid_alive?: boolean
  runner?: string
  model?: string
}
