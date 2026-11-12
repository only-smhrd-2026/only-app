/**
 * ELDER_CONNECT_001 — 어르신 기기 연결. 가족이 보낸 링크 /elder/connect#<토큰> 으로 들어온다 (D16, 토큰은 # 뒤).
 * [시작하기] → 기기 쿠키 발급 → 마이크 권한 → 어르신 홈.
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { DeviceOut, InviteStatusOut } from '../../api/types'
import connectPreview from '../../assets/elder-connect-preview.svg'
import { speak } from '../../lib/audio'
import './ELDER_CONNECT_001.css'

export default function ELDER_CONNECT_001() {
  const nav = useNavigate()
  const token = window.location.hash.slice(1)
  const [status, setStatus] = useState<InviteStatusOut>()
  const [error, setError] = useState<string | undefined>(
    token ? undefined : '링크가 올바르지 않아요. 가족에게 다시 받아 주세요.',
  )
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState<'invite' | 'permissions'>('invite')
  const connected = useRef(false)

  useEffect(() => {
    if (!token) return
    api<InviteStatusOut>('/api/invites/status', { body: { token } })
      .then(setStatus)
      .catch((e: ApiError) => setError(e.message))
  }, [token])

  async function start() {
    if (busy) return
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
      nav('/elder', { replace: true })
    } catch (e) {
      const message = (e as ApiError).message
      setError(message)
      void speak(message)
      setBusy(false)
    }
  }

  return (
    <main className="elder elder-connect">
      <header className="elder-connect-header">
        <h1 className="elder-text elder-text--lg">{step === 'invite' ? '하루한장' : '처음 연결'}</h1>
        {step === 'invite' && <p className="elder-text">가족 사진으로 매일 이야기 나눠요</p>}
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
          <p className="elder-text">휴대폰에서 마이크 권한을 물으면 ‘허용’을 눌러 주세요. 허용하지 않아도 시작할 수 있어요.</p>
          {busy && <p className="elder-text" role="status">연결 중…</p>}
        </div>
      )}
      {status?.valid && (
        <>
          <button className="elder-btn elder-connect-start" onClick={start} disabled={busy}>
            {busy ? '연결 중…' : '시작하기'}
          </button>
          {step === 'invite' && <aside className="elder-connect-install" aria-label="홈 화면에 추가 안내">
            <p className="elder-text">휴대폰 홈 화면에 하루한장을 놓아 두면 다음부터 바로 열 수 있어요.</p>
            <p className="elder-text">연결한 뒤 크롬 오른쪽 위 ⋮ 를 누르고 ‘홈 화면에 추가’를 눌러 주세요.</p>
          </aside>}
        </>
      )}
    </main>
  )
}
