/**
 * 녹음·재생·브라우저 TTS. 서버 TTS 음성(audio_b64)은 playBase64, 그것이 없을 때(mock·실패)와 화면 고정 안내는 speechSynthesis (D5·D46).
 * 화면 고정 안내(PROMPT)는 서버와 같은 목소리로 미리 합성한 mp3(src/assets/audio)를 먼저 쓴다 (FR-VS-004·D48).
 * 그 밖의 화면 글(팝업 문장·안내·가족 소식·지난 일기)은 서버가 고른 목소리로 만든 소리를 먼저 쓴다 (POST /api/elder/speech, D78).
 * say()·speak() 는 늘 resolve 한다. 끝까지 못 들려줬을 때만 false(사용자 터치 전이라 자동 재생이 막힘, 전화벨이 소리를 멈춤)
 * — 부르는 쪽이 '눌러서 들어 보세요'를 띄운다 (D48).
 */
import { api, ApiError } from '../api/client'
import type { DeviceOut } from '../api/types'
import { MOOD_PROMPT } from './moodCheck'

export type Recorder = { stop: () => Promise<Blob> }

/** 마이크 녹음 시작. maxMs 가 지나면 저절로 멈춘다. 끝나면 webm/opus Blob. */
export async function startRecording(maxMs = 60_000): Promise<Recorder> {
  let stream: MediaStream
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'NotAllowedError') syncMic(false)
    throw e
  }
  syncMic(true)
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

/**
 * 마이크 허락이 서버에 적힌 것과 다르면 알린다 — 꺼지면 서버가 가족에게 '기기 권한이 꺼져 있어요'(PERMISSION_OFF)를 보낸다.
 * 연결 때 한 번만 알리던 것을(ELDER_CONNECT_001) 녹음할 때도 (11/24 실기기: 허락이 풀렸는데 가족은 몰랐다).
 * 쪽을 열 때마다 한 번만, 서버와 같으면 보내지 않는다 — 같은 알림이 쌓이지 않게.
 */
let micSynced = false
function syncMic(on: boolean) {
  if (micSynced) return
  micSynced = true
  api<DeviceOut>('/api/devices/me')
    .then((d) => d.perm_mic !== on && api('/api/devices/me/permissions', { method: 'PATCH', body: { perm_mic: on } }))
    .catch(() => {})
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
 * 화면 고정 안내 → 어르신이 고른 목소리의 mp3: 여자 src/assets/audio/<키>.mp3 · 남자 src/assets/audio/male/<키>.mp3
 * (서버 TTS 와 같은 목소리로 미리 합성, FR-VS-004 '같은 안내 문장은 미리 합성해 캐시', D48·D74).
 * 빌드가 주소에 해시를 붙여 다시 만들면 폰 캐시도 바뀐다. 여기 없는 문장·파일이 없을 때는 기기 목소리로 읽는다.
 * 문장이나 목소리(backend tts.VOICES)를 바꾸면 mp3 를 다시 만든다
 * (홍진성 PC, 실제 키, 문장 수 × 목소리 2개만큼 Google 호출 — 한 줄에 '  키: '문장',' 모양을 지켜야 아래 명령이 읽는다):
 *   cd backend && uv run python - <<'EOF'
 *   import pathlib, re
 *   from app.ai import tts
 *   src = pathlib.Path('../frontend/src/lib/audio.ts').read_text()
 *   for key, text in re.findall(r"^  (\w+): '([^']+)',", src, re.M):
 *       for voice, sub in (('FEMALE', ''), ('MALE', 'male/')):
 *           pathlib.Path(f'../frontend/src/assets/audio/{sub}{key}.mp3').write_bytes(tts._google(text, voice))
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
  voiceAsk: '어떤 목소리가 좋으세요? 눌러서 들어 보세요.', // 목소리 고르기(ELDER_CONNECT_001) — 고르기 전이라 여자 목소리 mp3 만 (D74)
  voiceHello: '안녕하세요. 이 목소리로 이야기 나눠요.', // 목소리 고르기·가족방 설정 — 누른 목소리로 들려준다 (D74)
  ...MOOD_PROMPT, // 마음 체크 11문장 — 글은 lib/moodCheck.ts 에 있다(공식 문구라 그 파일에서만 고친다). mp3 는 같은 명령을 그 파일에 돌려 만든다
} as const

const FILES = import.meta.glob<string>('../assets/audio/**/*.mp3', { eager: true, query: '?url', import: 'default' })
const PROMPT_KEY = new Map<string, string>(Object.entries(PROMPT).map(([key, text]) => [text, key]))

