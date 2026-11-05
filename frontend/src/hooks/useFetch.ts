import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'

/** GET 한 번 + reload. path 가 null 이면 부르지 않는다. */
export function useFetch<T>(path: string | null) {
  const [data, setData] = useState<T>()
  const [error, setError] = useState<ApiError>()
  const [loading, setLoading] = useState(!!path)
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    if (!path) return
    let alive = true
    setLoading(true)
    api<T>(path)
      .then((d) => alive && (setData(d), setError(undefined)))
      .catch((e) => alive && setError(e as ApiError))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [path, tick])

  return { data, error, loading, reload }
}
