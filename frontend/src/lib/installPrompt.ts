/** 페이지가 열릴 때 한 번 오는 설치 이벤트를 가족 홈에 도착할 때까지 보관한다. */
type InstallPromptEvent = Event & {
  prompt: () => Promise<{ outcome: 'accepted' | 'dismissed' }>
}

let pending: InstallPromptEvent | null = null
let installed = false
const listeners = new Set<() => void>()
const notify = () => listeners.forEach((listener) => listener())

window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault()
  pending = event as InstallPromptEvent
  notify()
})

window.addEventListener('appinstalled', () => {
  pending = null
  installed = true
  notify()
})

export function getInstallState(): 'installed' | 'available' | 'unavailable' {
  const ios = navigator as Navigator & { standalone?: boolean }
  if (installed || window.matchMedia('(display-mode: standalone)').matches || ios.standalone) return 'installed'
  return pending ? 'available' : 'unavailable'
}

export function subscribeInstallPrompt(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export async function promptInstall() {
  const event = pending
  if (!event) return
  // 한 이벤트의 prompt()는 한 번만 쓸 수 있다. 연속 클릭도 같은 이벤트를 다시 쓰지 않는다.
  pending = null
  try {
    await event.prompt()
  } finally {
    notify()
  }
}