// 어르신이 고른 목소리(가족방 tts_voice, D74). 홈을 읽을 때 setVoice 로 맞추고 폰에도 적어 둔다
// — 홈을 거치지 않고 하위 화면에서 새로고침해도 고정 안내가 같은 목소리로 나온다
const VOICE_KEY = 'haru.elder.voice'
let voice: 'FEMALE' | 'MALE' = 'FEMALE'
try {
  if (localStorage.getItem(VOICE_KEY) === 'MALE') voice = 'MALE'
} catch {
  // 저장소가 막힌 브라우저 — 여자 목소리
}

export function setVoice(v: 'FEMALE' | 'MALE') {
  voice = v
  try {
    localStorage.setItem(VOICE_KEY, v)
  } catch {
    // 저장소가 막힌 브라우저 — 이 화면에서만
  }
}

let current: HTMLAudioElement | null = null

/**
 * mp3 재생. 끝까지 들려주면 true, stopSpeaking() 으로 멈추면 true, 전화벨·알람이 소리를 멈추면 false.
 * 재생하지 못하면 reject — 자동 재생 막힘은 NotAllowedError, 소리가 3초 안에 시작되지 않거나 나오다 끊긴 채 3초면
 * (망이 멈춤: error 없이 stalled·waiting 만 옴) Error.
 */
