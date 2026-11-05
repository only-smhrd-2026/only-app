/** 녹음·재생·브라우저 TTS. VoiceSession 이 쓴다. 서버 STT/TTS 가 mock 인 동안 재생은 speechSynthesis (D5). */

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

/** 서버 TTS(base64 mp3) 재생. 끝나면 resolve. 자동재생이 막히면 reject. */
export function playBase64(b64: string, mime = 'audio/mpeg'): Promise<void> {
  return new Promise((resolve, reject) => {
    const audio = new Audio(`data:${mime};base64,${b64}`)
    audio.onended = () => resolve()
    audio.onerror = () => reject(new Error('audio'))
    audio.play().catch(reject)
  })
}

/** 브라우저 TTS. 없으면 바로 resolve (자막만). */
export function speak(text: string, rate = 0.85): Promise<void> {
  return new Promise((resolve) => {
    if (!('speechSynthesis' in window)) return resolve()
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.lang = 'ko-KR'
    u.rate = rate
    u.onend = () => resolve()
    u.onerror = () => resolve()
    window.speechSynthesis.speak(u)
  })
}

export function stopSpeaking() {
  if ('speechSynthesis' in window) window.speechSynthesis.cancel()
}
