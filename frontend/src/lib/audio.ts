/** 녹음·재생·브라우저 TTS. 서버 TTS 음성(audio_b64)은 playBase64, 그것이 없을 때(mock·실패)와 화면 고정 안내는 speechSynthesis (D5·D46). */

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

let current: HTMLAudioElement | null = null

/**
 * 서버 TTS(base64 mp3) 재생. 끝나면 resolve. 자동재생이 막히면 reject. stopSpeaking() 으로 멈출 수 있다.
 * rate = 말 속도(0.70·0.85·1.00). 서버는 1.0배로 합성하고 여기서 늦춘다 (D46). 음높이는 브라우저가 그대로 둔다.
 */
export function playBase64(b64: string, rate = 1, mime = 'audio/mpeg'): Promise<void> {
  return new Promise((resolve, reject) => {
    const audio = new Audio(`data:${mime};base64,${b64}`)
    audio.defaultPlaybackRate = audio.playbackRate = rate // default 도 같이: 다시 불러올 때 1.0 으로 돌아가지 않게
    current = audio
    audio.onended = () => resolve()
    audio.onpause = () => resolve() // stopSpeaking() 으로 멈춘 경우
    audio.onerror = () => reject(new Error('audio'))
    audio.play().catch(reject)
  })
}

/** 브라우저 TTS. 없으면 바로 resolve (자막만). 기기에 한국어 음성이 없어 onend/onerror 가 안 오면 글자 수 기준 시간 뒤 resolve. */
export function speak(text: string, rate = 0.85): Promise<void> {
  return new Promise((resolve) => {
    if (!('speechSynthesis' in window)) return resolve()
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.lang = 'ko-KR'
    u.rate = rate
    // ponytail: 안전장치. 실기기 음성 속도는 제각각이라 글자당 ~250ms + 2초를 상한으로 둔다
    const guard = setTimeout(resolve, Math.min(15_000, 2_000 + (text.length * 250) / rate))
    const done = () => {
      clearTimeout(guard)
      resolve()
    }
    u.onend = done
    u.onerror = done
    window.speechSynthesis.speak(u)
  })
}

/** 재생 중인 서버 음성과 브라우저 TTS 를 모두 멈춘다. */
export function stopSpeaking() {
  current?.pause()
  current = null
  if ('speechSynthesis' in window) window.speechSynthesis.cancel()
}
