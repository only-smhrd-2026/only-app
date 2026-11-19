/** lib/push — 가짜 브라우저(알림 권한·푸시 구독·서버)로 켜기·끄기·조용히 맞추기를 돌려 본다. 진짜 푸시 서비스는 부르지 않는다. */
import { afterEach, expect, it, vi } from 'vitest'

// RFC 8291 부록 A 의 두 공개 키 — 풀면 65바이트, 0x04 로 시작한다. KEY = 서버 키, OLD_KEY = 바꾸기 전 서버 키로 쓴다
const KEY = 'BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8'
const OLD_KEY = 'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4'

afterEach(() => vi.unstubAllGlobals())

type Permission = 'default' | 'granted' | 'denied'
type SubscribeOptions = { userVisibleOnly: boolean; applicationServerKey: Uint8Array<ArrayBuffer> }

/** 가짜 브라우저를 깔고 lib/push 를 새로 읽는다(모듈이 기억하는 키·'맞춤 끝' 표시를 테스트마다 비우려고) */
async function setup({ permission = 'default' as Permission, ask = 'granted' as Permission, serverKey = KEY as string | null, fail = false } = {}) {
  const posts: { path: string; body: { endpoint: string } }[] = []
  const subs: { endpoint: string; unsubscribe: () => Promise<boolean> }[] = []
  let current: (typeof subs)[number] | null = null
  let failing = fail
  const subscribe = vi.fn(async (options: SubscribeOptions) => {
    const endpoint = `https://fcm.googleapis.com/fcm/send/fake-${subs.length + 1}`
    const made = {
      endpoint,
      options: { applicationServerKey: options.applicationServerKey.buffer },
      toJSON: () => ({ endpoint, keys: { p256dh: 'p', auth: 'a' } }),
      unsubscribe: vi.fn(async () => {
        if (current === made) current = null
        return true
      }),
    }
    subs.push(made)
    current = made
    return made
  })
  const registration = { pushManager: { getSubscription: async () => current, subscribe } }
  const notification = {
    permission,
    requestPermission: vi.fn(async () => {
      if (notification.permission === 'default') notification.permission = ask
      return notification.permission
    }),
  }
  vi.stubGlobal('Notification', notification)
  vi.stubGlobal('window', { PushManager: class {}, Notification: notification })
  vi.stubGlobal('navigator', { serviceWorker: { ready: Promise.resolve(registration), getRegistration: async () => registration } })
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/push/key') return Response.json({ public_key: serverKey })
    if (failing) return Response.json({ detail: '서버 오류', code: 'INTERNAL' }, { status: 500 })
    posts.push({ path, body: JSON.parse(String(init?.body)) })
    return Response.json({ ok: true })
  }))
  vi.resetModules()
  const push = await import('./push')
  return { push, posts, subs, subscribe, notification, heal: () => { failing = false } }
}

it('decodes a base64url key to its bytes and back', async () => {
  const { push } = await setup()
  const bytes = push.fromBase64Url(KEY)
  expect(bytes.length).toBe(65)
  expect(bytes[0]).toBe(4)
  expect(push.toBase64Url(bytes.buffer)).toBe(KEY)
  expect([...push.fromBase64Url('-_8')]).toEqual([251, 255]) // 보통 base64 로는 '+/8='
  expect(push.toBase64Url(new Uint8Array([251, 255]).buffer)).toBe('-_8')
  expect(push.toBase64Url(null)).toBe('')
})

it('reports unsupported where the browser has no push', async () => {
  const { push } = await setup()
  vi.stubGlobal('window', { Notification: {} }) // PushManager 없음 = 아이폰 사파리 탭
  expect(await push.pushState()).toBe('unsupported')
  expect(await push.enablePush(push.FAMILY_PUSH)).toBe('unsupported')
})

it('turns on: asks permission, subscribes with the server key, registers the subscription as is', async () => {
  const { push, posts, subs, subscribe, notification } = await setup()
  expect(await push.pushState()).toBe('off')
  expect(await push.enablePush(push.FAMILY_PUSH)).toBe('on')
  expect(notification.requestPermission).toHaveBeenCalledTimes(1)
  const options = subscribe.mock.calls[0][0]
  expect(options.userVisibleOnly).toBe(true)
  expect(push.toBase64Url(options.applicationServerKey.buffer)).toBe(KEY)
  expect(posts).toEqual([{ path: '/api/push/subscribe', body: { endpoint: subs[0].endpoint, keys: { p256dh: 'p', auth: 'a' } } }])
  expect(await push.pushState()).toBe('on')
})

it('does not subscribe or call the server when permission is refused', async () => {
  const { push, posts, subscribe } = await setup({ ask: 'denied' })
  expect(await push.enablePush(push.FAMILY_PUSH)).toBe('denied')
  expect(subscribe).not.toHaveBeenCalled()
  expect(posts).toEqual([])
  expect(await push.pushState()).toBe('denied')
})

