import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { HealthReport, RuntimeStatus } from '@/types'

/**
 * Poll the local backend health endpoint. Degrades gracefully: when the
 * backend is offline the UI still renders and simply reports "offline".
 */
export function useHealth() {
  return useQuery<HealthReport>({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 15_000,
    retry: 0,
    staleTime: 5_000,
  })
}

/** Derive the Qwen3:8B runtime badge shown in the workspace header. */
export function useRuntimeStatus(modelLabel = 'Qwen3:8B'): RuntimeStatus {
  const { data, isLoading, isError } = useHealth()

  if (isLoading) {
    return { label: modelLabel, state: 'loading', detail: 'Checking local runtime…' }
  }
  if (isError || !data) {
    return { label: modelLabel, state: 'offline', detail: 'Backend not reachable' }
  }
  const generationReady = data.generation?.available === true || data.qwen?.available === true
  if (!generationReady) {
    return { label: modelLabel, state: 'offline', detail: 'Model not loaded' }
  }
  const gpu = data.gpu?.available ? `GPU · ${data.gpu.name ?? 'ready'}` : 'CPU'
  return { label: modelLabel, state: 'online', detail: gpu }
}
