/**
 * ELDER_CONNECT_001 — 어르신 기기 연결. 가족이 보낸 링크 /elder/connect#<토큰> 으로 들어온다 (D16, 토큰은 # 뒤).
 * [시작하기] → 기기 쿠키 발급 → 마이크 권한 → 어르신 홈. 디자인 없음 (김승희가 Figma 대로 교체, 권한 단계 포함).
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { DeviceOut, InviteStatusOut } from '../../api/types'

export default function ELDER_CONNECT_001() {
  const nav = useNavigate()
  const token = window.location.hash.slice(1)
  const [status, setStatus] = useState<InviteStatusOut>()
  const [error, setError] = useState<string | undefined>(
    token ? undefined : '링크가 올바르지 않아요. 가족에게 다시 받아 주세요.',
  )
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!token) return
    api<InviteStatusOut>('/api/invites/status', { body: { token } })
      .then(setStatus)
      .catch((e: ApiError) => setError(e.message))
  }, [token])

  async function start() {
    setBusy(true)
    try {
      await api<DeviceOut>('/api/devices/connect', { body: { token } })
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
      setError((e as ApiError).message)
      setBusy(false)
    }
  }

  return (
    <main className="elder">
      <p className="elder-text elder-text--lg">하루한장</p>
      {error && <p className="elder-text">{error}</p>}
      {status && !status.valid && <p className="elder-text">이 링크는 더 쓸 수 없어요. 가족에게 새 링크를 받아 주세요.</p>}
      {status?.valid && (
        <>
          <p className="elder-text">{status.elder_name} 님 전화기로 연결할까요?</p>
          <button className="elder-btn" onClick={start} disabled={busy}>
            {busy ? '연결 중…' : '시작하기'}
          </button>
        </>
      )}
    </main>
  )
}
