import { afterEach, expect, it, vi } from 'vitest'
import { api, ApiError } from './client'

afterEach(() => vi.unstubAllGlobals())

it('preserves the server status, code, and message', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
    Response.json({ detail: '다시 로그인해 주세요', code: 'AUTH_REQUIRED' }, { status: 401 }),
  ))
  const request = api('/api/auth/me')
  await expect(request).rejects.toBeInstanceOf(ApiError)
  await expect(request).rejects.toMatchObject({
    status: 401, code: 'AUTH_REQUIRED', message: '다시 로그인해 주세요',
  })
})

it('uses the status as the fallback code for a bodyless error', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 502 })))
  await expect(api('/api/example')).rejects.toMatchObject({ status: 502, code: 'HTTP_502' })
})

it('returns undefined for a 204 response', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
  await expect(api('/api/example')).resolves.toBeUndefined()
})

it('translates network errors', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
  await expect(api('/api/example')).rejects.toMatchObject({
    status: 0, code: 'NETWORK', message: '연결이 잠깐 끊겼어요. 다시 해 주세요.',
  })
})

it('preserves the original error for an aborted signal', async () => {
  const error = new DOMException('Aborted', 'AbortError')
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(error))
  await expect(api('/api/example', { signal: AbortSignal.abort() })).rejects.toBe(error)
})
