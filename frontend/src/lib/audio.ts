/**
 * 녹음·재생·브라우저 TTS. 서버 TTS 음성(audio_b64)은 playBase64, 그것이 없을 때(mock·실패)와 화면 고정 안내는 speechSynthesis (D5·D46).
 * 화면 고정 안내(PROMPT)는 서버와 같은 목소리로 미리 합성한 mp3(src/assets/audio)를 먼저 쓴다 (FR-VS-004·D48).
 * say()·speak() 는 늘 resolve 한다. 끝까지 못 들려줬을 때만 false(사용자 터치 전이라 자동 재생이 막힘, 전화벨이 소리를 멈춤)
 * — 부르는 쪽이 '눌러서 들어 보세요'를 띄운다 (D48).
 */

export type Recorder = { stop: () => Promise<Blob> }

/** 마이크 녹음 시작. maxMs 가 지나면 저절로 멈춘다. 끝나면 webm/opus Blob. */
export async function startRecording(maxMs = 60_000): Promise<Recorder> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : ''
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
  const chunks: Blob[] = []
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data)
  const done = new Promise<Blob>((resolve) => {
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop())
      resolve(new Blob(chunks, { type: rec.mimeType || 'audio/webm' }))
    }
  })
  rec.start()
  const timer = setTimeout(() => rec.state !== 'inactive' && rec.stop(), maxMs)
  return {
    stop: () => {
      clearTimeout(timer)
      if (rec.state !== 'inactive') rec.stop()
      return done
    },
  }
}

/** 녹음이 시작됐다는 신호 (FR-VS-001): 짧은 진동 + 삐. 못 내는 기기면 조용히 넘어간다. */
export function cue() {
  navigator.vibrate?.(80)
  try {
    const ctx = new AudioContext()
    const osc = ctx.createOscillator()
    const vol = ctx.createGain()
    vol.gain.value = 0.15
    osc.frequency.value = 880
    osc.connect(vol).connect(ctx.destination)
    osc.onended = () => void ctx.close()
    osc.start()
    osc.stop(ctx.currentTime + 0.12)
  } catch {
    // AudioContext 가 없는 기기
  }
}

/**
 * 화면 고정 안내 → src/assets/audio/<키>.mp3 (서버 TTS 와 같은 목소리로 미리 합성, FR-VS-004 '같은 안내 문장은 미리 합성해 캐시', D48).
 * 빌드가 주소에 해시를 붙여 다시 만들면 폰 캐시도 바뀐다. 여기 없는 문장·파일이 없을 때는 기기 목소리로 읽는다.
 * 문장이나 목소리(tts.VOICE, 11/17 TEST-01)를 바꾸면 mp3 를 다시 만든다
 * (홍진성 PC, 실제 키, 문장 수만큼 Google 호출 — 한 줄에 '  키: '문장',' 모양을 지켜야 아래 명령이 읽는다):
 *   cd backend && uv run python - <<'EOF'
 *   import pathlib, re
 *   from app.ai import tts
 *   src = pathlib.Path('../frontend/src/lib/audio.ts').read_text()
 *   for key, text in re.findall(r"^  (\w+): '([^']+)',", src, re.M):
 *       pathlib.Path(f'../frontend/src/assets/audio/{key}.mp3').write_bytes(tts._google(text))
 *   EOF
 */
export const PROMPT = {
  slow: '조금만요.', // 답이 8초 넘게 늦을 때 (FR-VS-005)
  error: '잠깐 문제가 있네요. 조금 있다가 다시 올게요.', // 15초 초과·망 오류로 끝낼 때 (FR-VS-005)
  notHeard: '잘 못 들었어요. 다시 말씀해 주세요.',
  buttons: '이번에는 버튼으로 답해 주세요.',
  micOff: '마이크를 쓸 수 없어요. 버튼으로 답해 주세요.',
  check: '잘 들었는지 확인해 주세요. 맞으면 맞아요를 눌러 주세요.', // 저신뢰 전사 (FR-VS-002)
  bye: '그래요, 오늘은 여기까지 할게요. 고마워요.',
  thanks: '고마워요. 오늘은 여기까지 할게요.',
  tooMany: '잠시 후 다시 말씀해 주세요', // 서버 429 TOO_MANY_REQUESTS 문장 그대로 (routers/stt.py)
  sttLimit: '오늘은 말로 답하기를 다 썼어요. 버튼을 눌러 답해 주세요.', // 서버 429 STT_DAILY_LIMIT 문장 그대로
} as const

