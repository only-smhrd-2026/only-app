/**
 * ELDER_CONNECT_001 — 어르신 기기 연결 (11/23 시안 e-connect → e-fontpick → e-voice). 가족이 보낸 링크 /elder/connect#<토큰> (D16, 토큰은 # 뒤).
 * [시작하기] → 기기 쿠키 발급 → 마이크 안내(허용 창 그림) → [다음] 에 마이크·알림 권한을 묻는다 → 글자 크기(22·24·28) → 목소리(여자·남자, D74) → 홈.
 * 글자 크기·목소리는 나중에 홈의 설정(ELDER_SETTING_001)에서 바꿀 수 있다.
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { DeviceOut, ElderSettingsOut, InviteStatusOut } from '../../api/types'
import { Bub, IC } from '../../components/ElderUi'
import Sim from '../../components/Sim'
import { PROMPT, say, setVoice, speak, stopSpeaking } from '../../lib/audio'
import { setElderFont } from '../../lib/elderFont'
import { ELDER_PUSH, enablePush, pushKey, pushSupported } from '../../lib/push'
import './ELDER_CONNECT_001.css'

const VOICES = [['FEMALE', '여자 목소리'], ['MALE', '남자 목소리']] as const
const FONTS = [['L', '보통', 22], ['XL', '크게', 24], ['XXL', '아주 크게', 28]] as const
type Font = (typeof FONTS)[number][0]
const MIC = '안녕하세요, 저는 꼬마심심이예요. 마이크로 말씀을 들어요. 이런 창이 뜨면 방문 중 허용을 눌러 주세요.'
const FONT_ASK = '글자가 잘 보이세요? 제일 편한 크기를 눌러 주세요.'
const CARE_NOTE = '힘든 말씀을 하시면 가족에게도 알려요.' // 마음 알림 동의 (D55·D94 — 전화 버튼은 없어서 '통화' 말은 뺌)

export default function ELDER_CONNECT_001() {
  const nav = useNavigate()
  const token = window.location.hash.slice(1)
  const [status, setStatus] = useState<InviteStatusOut>()
  const [error, setError] = useState<string | undefined>(
    token ? undefined : '링크가 올바르지 않아요. 가족에게 다시 받아 주세요.',
  )
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState<'invite' | 'permissions' | 'font' | 'voice'>('invite')
  const [font, setFont] = useState<Font>(() => {
    const now = document.documentElement.dataset.font
    return now === 'L' || now === 'XXL' ? now : 'XL'
  })
  const [picked, setPicked] = useState<'FEMALE' | 'MALE'>('FEMALE')
  const connected = useRef(false)
  const name = status ? `${status.elder_name} 님` : ''
  const guidance = error ?? {
    invite: status
      ? status.valid
        ? `하루한장. ${name}, 가족이 초대했어요. ${CARE_NOTE} 아래 시작하기를 한 번 눌러 주세요.`
        : '이 링크는 더 쓸 수 없어요. 가족에게 새 링크를 받아 주세요.'
      : undefined,
    permissions: MIC,
    font: FONT_ASK,
    voice: undefined, // 아래에서 고정 안내 mp3 로
  }[step]

  useEffect(() => {
    if (!guidance) return
    let alive = true
    const retry = () => {
      window.removeEventListener('pointerup', retry)
      window.removeEventListener('keydown', retry)
      void speak(guidance)
    }
    void speak(guidance).then((heard) => {
      if (heard || !alive) return
      window.addEventListener('pointerup', retry, { once: true })
      window.addEventListener('keydown', retry, { once: true })
    })
    return () => {
      alive = false
      window.removeEventListener('pointerup', retry)
      window.removeEventListener('keydown', retry)
      stopSpeaking()
    }
  }, [guidance])

  useEffect(() => {
    if (step !== 'voice') return
    void say(PROMPT.voiceAsk, 0.9, null, 'FEMALE') // 고르기 전이라 기본(여자) 목소리로 묻는다 (D74)
    return () => stopSpeaking()
  }, [step])

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

  function fail(e: unknown) {
    // 서버 문장이 아닌 오류(응답이 중간에 끊김 등)는 영어라 그대로 보여 주거나 읽지 않는다
    setError(e instanceof ApiError ? e.message : '연결하지 못했어요. 다시 눌러 주세요.')
    setBusy(false)
  }

  /** [시작하기] — 일회용 링크로 기기 쿠키를 받는다. 주소·기록은 그대로(한 번 쓴 초대 링크로 돌아가지 않게) */
  async function start() {
    if (busy) return
    stopSpeaking()
    setBusy(true)
    setError(undefined)
    try {
      if (!connected.current) {
        await api<DeviceOut>('/api/devices/connect', { body: { token } })
        connected.current = true
      }
      setStep('permissions')
      setBusy(false)
    } catch (e) {
      fail(e)
    }
  }

  /** 마이크 안내의 [다음] — 안내를 듣고 난 뒤에 폰이 허용 창을 띄운다. 거부해도 버튼으로 답하며 진행 */
  async function allow() {
    if (busy) return
    stopSpeaking()
    setBusy(true)
    setError(undefined)
    try {
      await navigator.storage?.persist?.().catch(() => false) // 설치 직후 1회, 쿠키·캐시가 지워지지 않게 (D2)
      let perm_mic = false
      try {
        const s = await navigator.mediaDevices.getUserMedia({ audio: true })
        s.getTracks().forEach((t) => t.stop())
        perm_mic = true
      } catch {
        /* 거부해도 버튼 모드로 진행 */
      }
      // 알림 — 허용하면 이 폰을 구독시켜 추억·일기 시간에 폰 알림(웹 푸시)을 받는다 (lib/push). 거부해도 진행.
      // 푸시를 쓰는 서버·브라우저에서만 묻는다 — 아니면 칸을 비워(undefined) 마이크만 알린다
      const perm_notification = pushSupported() && (await pushKey())
        ? (await enablePush(ELDER_PUSH).catch(() => 'off')) === 'on'
        : undefined
      await api('/api/devices/me/permissions', { method: 'PATCH', body: { perm_mic, perm_notification } })
      setStep('font')
      setBusy(false)
    } catch (e) {
      fail(e)
    }
  }

  function pickFont(f: Font) {
    setFont(f)
    setElderFont(f) // 누르는 대로 화면 글자가 바로 바뀐다
  }

  async function saveFont() {
    if (busy) return
    stopSpeaking()
    setBusy(true)
    setError(undefined)
    try {
      const s = await api<ElderSettingsOut>('/api/elder/settings', { method: 'PATCH', body: { font_size: font } })
      setElderFont(s.font_size)
      setStep('voice')
      setBusy(false)
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
    if (busy) return
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

  const tick = <span className="elder-tick">{IC.check}</span>
  const errorLine = error && <p className="elder-text" role="alert">{error}</p>

  if (step === 'permissions')
    return (
      <main className="elder elder--fit">
        <h1>마이크를 허락해 주세요</h1>
        <div className="elder-greet">
          <Sim face="hello" size={84} className="elder-sim" />
          <Bub text="저는 꼬마심심이예요. 마이크로 말씀을 들어요." speed={0.9} className="elder-bub--tail" />
        </div>
        <div className="econ-perm elder-grow" aria-hidden="true">
          <div className="econ-perm-box">
            <b>마이크를 사용하도록 허용할까요?</b>
            <span className="econ-perm-row"><i className="yes">방문 중 허용</i><i>이번만 허용</i><i>허용 안함</i></span>
          </div>
        </div>
        <p className="econ-perm-cap">이런 창이 뜨면 <b>‘방문 중 허용’</b>을 눌러 주세요</p>
        {errorLine}
        <button type="button" className="elder-btn" onClick={() => void allow()} disabled={busy}>{busy ? '잠시만요…' : '다음'}</button>
      </main>
    )

  if (step === 'font')
    return (
      <main className="elder elder--fit">
        <h1>글자가 잘 보이세요?</h1>
        <div className="elder-greet">
          <Sim face="curious" size={84} className="elder-sim" />
          <Bub text="제일 편한 크기를 눌러 주세요." speed={0.9} className="elder-bub--tail" />
        </div>
        <div className="elder-col elder-grow">
          {FONTS.map(([f, label, px]) => (
            <button
              key={f}
              type="button"
              className={`elder-btn elder-btn--secondary elder-btn--wide${font === f ? ' elder-btn--on' : ''}`}
              style={{ fontSize: px }}
              aria-pressed={font === f}
              onClick={() => pickFont(f)}
            >
              가나다 · {label}
              {font === f && tick}
            </button>
          ))}
        </div>
        {errorLine}
        <button type="button" className="elder-btn" onClick={() => void saveFont()} disabled={busy}>{busy ? '잠시만요…' : '이 크기로 할게요'}</button>
      </main>
    )

  if (step === 'voice')
    return (
      <main className="elder elder--fit">
        <h1>어떤 목소리가 좋으세요?</h1>
        <div className="elder-greet">
          <Sim face="curious" size={84} className="elder-sim" />
          <Bub text="눌러서 들어 보세요." speed={0.9} className="elder-bub--tail" />
        </div>
        <div className="elder-col">
          {VOICES.map(([v, label]) => (
            <button
              key={v}
              type="button"
              className={`elder-btn elder-btn--secondary elder-btn--wide${picked === v ? ' elder-btn--on' : ''}`}
              aria-pressed={picked === v}
              onClick={() => listen(v)}
            >
              <span className="elder-lead">{IC.spk}</span>
              {label}
              {picked === v && tick}
            </button>
          ))}
        </div>
        <p className="elder-sub elder-grow">나중에 홈의 설정에서 바꿀 수 있어요.</p>
        {errorLine}
        <button type="button" className="elder-btn" onClick={() => void choose()} disabled={busy}>{busy ? '저장 중…' : '이 목소리로 할게요'}</button>
      </main>
    )

  return (
    <main className="elder elder--fit">
      <div className="elder-grow elder-center">
        <div className="elder-halo"><Sim face="hello" size={150} className="elder-sim" /></div>
        <p className="elder-eyebrow">하루한장</p>
        {status?.valid && <h1>{name},<br />가족이 초대했어요</h1>}
        <p className="elder-sub">가족 사진을 보며 이야기하고, 그림일기를 써서 가족과 나누는 앱이에요.</p>
      </div>
      {status && !status.valid && <p className="elder-text">이 링크는 더 쓸 수 없어요. 가족에게 새 링크를 받아 주세요.</p>}
      {errorLine}
      {status?.valid && (
        <>
          <div className="elder-info">{IC.phone}<span>{CARE_NOTE}</span></div>
          <button type="button" className="elder-btn" onClick={() => void start()} disabled={busy}>{busy ? '연결 중…' : '시작하기'}</button>
        </>
      )}
    </main>
  )
}
