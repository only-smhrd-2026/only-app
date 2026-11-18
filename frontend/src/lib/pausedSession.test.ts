import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearPaused, readPaused, resumePath, savePaused, type Paused } from './pausedSession'

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

  it('routes diary and memory sessions', () => {
    expect(resumePath(paused)).toBe('/elder/diary/42')
    expect(resumePath({ ...paused, kind: 'MEMORY' })).toBe('/elder/memory/42')
  })
})
