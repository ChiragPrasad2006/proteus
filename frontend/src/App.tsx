import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { NoiseOverlay } from '@/components/effects/NoiseOverlay'

/** One client per app — the local backend is queried for health, chat, mail. */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 10_000,
    },
  },
})

// Route-level code splitting keeps the landing and workspace bundles separate.
const LandingPage = lazy(() => import('@/pages/LandingPage'))
const WorkspacePage = lazy(() => import('@/pages/WorkspacePage'))

function RouteFallback() {
  return (
    <main className="flex min-h-svh items-center justify-center bg-cobalt">
      <p className="font-display text-2xl text-paper">proteus</p>
    </main>
  )
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/workspace" element={<WorkspacePage />} />
            {/* Unknown routes fall back to the landing page. */}
            <Route path="*" element={<LandingPage />} />
          </Routes>
        </Suspense>
        <NoiseOverlay />
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
