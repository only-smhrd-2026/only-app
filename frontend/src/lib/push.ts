/**
 * 웹 푸시(폰 알림) — 이 브라우저를 구독시켜 서버에 알린다. 알림을 띄우는 쪽은 서비스 워커(public/sw.js), 보내는 쪽은 서버.
 * 가족: 알림 화면(NOTI_001)의 [알림 켜기]·[끄기], 로그아웃하면 끈다. 어르신 기기: 연결 화면에서 허용하면 켠다.
 * 서버에 푸시 키가 없으면(pushKey() = null) 아무것도 하지 않는다 — 화면은 카드를 숨긴다.
 */
import { api } from '../api/client'
import type { PushKeyOut } from '../api/types'

export type PushState = 'unsupported' | 'denied' | 'off' | 'on'

export const FAMILY_PUSH = '/api/push/subscribe'
export const ELDER_PUSH = '/api/elder/push/subscribe'

// 가족 푸시 알림을 눌러 들어온 주소 /?room=번호 → 가족 틀(FamilyFrame)이 그 어르신을 보이게 폰에 적고 주소에서는 뗀다.
// 알림 목록(NOTI_001)에서 눌렀을 때와 같은 칸이다. 서비스 워커는 이 칸을 못 써서 주소로 받는다
if (typeof location !== 'undefined') {
  const query = new URLSearchParams(location.search)
  const room = Number(query.get('room'))
  if (Number.isInteger(room) && room > 0) {
    try { localStorage.setItem('haru.fam.room', String(room)) } catch { /* 저장이 막힌 브라우저 */ }
    query.delete('room')
    const rest = query.toString()
    history.replaceState(history.state, '', location.pathname + (rest ? `?${rest}` : '') + location.hash)
  }
}

/** base64url 글자 → 바이트 (서버 공개 키를 pushManager.subscribe 에 넘길 때) */
export function fromBase64Url(text: string): Uint8Array<ArrayBuffer> {
  const base64 = text.replace(/-/g, '+').replace(/_/g, '/')
  return Uint8Array.from(atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')), (ch) => ch.charCodeAt(0))
}

/** 바이트 → base64url 글자 (끝의 = 없이) */
export function toBase64Url(bytes: ArrayBuffer | null): string {
  if (!bytes) return ''
  return btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export const pushSupported = () =>
  typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

let keyAsk: Promise<string | null> | null = null
/** 서버 공개 키. null = 이 서버는 푸시를 안 쓴다. 한 번만 묻고, 못 물었으면(망 오류) 다음에 다시 묻는다 */
export function pushKey(): Promise<string | null> {
  keyAsk ??= api<PushKeyOut>('/api/push/key').then((r) => r.public_key, () => {
    keyAsk = null
    return null
  })
  return keyAsk
}

/** 지금 이 브라우저의 상태. on = 알림 허용 + 구독 있음 */
export async function pushState(): Promise<PushState> {
  if (!pushSupported()) return 'unsupported'
  if (Notification.permission === 'denied') return 'denied'
  const reg = await navigator.serviceWorker.ready
  return Notification.permission === 'granted' && (await reg.pushManager.getSubscription()) ? 'on' : 'off'
}

/** 구독을 서버에 등록한다. create=false 면 이미 구독한 브라우저만(새로 만들지 않는다) */
async function register(path: string, key: string, create: boolean): Promise<void> {
  const reg = await navigator.serviceWorker.ready
  let sub = await reg.pushManager.getSubscription()
  const had = !!sub
  // 서버 키가 바뀌었으면 옛 구독으로는 못 받는다 → 버리고 새 키로 다시
  const subKey = sub?.options?.applicationServerKey
  if (sub && subKey && toBase64Url(subKey) !== key.replace(/=+$/, '')) {
    await sub.unsubscribe()
    sub = null
  }
  if (!sub) {
    if (!create && !had) return
    sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: fromBase64Url(key) })
  }
  await api(path, { body: sub.toJSON() })
}

/**
 * 켜기 — 권한을 묻고(이미 허용했으면 묻지 않는다) 구독해 서버에 등록한다. 돌려주는 값 = 그 뒤의 상태.
 * 서버에 푸시 키가 있을 때만 부른다(pushKey()). 권한은 다른 것을 기다리기 전에 맨 먼저 묻는다 — 아이폰은 누른 바로 그때만 물을 수 있다
 */
export async function enablePush(path: string): Promise<PushState> {
  if (!pushSupported()) return 'unsupported'
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') return permission === 'denied' ? 'denied' : 'off'
  const key = await pushKey()
  if (!key) return 'off'
  await register(path, key, true)
  return 'on'
}

const synced = new Set<string>()
/**
 * 조용히 맞추기 — 알림을 이미 허용한 브라우저의 구독을 서버에 다시 알린다. 화면 변화 없음, 실패는 무시(다음에 열 때 다시).
 * 어르신 홈(create=true): 구독이 없으면 만든다. 가족 틀(create=false): 켜 둔 브라우저만 — 지금 로그인한 사람 것으로 맞춘다.
 * 앱을 연 동안 같은 사람(who)은 한 번만 한다.
 */
export async function syncPush(path: string, create: boolean, who: number | string = ''): Promise<void> {
  const mark = `${path}:${who}`
  if (synced.has(mark) || !pushSupported() || Notification.permission !== 'granted') return
  synced.add(mark)
  try {
    const key = await pushKey()
    if (key) await register(path, key, create)
  } catch {
    synced.delete(mark)
  }
}

/** 끄기(가족 [끄기]·로그아웃) — 서버에서 이 브라우저를 지우고 브라우저 구독도 푼다. 로그인돼 있을 때 부른다 */
export async function disablePush(): Promise<void> {
  if (!pushSupported()) return
  const reg = await navigator.serviceWorker.getRegistration()
  const sub = await reg?.pushManager.getSubscription()
  if (!sub) return
  await api('/api/push/unsubscribe', { body: { endpoint: sub.endpoint } }).catch(() => {})
  await sub.unsubscribe()
}
