/** public/sw.js 의 푸시 처리 — 가짜 self 로 돌려 본다(브라우저·푸시 서버 없이). 알림을 꼭 띄우는지, 누르면 어디로 가는지. */
import { expect, it, vi } from 'vitest'
import source from '../../public/sw.js?raw'

type Handler = (event: Record<string, unknown>) => void
const ORIGIN = 'https://haru.test'

function load(windows: unknown[] = []) {
  const handlers: Record<string, Handler> = {}
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (type: string, handler: Handler) => {
      handlers[type] = handler
    },
    skipWaiting: vi.fn(),
    registration: { showNotification: vi.fn(() => Promise.resolve()) },
    clients: {
      claim: vi.fn(),
      matchAll: vi.fn(() => Promise.resolve(windows)),
      openWindow: vi.fn(() => Promise.resolve(null)),
    },
  }
  new Function('self', source)(self)
  /** 이벤트를 넣고 waitUntil 에 넘긴 일이 끝날 때까지 기다린다 */
  const fire = async (type: string, event: Record<string, unknown>) => {
    const waits: unknown[] = []
    handlers[type]({ ...event, waitUntil: (p: unknown) => waits.push(p) })
    await Promise.all(waits)
  }
  return { self, fire }
}

const click = (url?: unknown) => ({ notification: { close: vi.fn(), data: url === undefined ? null : { url } } })

it('shows the pushed title, body and tag', async () => {
  const { self, fire } = load()
  const payload = { title: '순자 할머니 일기가 왔어요', body: '본문', url: '/?room=3', tag: 'DIARY_POSTED-3' }
  await fire('push', { data: { json: () => payload } })
  expect(self.registration.showNotification).toHaveBeenCalledWith('순자 할머니 일기가 왔어요', {
    body: '본문',
    tag: 'DIARY_POSTED-3',
    renotify: true,
    icon: '/icons/icon-192.png',
    data: { url: '/?room=3' },
  })
})

it('still shows a notification when the payload is missing or broken', async () => {
  const broken = () => {
    throw new SyntaxError('bad json')
  }
  for (const data of [null, { json: broken }, { json: () => null }, { json: () => '글자만' }]) {
    const { self, fire } = load()
    await fire('push', { data })
    expect(self.registration.showNotification).toHaveBeenCalledWith(
      '하루한장에 새 소식이 있어요',
      expect.objectContaining({ renotify: false, data: { url: '/start' } }),
    )
  }
})

it('brings an open window to the front and sends it to the address', async () => {
  const open = { focus: vi.fn(), navigate: vi.fn(() => Promise.resolve(null)) }
  open.focus.mockResolvedValue(open)
  const { self, fire } = load([open])
  const event = click('/elder/today')
  await fire('notificationclick', event)
  expect(event.notification.close).toHaveBeenCalled()
  expect(open.focus).toHaveBeenCalled()
  expect(open.navigate).toHaveBeenCalledWith(`${ORIGIN}/elder/today`)
  expect(self.clients.openWindow).not.toHaveBeenCalled()
})

it('opens a new window when none is open or the open one cannot be moved', async () => {
  const closed = load()
  await closed.fire('notificationclick', click('/elder/diary'))
  expect(closed.self.clients.openWindow).toHaveBeenCalledWith(`${ORIGIN}/elder/diary`)

  const stuck = { focus: vi.fn(), navigate: vi.fn(() => Promise.reject(new TypeError('not controlled'))) }
  stuck.focus.mockResolvedValue(stuck)
  const uncontrolled = load([stuck])
  await uncontrolled.fire('notificationclick', click('/weekly/3'))
  expect(uncontrolled.self.clients.openWindow).toHaveBeenCalledWith(`${ORIGIN}/weekly/3`)
})

it('never leaves the app: other sites and missing addresses go to the start page', async () => {
  for (const url of ['https://evil.example/steal', '//evil.example/x', undefined]) {
    const { self, fire } = load()
    await fire('notificationclick', click(url))
    expect(self.clients.openWindow).toHaveBeenCalledWith(`${ORIGIN}/start`)
  }
})
