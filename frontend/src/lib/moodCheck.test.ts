import { afterEach, expect, it, vi } from 'vitest'
import { CHECKS, checkKind, MEM_SETS, memSetFor, MOOD_ANSWERS, MOOD_ITEMS, moodSnoozed, ordinal, snoozeMood } from './moodCheck'

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

it('keeps each scale at its own item and answer count', () => {
  const shape = Object.fromEntries(Object.entries(CHECKS).map(([k, c]) => [k, [c.items.length, c.answers.length]]))
  expect(shape).toEqual({ PHQ8: [8, 4], PHQ9: [9, 4], UCLA3: [3, 3], GAD7: [7, 4], SMCQ: [14, 2] })
  expect(CHECKS.PHQ9.items.slice(0, 8)).toEqual([...MOOD_ITEMS]) // PHQ-9 = PHQ-8 + 9번
})

it('reads the check kind from the address, PHQ8 by default', () => {
  expect(checkKind('GAD7')).toBe('GAD7')
  expect(checkKind(null)).toBe('PHQ8')
  expect(checkKind('MEMGAME')).toBe('PHQ8')
  expect(checkKind('toString')).toBe('PHQ8')
  expect(ordinal(0)).toBe('첫 번째 질문이에요.')
  expect(ordinal(13)).toBe('열네 번째 질문이에요.')
})

it('changes memory game words every Korean day', () => {
  for (const s of MEM_SETS) {
    expect(s.words).toHaveLength(3)
    expect(s.choices).toHaveLength(6)
    for (const w of s.words) expect(s.choices.filter((c) => c[1] === w[1])).toHaveLength(1)
  }
  const d1 = memSetFor(Date.parse('2026-11-23T14:59:00Z')) // 11/23 23:59 KST
  expect(memSetFor(Date.parse('2026-11-22T15:00:00Z'))).toBe(d1) // 11/23 00:00 KST
  expect(memSetFor(Date.parse('2026-11-23T15:00:00Z'))).not.toBe(d1) // 11/24 00:00 KST
})
