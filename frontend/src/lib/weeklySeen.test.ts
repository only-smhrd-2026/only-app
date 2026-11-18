import { afterEach, expect, it, vi } from 'vitest'
import { markWeeklySeen, weeklySeen } from './weeklySeen'

afterEach(() => vi.unstubAllGlobals())

it('remembers the last week separately for each room', () => {
  const values = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  })
  markWeeklySeen(1, '2026-11-16')
  expect(weeklySeen(1)).toBe('2026-11-16')
  expect(weeklySeen(2)).toBeNull()
})
