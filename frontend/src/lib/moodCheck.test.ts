import { afterEach, expect, it, vi } from 'vitest'
import { MOOD_ANSWERS, MOOD_ITEMS, moodSnoozed, snoozeMood } from './moodCheck'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('has eight mood questions and four answers', () => {
  expect(MOOD_ITEMS).toHaveLength(8)
  expect(MOOD_ANSWERS).toHaveLength(4)
})

it('snoozes until midnight in Korea', () => {
  const values = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  })
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-11-18T14:59:59Z'))
  snoozeMood()
  expect(moodSnoozed()).toBe(true)
  vi.setSystemTime(new Date('2026-11-18T15:00:00Z'))
  expect(moodSnoozed()).toBe(false)
})

it('works without readable local storage', () => {
  vi.stubGlobal('localStorage', undefined)
  expect(() => snoozeMood()).not.toThrow()
  expect(moodSnoozed()).toBe(false)
  const blocked = () => { throw new Error('storage disabled') }
  vi.stubGlobal('localStorage', { getItem: blocked, setItem: blocked })
  expect(() => snoozeMood()).not.toThrow()
  expect(moodSnoozed()).toBe(false)
})
