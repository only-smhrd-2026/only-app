/**
 * ELDER_CONNECT_001 — 어르신 기기 연결. 가족이 보낸 링크 /elder/connect#<토큰> 으로 들어온다 (D16, 토큰은 # 뒤).
 * [시작하기] → 기기 쿠키 발급 → 마이크 권한 → 목소리 고르기(여자·남자, D74) → 어르신 홈.
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { DeviceOut, InviteStatusOut } from '../../api/types'
import connectPreview from '../../assets/elder-connect-preview.svg'
import { PROMPT, say, setVoice, speak, stopSpeaking } from '../../lib/audio'
import './ELDER_CONNECT_001.css'

const VOICES = [
  ['FEMALE', '여자 목소리'],
  ['MALE', '남자 목소리'],
] as const

export default function ELDER_CONNECT_001() {
  const nav = useNavigate()
  const token = window.location.hash.slice(1)
  const [status, setStatus] = useState<InviteStatusOut>()
  const [error, setError] = useState<string | undefined>(
    token ? undefined : '링크가 올바르지 않아요. 가족에게 다시 받아 주세요.',
  )
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState<'invite' | 'permissions' | 'voice'>('invite')
  const [picked, setPicked] = useState<'FEMALE' | 'MALE'>()
  const connected = useRef(false)

  useEffect(() => {
    if (!token) return
    api<InviteStatusOut>('/api/invites/status', { body: { token } })
      .then(async (s) => {
        // 이미 연결된 폰이 쓴 링크를 다시 연 경우(카톡의 같은 링크를 또 누름, 연결 도중 새로고침):
        // '이 링크는 더 쓸 수 없어요'에서 막히지 않게 홈으로 보낸다. 기기 쿠키가 살아 있으면 홈이 열린다
        if (!s.valid && (await api('/api/elder/home').then(() => true, () => false))) return nav('/elder', { replace: true })
        setStatus(s)
      })
      .catch((e: ApiError) => setError(e.message))
  }, [token, nav])

  async function start() {
    if (busy) return
    stopSpeaking() // 앞서 읽던 오류 문장을 끊는다 — 다시 눌러 성공하면 홈까지 이어져 읽힌다
    setBusy(true)
    setError(undefined)
    try {
      if (!connected.current) {
        await api<DeviceOut>('/api/devices/connect', { body: { token } })
        connected.current = true // 권한 저장을 다시 시도해도 일회용 링크는 다시 쓰지 않는다
      }
      setStep('permissions') // 주소·기록은 그대로 둔다 — 한 번 쓴 초대 링크로 돌아가지 않게
      await navigator.storage?.persist?.().catch(() => false) // 설치 직후 1회, 쿠키·캐시가 지워지지 않게 (D2)
      let perm_mic = false
      try {
        const s = await navigator.mediaDevices.getUserMedia({ audio: true })
        s.getTracks().forEach((t) => t.stop())
        perm_mic = true
      } catch {
        /* 거부해도 버튼 모드로 진행 */
      }
      await api('/api/devices/me/permissions', { method: 'PATCH', body: { perm_mic } })
      setStep('voice')
      setBusy(false)
      void say(PROMPT.voiceAsk, 0.9, null, 'FEMALE') // 고르기 전이라 기본(여자) 목소리로 묻는다 (D74)
    } catch (e) {
      fail(e)
    }
  }

  // 누르면 그 목소리로 인사 한 마디 + 고름. 다시 누르면 다시 들려준다 (D74)
  function listen(v: 'FEMALE' | 'MALE') {
    setPicked(v)
    void say(PROMPT.voiceHello, 0.9, null, v)
  }

  // 고른 목소리를 가족방에 저장하고, 이 폰의 고정 안내도 그 목소리로 → 홈
  async function choose() {
    if (!picked || busy) return
    stopSpeaking()
    setBusy(true)
    setError(undefined)
    try {
      await api('/api/elder/voice', { body: { voice: picked } })
      setVoice(picked)
      nav('/elder', { replace: true })
    } catch (e) {
      fail(e)
    }
  }

  function fail(e: unknown) {
    // 서버 문장이 아닌 오류(응답이 중간에 끊김 등)는 영어라 그대로 보여 주거나 읽지 않는다
    const message = e instanceof ApiError ? e.message : '연결하지 못했어요. 다시 눌러 주세요.'
    setError(message)
    void speak(message)
    setBusy(false)
  }

  return (
    <main className="elder elder--fit elder-connect">
      <header className="elder-connect-header">
        <h1 className="elder-text elder-text--lg">{step === 'invite' ? '하루한장' : '처음 연결'}</h1>
        {step === 'invite' && <p className="elder-text">가족 사진을 보며 이야기하고, 그림일기를 써서 가족과 나누는 앱이에요.</p>}
      </header>
      {step === 'invite' && <img className="elder-connect-photo" src={connectPreview} alt="" />}
      {error && <p className="elder-text elder-connect-message" role="alert">{error}</p>}
      {status && !status.valid && <p className="elder-text elder-connect-message">이 링크는 더 쓸 수 없어요. 가족에게 새 링크를 받아 주세요.</p>}
      {status?.valid && step === 'invite' && (
        <>
          <h2 className="elder-text elder-connect-invitation">{status.elder_name} 님,<br />가족이 초대했어요</h2>
          <p className="elder-text">아래를 한 번 눌러 주세요</p>
        </>
      )}
      {step === 'permissions' && (
        <div className="elder-connect-permissions" aria-live="polite">
          <p className="elder-text elder-connect-bubble">안녕하세요,<br />저는 꼬마심심이예요.<br />마이크를 허락해 주세요.</p>
          <p className="elder-text elder-connect-mic">마이크로 말씀을 들어요.</p>
          <p className="elder-text elder-connect-guide">휴대폰에서 마이크 권한을 물으면 ‘허용’을 눌러 주세요. 허용하지 않아도 시작할 수 있어요.</p>
          {busy && <p className="elder-text" role="status">연결 중…</p>}
        </div>
      )}
      {step === 'voice' && (
        <div className="elder-connect-voice" aria-live="polite">
          <p className="elder-text elder-connect-bubble">어떤 목소리가 좋으세요?<br />눌러서 들어 보세요.</p>
          {VOICES.map(([v, label]) => (
            <button
              key={v}
              type="button"
              className="elder-btn elder-btn--secondary elder-connect-voice-btn"
              aria-pressed={picked === v}
              onClick={() => listen(v)}
            >
              <svg className="elder-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M4 9.5v5h3.2L12 18.5v-13L7.2 9.5z" />
                <path d="M15.5 9a4.2 4.2 0 0 1 0 6M18.3 6.3a8 8 0 0 1 0 11.4" />
              </svg>
              {label}
              {picked === v && (
                <svg className="elder-ic elder-connect-ok" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M5 12.5l4.5 4.5L19 7.5" />
                </svg>
              )}
            </button>
          ))}
          <p className="elder-text elder-connect-guide">나중에 가족이 설정에서 바꿀 수 있어요.</p>
        </div>
      )}
      {step === 'voice' && (
        <button className="elder-btn elder-connect-start" onClick={choose} disabled={!picked || busy}>
          {busy ? '저장 중…' : '이 목소리로 할게요'}
        </button>
      )}
      {status?.valid && step !== 'voice' && (
        <>
          <button className="elder-btn elder-connect-start" onClick={start} disabled={busy}>
            {busy ? '연결 중…' : '시작하기'}
          </button>
          {step === 'invite' && <aside className="elder-connect-install" aria-label="홈 화면에 추가 안내">
            <p className="elder-text elder-connect-guide">연결한 뒤 크롬 ⋮ 에서 ‘홈 화면에 추가’를 누르면 다음부터 바로 열려요.</p>
          </aside>}
        </>
      )}
    </main>
  )
}
