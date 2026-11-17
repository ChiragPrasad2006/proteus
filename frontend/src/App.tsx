import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { NoiseOverlay } from '@/components/effects/NoiseOverlay'
import { LandingPage } from '@/pages/LandingPage'
import { WorkspacePage } from '@/pages/WorkspacePage'

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

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/workspace" element={<WorkspacePage />} />
          {/* Unknown routes fall back to the landing page. */}
          <Route path="*" element={<LandingPage />} />
        </Routes>
        <NoiseOverlay />
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
