import { expect, it } from 'vitest'
import { speakText } from './audio'

it('drops laughing/crying jamo, ^^, ~ and emoji before reading aloud', () => {
  expect(speakText('고마워 ㅜㅜ')).toBe('고마워')
  expect(speakText('ㅋㅋㅋ 좋아요^^')).toBe('좋아요')
  expect(speakText('사랑해요~~ ❤️👍🏻')).toBe('사랑해요')
  expect(speakText('할머니 👨‍👩‍👧 보고 싶어요')).toBe('할머니 보고 싶어요')
  expect(speakText('ㅠㅠ 😢')).toBe('')
})

it('leaves normal Korean as it is', () => {
  expect(speakText('오늘 김치찌개를 먹었어요. 맛있었어요!')).toBe('오늘 김치찌개를 먹었어요. 맛있었어요!')
  expect(speakText('3월 5일, 10시')).toBe('3월 5일, 10시')
})
