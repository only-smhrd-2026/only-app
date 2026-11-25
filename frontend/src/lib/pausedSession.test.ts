import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearPaused, readChat, readPaused, resumePath, savePaused, type Paused } from './pausedSession'

const paused: Paused = { id: '42', kind: 'DIARY', at: 1_000 }

beforeEach(() => {
  const values = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  })
})
afterEach(() => vi.unstubAllGlobals())

describe('paused session', () => {
  it('reads saved sessions until the 30-minute limit', () => {
    savePaused(paused)
    expect(readPaused(paused.at)).toEqual(paused)
    expect(readPaused(paused.at + 30 * 60_000)).toBeNull()
  })

  it('clears a saved session', () => {
    savePaused(paused)
    clearPaused()
    expect(readPaused(paused.at)).toBeNull()
  })

  it('keeps a chat in its own slot (D107)', () => {
    const now = Date.now() // clearPaused(id) 는 지금 시각으로 30분 안인 것만 본다
    const diary = { ...paused, at: now }
    savePaused(diary)
    savePaused({ id: '7', kind: 'CHAT', at: now, went: 'ALBUM' })
    expect(readPaused(now)).toEqual(diary) // 회상·일기 '이어서' 칸은 그대로
    expect(readChat(now)?.went).toBe('ALBUM')
    expect(readChat(now + 30 * 60_000)).toBeNull()
    clearPaused('7')
    expect(readChat(now)).toBeNull()
    expect(readPaused(now)).toEqual(diary)
  })

  it('routes diary and memory sessions', () => {
    expect(resumePath(paused)).toBe('/elder/diary/42')
    expect(resumePath({ ...paused, kind: 'MEMORY' })).toBe('/elder/memory/42')
  })
})
