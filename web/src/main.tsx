import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRootRoute, createRoute, createRouter, RouterProvider, type ErrorComponentProps } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Shell } from './components/shell'
import { ActivityPage } from './routes/activity'
import { InboxPage } from './routes/inbox'
import { OverviewPage } from './routes/overview'
import { ProjectPage } from './routes/project'
import { ProjectsPage } from './routes/projects'
import './styles.css'

const rootRoute = createRootRoute({
  component: Shell,
  validateSearch: (s: Record<string, unknown>): { run?: string; tab?: string } => ({
    run: typeof s.run === 'string' ? s.run : undefined,
    tab: typeof s.tab === 'string' ? s.tab : undefined,
  }),
})

const routeTree = rootRoute.addChildren([
  createRoute({ getParentRoute: () => rootRoute, path: '/', component: OverviewPage }),
  createRoute({ getParentRoute: () => rootRoute, path: '/inbox', component: InboxPage }),
  createRoute({ getParentRoute: () => rootRoute, path: '/activity', component: ActivityPage }),
  createRoute({ getParentRoute: () => rootRoute, path: '/projects', component: ProjectsPage }),
  createRoute({ getParentRoute: () => rootRoute, path: '/projects/$name', component: ProjectPage }),
])

function PageError({ error, reset }: ErrorComponentProps) {
  return (
    <div className="mx-auto max-w-xl px-4 pt-16 text-center md:pt-24">
      <h1 className="text-xl font-semibold text-ink">This page hit an error</h1>
      <p className="mt-2 text-sm text-ink-2">The rest of Agent Room still works. Try again, or pick another page.</p>
      <pre className="mt-5 overflow-auto rounded-xl border border-line bg-sunken p-3 text-left font-mono text-xs whitespace-pre-wrap text-bad">
        {String((error as Error)?.message ?? error)}
      </pre>
      <button
        onClick={reset}
        className="mt-5 inline-flex h-10 items-center rounded-[10px] bg-accent px-4 text-sm font-medium text-accent-ink"
      >
        Try again
      </button>
    </div>
  )
}

const router = createRouter({ routeTree, defaultPreload: false, scrollRestoration: true, defaultErrorComponent: PageError })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: true, retry: 1 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