it('turns off: removes this browser on the server, then drops the subscription', async () => {
  const { push, posts, subs } = await setup()
  await push.enablePush(push.FAMILY_PUSH)
  await push.disablePush()
  expect(posts[1]).toEqual({ path: '/api/push/unsubscribe', body: { endpoint: subs[0].endpoint } })
  expect(subs[0].unsubscribe).toHaveBeenCalled()
  expect(await push.pushState()).toBe('off')
  await push.disablePush() // 구독이 없으면 아무것도 하지 않는다
  expect(posts.length).toBe(2)
})

it('quiet sync never asks for permission', async () => {
  const { push, posts, subscribe, notification } = await setup({ permission: 'default' })
  await push.syncPush(push.ELDER_PUSH, true)
  expect(notification.requestPermission).not.toHaveBeenCalled()
  expect(subscribe).not.toHaveBeenCalled()
  expect(posts).toEqual([])
})

it('quiet sync on the elder home subscribes an allowed phone once per app open', async () => {
  const { push, posts, subs, subscribe } = await setup({ permission: 'granted' })
  await push.syncPush(push.ELDER_PUSH, true)
  await push.syncPush(push.ELDER_PUSH, true)
  expect(subscribe).toHaveBeenCalledTimes(1)
  expect(posts).toEqual([{ path: '/api/elder/push/subscribe', body: { endpoint: subs[0].endpoint, keys: { p256dh: 'p', auth: 'a' } } }])
})

it('quiet sync for family only re-registers a browser that was already on, once per person', async () => {
  const { push, posts, subs, subscribe } = await setup({ permission: 'granted' })
  await push.syncPush(push.FAMILY_PUSH, false, 1) // 켠 적 없는 브라우저 → 만들지 않는다
  expect(subscribe).not.toHaveBeenCalled()
  expect(posts).toEqual([])
  await push.enablePush(push.FAMILY_PUSH)
  await push.syncPush(push.FAMILY_PUSH, false, 2) // 같은 브라우저에 다른 사람이 로그인 → 그 사람 것으로 다시 등록
  await push.syncPush(push.FAMILY_PUSH, false, 2)
  expect(subscribe).toHaveBeenCalledTimes(1)
  expect(posts.map((p) => [p.path, p.body.endpoint])).toEqual([
    ['/api/push/subscribe', subs[0].endpoint],
    ['/api/push/subscribe', subs[0].endpoint],
  ])
})

it('quiet sync replaces a subscription made with an old server key', async () => {
  const { push, posts, subs, subscribe } = await setup({ permission: 'granted' })
  await subscribe({ userVisibleOnly: true, applicationServerKey: push.fromBase64Url(OLD_KEY) }) // 키를 바꾸기 전에 만든 구독
  await push.syncPush(push.FAMILY_PUSH, false, 1)
  expect(subs[0].unsubscribe).toHaveBeenCalled()
  expect(push.toBase64Url(subscribe.mock.calls[1][0].applicationServerKey.buffer)).toBe(KEY)
  expect(posts.map((p) => p.body.endpoint)).toEqual([subs[1].endpoint])
})

it('quiet sync swallows a failure and tries again next time', async () => {
  const { push, posts, heal } = await setup({ permission: 'granted', fail: true })
  await expect(push.syncPush(push.ELDER_PUSH, true)).resolves.toBeUndefined()
  expect(posts).toEqual([])
  heal()
  await push.syncPush(push.ELDER_PUSH, true)
  expect(posts.length).toBe(1)
})

it('does nothing when the server has no push key', async () => {
  const { push, posts, subscribe } = await setup({ permission: 'granted', serverKey: null })
  expect(await push.pushKey()).toBeNull()
  await push.syncPush(push.ELDER_PUSH, true)
  expect(await push.enablePush(push.FAMILY_PUSH)).toBe('off')
  expect(subscribe).not.toHaveBeenCalled()
  expect(posts).toEqual([])
})

it('a notification link /?room=7 remembers that room and leaves the address clean', async () => {
  const run = async (search: string) => {
    const saved = new Map<string, string>()
    const replaced: string[] = []
    vi.stubGlobal('location', { search, pathname: '/', hash: '' })
    vi.stubGlobal('history', { state: null, replaceState: (_state: unknown, _title: string, url: string) => replaced.push(url) })
    vi.stubGlobal('localStorage', { setItem: (key: string, value: string) => saved.set(key, value) })
    vi.resetModules()
    await import('./push')
    return { room: saved.get('haru.fam.room'), replaced }
  }
  expect(await run('?room=7')).toEqual({ room: '7', replaced: ['/'] })
  expect(await run('?room=7&preview=1')).toEqual({ room: '7', replaced: ['/?preview=1'] })
  for (const search of ['', '?room=abc', '?room=-1', '?room=1.5', '?room=0', '?preview=1']) {
    expect(await run(search)).toEqual({ room: undefined, replaced: [] })
  }
})
