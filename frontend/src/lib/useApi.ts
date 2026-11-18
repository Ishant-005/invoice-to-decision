import { useCallback, useEffect, useRef, useState } from 'react'

import { request } from './api'

export interface ApiState<T> {
  data: T | null
  error: string | null
  loading: boolean // true only until the first answer arrives
  reload: () => void
  setData: (data: T) => void
}

/**
 * Fetch one API path and keep the answer.
 *
 * `pollWhile` turns on polling: after every answer, if it returns true the path is fetched
 * again `pollMs` later. The run view uses this to follow a run until it has finished.
 */
export function useApi<T>(
  path: string | null,
  pollWhile?: (data: T) => boolean,
  pollMs = 700,
): ApiState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(path !== null)
  const [version, setVersion] = useState(0)
  // Kept in a ref so a new function on every render does not restart the effect.
  const pollRef = useRef(pollWhile)
  useEffect(() => {
    pollRef.current = pollWhile
  })

  useEffect(() => {
    if (path === null) return
    let cancelled = false
    let timer: number | undefined
    let answered = false

    async function load() {
      try {
        const answer = await request<T>(path as string)
        if (cancelled) return
        answered = true
        setData(answer)
        setError(null)
        if (pollRef.current?.(answer)) timer = window.setTimeout(load, pollMs)
      } catch (failure) {
        if (cancelled) return
        setError(failure instanceof Error ? failure.message : 'Something went wrong.')
        // Keep trying once polling has begun: one dropped request must not freeze a live run.
        if (answered && pollRef.current) timer = window.setTimeout(load, pollMs * 3)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [path, version, pollMs])

  const reload = useCallback(() => setVersion((v) => v + 1), [])
  return { data, error, loading, reload, setData }
}