const FILES = import.meta.glob<string>('../assets/audio/*.mp3', { eager: true, query: '?url', import: 'default' })
const PROMPT_URL = new Map<string, string>()
for (const [key, text] of Object.entries(PROMPT)) {
  const url = FILES[`../assets/audio/${key}.mp3`]
  if (url) PROMPT_URL.set(text, url)
}

let current: HTMLAudioElement | null = null

/**
 * mp3 재생. 끝까지 들려주면 true, stopSpeaking() 으로 멈추면 true, 전화벨·알람이 소리를 멈추면 false.
 * 재생하지 못하면 reject — 자동 재생 막힘은 NotAllowedError, 3초 안에 소리가 시작되지 않으면(망이 멈춤: error 없이 stalled 만 옴) Error.
 */
function play(src: string, rate: number): Promise<boolean> {
  return new Promise((resolve, reject) => {
    const audio = new Audio(src)
    audio.defaultPlaybackRate = audio.playbackRate = rate // default 도 같이: 다시 불러올 때 1.0 으로 돌아가지 않게
    current = audio
    const stalled = setTimeout(() => {
      audio.onpause = null
      audio.pause()
      reject(new Error('stalled'))
    }, 3_000)
    const settle = () => clearTimeout(stalled)
    audio.onplaying = settle
    audio.onended = () => (settle(), resolve(true))
    // stopSpeaking() 은 current 를 비운 뒤 pause 이벤트가 온다 → 우리가 멈춘 것. current 그대로면 시스템이 멈춘 것(전화벨)
    audio.onpause = () => (settle(), resolve(audio.ended || current !== audio))
    audio.onerror = () => (settle(), reject(new Error('audio')))
    audio.play().catch((e: unknown) => (settle(), reject(e)))
  })
}

/**
 * 서버 TTS(base64 mp3) 재생. 끝나면 resolve. 자동재생이 막히거나 재생하지 못하면 reject. stopSpeaking() 으로 멈출 수 있다.
 * rate = 말 속도(0.70·0.85·1.00). 서버는 1.0배로 합성하고 여기서 늦춘다 (D46). 음높이는 브라우저가 그대로 둔다.
 */
export function playBase64(b64: string, rate = 1, mime = 'audio/mpeg'): Promise<void> {
  return play(`data:${mime};base64,${b64}`, rate).then(() => {})
}

/**
 * 읽기: 서버 음성(b64) → 고정 안내 mp3 → 기기 목소리 순. 앞서 읽던 것은 끊는다. 끝까지 들려줬으면 true.
 * 자동 재생이 막혔을 때는 기기 목소리로 다시 읽지 않는다 — 크롬은 같은 규칙으로 막는다 (D48).
 */
export function say(text: string, rate = 0.85, b64?: string | null): Promise<boolean> {
  stopSpeaking()
  const src = b64 ? `data:audio/mpeg;base64,${b64}` : PROMPT_URL.get(text)
  if (!src) return speak(text, rate)
  return play(src, rate).catch((e: unknown) =>
    e instanceof DOMException && e.name === 'NotAllowedError' ? false : speak(text, rate),
  )
}

/**
 * 브라우저 TTS. 없으면 바로 resolve (자막만). 기기에 한국어 음성이 없어 onend/onerror 가 안 오면 글자 수 기준 시간 뒤 resolve.
 * 사용자 터치 전이라 막히면 false — 크롬은 speak() 안에서 바로 error 'not-allowed' 를 보낸다 (D48).
 */
export function speak(text: string, rate = 0.85): Promise<boolean> {
  return new Promise((resolve) => {
    if (!('speechSynthesis' in window)) return resolve(true)
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.lang = 'ko-KR'
    u.rate = rate
    // ponytail: 안전장치. 실기기 음성 속도는 제각각이라 글자당 ~250ms + 2초를 상한으로 둔다
    const guard = setTimeout(() => resolve(true), Math.min(15_000, 2_000 + (text.length * 250) / rate))
    const done = (ok: boolean) => {
      clearTimeout(guard)
      resolve(ok)
    }
    u.onend = () => done(true)
    u.onerror = (e) => done(e.error !== 'not-allowed')
    window.speechSynthesis.speak(u)
  })
}

/** 재생 중인 서버 음성과 브라우저 TTS 를 모두 멈춘다. */
export function stopSpeaking() {
  const a = current
  current = null // pause 이벤트보다 먼저 비운다: play() 가 '우리가 멈춤'으로 알아보게
  a?.pause()
  if ('speechSynthesis' in window) window.speechSynthesis.cancel()
}
