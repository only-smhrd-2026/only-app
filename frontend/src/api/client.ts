/** 서버 호출 공통 (D10). 쿠키 인증이라 토큰 헤더 없음. 오류는 서버 {detail, code} 그대로 ApiError 로. */

export class ApiError extends Error {
  status: number
  code: string
  constructor(status: number, code: string, detail: string) {
    super(detail)
    this.status = status
    this.code = code
  }
}

type Options = { method?: string; body?: unknown; form?: FormData; signal?: AbortSignal }

export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const method = opts.method ?? (opts.body !== undefined || opts.form ? 'POST' : 'GET')
  const res = await fetch(path, {
    method,
    credentials: 'include',
    headers: opts.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
    signal: opts.signal,
  })
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiError(res.status, data.code ?? `HTTP_${res.status}`, data.detail ?? '서버 오류')
  return data as T
}
