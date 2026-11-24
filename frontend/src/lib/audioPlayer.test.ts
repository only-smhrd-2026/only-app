// 재생기 하나를 같이 쓰는 play() (11/24 아이폰) — 앞 소리의 늦은 멈춤 이벤트가 새 소리를 끝내지 않는지
import { beforeAll, expect, it } from 'vitest'

const made: FakeAudio[] = []
class FakeAudio {
  src = ''
  paused = true
  ended = false
  playbackRate = 1
  defaultPlaybackRate = 1
  onpause: (() => void) | null = null
  onended: (() => void) | null = null
  onwaiting: (() => void) | null = null
  onplaying: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor() {
    made.push(this)
  }
  play() {
    this.paused = false
    this.ended = false
    return Promise.resolve()
  }
  pause() {
    this.paused = true
    setTimeout(() => this.onpause?.(), 0) // 브라우저처럼 이벤트는 나중에 온다
  }
  finishSound() {
    this.paused = true
    this.ended = true
    this.onended?.()
  }
}

let say: typeof import('./audio').say
beforeAll(async () => {
  Object.assign(globalThis, { window: globalThis, Audio: FakeAudio })
  ;({ say } = await import('./audio'))
})

const tick = () => new Promise((r) => setTimeout(r, 5))

it('reuses one player and a late pause from the old sound does not stop the new one', async () => {
  const first = say('하나', 1, 'AAA')
  const second = say('둘', 1, 'BBB') // say 가 앞 소리를 멈춘다 → 멈춤 이벤트가 새 소리 시작 뒤에 온다
  expect(await first).toBe(true) // 앞 소리는 '우리가 멈춤'
  await tick()
  expect(made).toHaveLength(1)
  let settled = false
  void second.then(() => (settled = true))
  await tick()
  expect(settled).toBe(false) // 늦게 온 멈춤 이벤트에 끝나지 않았다
  made[0].finishSound()
  expect(await second).toBe(true)
})

it('a pause we did not make (phone ring) ends the sound as not heard', async () => {
  const third = say('셋', 1, 'CCC')
  await tick()
  made[0].pause()
  expect(await third).toBe(false)
})