function play(src: string, rate: number): Promise<boolean> {
  return new Promise((resolve, reject) => {
    const audio = new Audio(src)
    audio.defaultPlaybackRate = audio.playbackRate = rate // default 도 같이: 다시 불러올 때 1.0 으로 돌아가지 않게
    current = audio
    let stalled = 0
    const settle = () => clearTimeout(stalled)
    const wait = () => {
      settle()
      stalled = window.setTimeout(() => {
        audio.onpause = null
        audio.pause()
        reject(new Error('stalled'))
      }, 3_000)
    }
    wait()
    audio.onwaiting = wait
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
 * rate = 말 속도(0.80·0.90·1.00, D74). 서버는 1.0배로 합성하고 여기서 늦춘다 (D46). 음높이는 브라우저가 그대로 둔다.
 */
export function playBase64(b64: string, rate = 1, mime = 'audio/mpeg'): Promise<void> {
  return play(`data:${mime};base64,${b64}`, rate).then(() => {})
}

/**
 * 읽기: 서버 음성(b64) → 고정 안내 mp3 → 서버가 고른 목소리로 만든 소리(D78) → 기기 목소리 순.
 * 앞서 읽던 것은 끊는다. 끝까지 들려줬으면 true.
 * 자동 재생이 막혔을 때는 기기 목소리로 다시 읽지 않는다 — 크롬은 같은 규칙으로 막는다 (D48).
 * v = 고정 안내 mp3 의 목소리. 평소에는 고른 목소리, 목소리 고르기·가족방 설정에서 들려줄 때만 따로 준다 (D74).
 */
export function say(text: string, rate = 0.9, b64?: string | null, v = voice): Promise<boolean> {
  stopSpeaking()
  const key = PROMPT_KEY.get(text) // 고정 안내 mp3 는 원래 글로 찾는다 — 다듬기는 그 뒤
  const src = b64 ? `data:audio/mpeg;base64,${b64}` : key && FILES[`../assets/audio/${v === 'MALE' ? 'male/' : ''}${key}.mp3`]
  const words = speakText(text)
  if (!src) return words ? speakServer(words, rate) : Promise.resolve(true)
  return play(src, rate).catch((e: unknown) =>
    e instanceof DOMException && e.name === 'NotAllowedError' ? false : words ? speakDevice(words, rate) : true,
  )
}

/**
 * 소리로 읽을 글 — 가족 글의 'ㅜㅜ'·'ㅋㅋ'(낱자모), '^^', '~', 그림 문자는 뺀다 (11/24 실기기: 'ㅜㅜ'를 '열열이'로 읽음).
 * 화면 글은 그대로 두고 읽기에서만 뺀다. 남는 말이 없으면 '' — say 는 아무것도 읽지 않는다.
 */
export function speakText(text: string): string {
  return text
    .replace(/[\u3131-\u318E]+/g, ' ') // 홀로 쓴 자모(ㅋ ㅎ ㅠ ㅜ …) — 글자 안의 자모는 이 범위가 아니라 안 지워진다
    .replace(/[\^~]+/g, ' ')
    .replace(/[\p{Extended_Pictographic}\p{Emoji_Modifier}\uFE0F\u200D]/gu, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/** 화면 글 읽기 — say 와 같다(고른 목소리, 안 되면 기기 목소리). 화면들이 쓰던 이름이라 남겨 둔다 (D78). */
export function speak(text: string, rate = 0.9): Promise<boolean> {
  return say(text, rate)
}

// 서버 소리 (D78). stopSpeaking 마다 늘어 — 기다리는 사이 멈춘 읽기는 소리를 받아도 틀지 않는다
let gen = 0
const SPEECH_WAIT_MS = 4_000 // 한 묶음을 이만큼 기다려도 안 오면 기기 목소리로 (60자 합성 약 1.8초, tts.py 실측)
const SPEECH_CHUNK = 60 // 긴 글은 문장을 이 글자 수 안팎으로 묶어 차례로 — 400자를 한 번에 만들면 9초를 기다린다
const SPEECH_OFF_MS = 60_000 // 서버가 소리를 못 주면(mock·상한·장애) 이 동안은 묻지 않고 기기 목소리로
let speechOffUntil = 0
const speechCache = new Map<string, string>() // 목소리|글 → b64. 같은 안내를 다시 읽을 때 서버를 부르지 않는다

function chunks(text: string): string[] {
  const out: string[] = []
  for (const s of text.trim().split(/(?<=[.!?。])\s+/)) {
    const last = out.length - 1
    if (last >= 0 && out[last].length + 1 + s.length <= SPEECH_CHUNK) out[last] += ` ${s}`
    else out.push(s)
  }
  return out
}

function fetchSpeech(text: string): Promise<string | null> {
  const key = `${voice}|${text}`
  const hit = speechCache.get(key)
  if (hit) return Promise.resolve(hit)
  if (Date.now() < speechOffUntil) return Promise.resolve(null)
  const ctl = new AbortController()
  const timer = window.setTimeout(() => ctl.abort(), SPEECH_WAIT_MS)
  return api<{ audio_b64: string | null }>('/api/elder/speech', { body: { text }, signal: ctl.signal })
    .then((r) => {
      if (!r.audio_b64) {
        speechOffUntil = Date.now() + SPEECH_OFF_MS
        return null
      }
      speechCache.set(key, r.audio_b64)
      if (speechCache.size > 40) speechCache.delete(speechCache.keys().next().value!) // 오래된 것부터
      return r.audio_b64
    })
    .catch((e: unknown) => {
      // 기기 연결 전(401)·글이 너무 김(422)은 이 글만 기기 목소리로. 시간 초과·망·서버 오류는 잠시 묻지 않는다
      if (!(e instanceof ApiError && e.status >= 400 && e.status < 500)) speechOffUntil = Date.now() + SPEECH_OFF_MS
      return null
    })
    .finally(() => window.clearTimeout(timer))
}

/** 서버가 고른 목소리로 묶음마다 받아 차례로 튼다 — 트는 동안 다음 묶음을 받아 둔다. 못 받으면 남은 글은 기기 목소리. */
async function speakServer(text: string, rate: number): Promise<boolean> {
  const my = gen
  if (!text.trim()) return true
  const parts = chunks(text)
  let next = fetchSpeech(parts[0])
  for (let i = 0; i < parts.length; i++) {
    const b64 = await next
    if (my !== gen) return true // 기다리는 사이 멈췄다(다음 화면·다른 읽기) — 틀지 않는다
    if (!b64) return speakDevice(parts.slice(i).join(' '), rate)
    if (i + 1 < parts.length) next = fetchSpeech(parts[i + 1])
    try {
      const heard = await play(`data:audio/mpeg;base64,${b64}`, rate)
      if (my !== gen) return true // 우리가 멈췄다
      if (!heard) return false // 전화벨·알람이 소리를 멈췄다
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === 'NotAllowedError') return false
      return speakDevice(parts.slice(i).join(' '), rate)
    }
  }
  return true
}

/**
 * 브라우저 TTS(기기 목소리) — 서버 소리가 없을 때만. 없으면 바로 resolve (자막만).
 * 기기에 한국어 음성이 없어 onend/onerror 가 안 오면 글자 수 기준 시간 뒤 resolve.
 * 사용자 터치 전이라 막히면 false — 크롬은 speak() 안에서 바로 error 'not-allowed' 를 보낸다 (D48).
 */
function speakDevice(text: string, rate = 0.9): Promise<boolean> {
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

/** 재생 중인 서버 음성과 브라우저 TTS 를 모두 멈춘다. 서버 소리를 기다리던 읽기도 틀지 않게 된다 (D78). */
export function stopSpeaking() {
  gen++
  const a = current
  current = null // pause 이벤트보다 먼저 비운다: play() 가 '우리가 멈춤'으로 알아보게
  a?.pause()
  if ('speechSynthesis' in window) window.speechSynthesis.cancel()
}
