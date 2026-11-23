/**
 * 가족 홈 긴급 카드 (D55 마음 위급 + 11/19 몸 위급, 11/23 시안 f-home-urgent) — 위급 알림이 오면 가족 홈 맨 위에 보인다.
 * 행동 요령(연분홍 상자) → [○○께 전화하기](tel: 만 — 번호는 저장하지 않는다 D57) → 109·119 → [연락한 뒤 알려 주기].
 * 알려 주기 판: [통화했어요] = 다른 가족에게 '○○님이 연락했어요'(ack) · [안 받으세요 · 다른 가족에게 알리기] = 다른 가족에게
 * 전화해 달라고 알림(missed, 카드는 그대로 남음) · [아직이에요] = 판만 닫음.
 * 30분 동안 아무도 연락 안 하면 서버가 한 번 더 알리고, 하루가 지나면 카드를 내린다 (backend/app/services/alerts.py).
 * 어르신이 하신 말은 여기에도 보이지 않는다 (D15).
 */
import { useState } from 'react'
import { api } from '../api/client'
import type { AlertOut } from '../api/types'
import { useFetch } from '../hooks/useFetch'
import FamIcon from './FamIcon'
import './UrgentCard.css'

const GUIDE = {
  MOOD: {
    title: '지금 전화 한 통 드려 보세요',
    say: '많이 힘들어하시는 말씀이 있었어요. 무슨 말씀이었는지는 전하지 않아요.',
    tips: ['먼저 안부를 묻고 끝까지 들어 주세요.', '“힘내세요”보다 “많이 힘드셨겠어요”가 좋아요.', '혼자 계시면 곁에 있어 줄 분을 찾아 주세요.'],
  },
  BODY: {
    title: '지금 바로 전화해 보세요',
    say: '몸이 많이 불편하다고 하셨어요.',
    tips: ['전화를 안 받으시면 가까이 사는 분께 가 봐 달라고 부탁하세요.', '숨쉬기 힘들어하시거나 의식이 흐리면 바로 119 에 알리세요.'],
  },
} as const

// 받침이 있으면 '과', 없으면 '와' (끝 글자가 한글이 아니면 '와')
function wa(w: string) {
  const c = w.charCodeAt(w.length - 1) - 0xac00
  return c >= 0 && c <= 11171 && c % 28 ? '과' : '와'
}
const clock = (iso: string) => new Date(iso).toLocaleTimeString('ko-KR', { hour: 'numeric', minute: '2-digit' })

export default function UrgentCard({ roomId, who }: { roomId: number; who: string }) {
  const { data, reload } = useFetch<AlertOut | null>(`/api/rooms/${roomId}/alert`)
  const [sheet, setSheet] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  // '안 받으세요' 뒤에는 다시 읽은 카드에 missed_at·missed_by_name 이 실려 온다
  const alert = data
  if (!alert) return null

  if (alert.acked_at) {
    return (
      <section className="fam-card urgent urgent--done" role="status">
        <b>{alert.acked_by_me ? '내가' : `${alert.acked_by_name ?? '가족'}님이`} 연락했어요</b>
        <small>
          {clock(alert.acked_at)} · {who} 급한 알림
        </small>
      </section>
    )
  }

  async function send(kind: 'ack' | 'missed', a: AlertOut) {
    setBusy(true)
    setFailed(false)
    try {
      await api(`/api/rooms/${roomId}/alerts/${a.alert_id}/${kind}`, { method: 'POST' })
      setSheet(false)
      reload()
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  const guide = GUIDE[alert.kind]
  return (
    <section className="fam-card urgent" role="alert" aria-label="급한 알림">
      <h2>
        <FamIcon name="phone" />
        {guide.title}
      </h2>
      <p className="fam-mini">
        {clock(alert.created_at)} · {who} · 급한 알림
      </p>
      <p>{guide.say}</p>
      <ul className="urgent-tips">
        {guide.tips.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {/* 번호 없이 전화 앱만 연다 — 어르신 번호는 저장하지 않는다(D57) */}
      <a className="fam-btn fam-btn--primary" href="tel:">
        <FamIcon name="phone" />
        {who}께 전화하기
      </a>
      <div className="urgent-nums">
        {alert.kind === 'MOOD' && (
          <a href="tel:109">
            <FamIcon name="phone" />
            자살예방 상담 109
          </a>
        )}
        <a href="tel:119">
          <FamIcon name="phone" />
          응급 119
        </a>
      </div>
      {alert.missed_at && (
        <p className="urgent-missed" role="status">
          {alert.missed_by_name ?? '가족'}님이 {clock(alert.missed_at)}에 전화했는데 안 받으셨어요 · 다른 가족에게 알렸어요
        </p>
      )}
      <button type="button" className="fam-btn" onClick={() => (setFailed(false), setSheet(true))}>
        연락한 뒤 알려 주기
      </button>
      {failed && !sheet && <p className="urgent-fail">저장하지 못했어요. 다시 눌러 주세요.</p>}

      {sheet && (
        <>
          <button type="button" className="fam-scrim" aria-label="닫기" onClick={() => setSheet(false)} />
          <div className="fam-sheet" role="dialog" aria-label="통화 결과">
            <span className="fam-grab" />
            <h2>
              {who}
              {wa(who)} 통화하셨어요?
            </h2>
            <button type="button" className="fam-btn fam-btn--primary" disabled={busy} onClick={() => send('ack', alert)}>
              네, 통화했어요
            </button>
            <button type="button" className="fam-btn" disabled={busy} onClick={() => send('missed', alert)}>
              안 받으세요 · 다른 가족에게 알리기
            </button>
            <button type="button" className="fam-btn fam-btn--text" onClick={() => setSheet(false)}>
              아직이에요
            </button>
            {failed && <p className="urgent-fail">저장하지 못했어요. 다시 눌러 주세요.</p>}
          </div>
        </>
      )}
    </section>
  )
}
