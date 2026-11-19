// 홈 화면 설치(PWA)용 최소 서비스 워커. 화면 껍데기(index.html)만 네트워크 우선으로 캐시하고, /api 는 절대 캐시하지 않는다.
const CACHE = 'haru-shell-v1'

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.add('/').catch(() => {})))
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))),
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  if (event.request.method !== 'GET' || url.pathname.startsWith('/api/')) return
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          const copy = res.clone() // 응답을 넘기기 전에 복사해야 한다 (넘긴 뒤 clone 하면 TypeError)
          caches.open(CACHE).then((c) => c.put('/', copy))
          return res
        })
        .catch(() => caches.match('/')),
    )
  }
})

// 웹 푸시: 서버가 보낸 { title, body?, url, tag } 를 폰 알림으로 띄운다 (backend/app/services/push.py).
// 본문이 없거나 깨져도 기본 문장으로 꼭 띄운다 — 아이폰은 알림을 안 띄운 푸시가 이어지면 구독을 끊는다.
self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data.json() || {}
  } catch {
    /* 본문 없음·깨짐 → 기본 문장 */
  }
  event.waitUntil(
    self.registration.showNotification(data.title || '하루한장에 새 소식이 있어요', {
      body: data.body,
      tag: data.tag,
      renotify: Boolean(data.tag), // 같은 종류 알림이 또 와도 소리·진동으로 알린다
      icon: '/icons/icon-192.png', // manifest 의 아이콘
      data: { url: data.url || '/start' },
    }),
  )
})

// 알림을 누르면: 이미 열린 창이 있으면 그 창을 앞으로 가져와 그 주소로, 없으면 새로 연다.
// 주소는 우리 앱 안의 것만 — 없거나 다른 곳이면 앱 첫 주소(/start: 어르신 폰은 어르신 홈, 아니면 가족 홈)
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  let url = new URL('/start', self.location.origin)
  try {
    const wanted = new URL(event.notification.data.url, self.location.origin)
    if (wanted.origin === self.location.origin) url = wanted
  } catch {
    /* 주소를 못 읽음 → 앱 첫 주소 */
  }
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      const open = windows[0]
      if (!open || !('navigate' in open)) return self.clients.openWindow(url.href)
      return open
        .focus()
        .then((client) => client.navigate(url.href))
        .catch(() => self.clients.openWindow(url.href))
    }),
  )
})
