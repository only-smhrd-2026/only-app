/**
 * 가족 홈 긴급 카드 (D55 마음 위급 + 11/19 몸 위급) — 위급 알림이 오면 가족 홈 맨 위에 보인다.
 * [제가 연락했어요]를 누르면 다른 가족에게 '○○님이 연락했어요'로 바뀌어 서로 미루지 않는다.
 * 30분 동안 아무도 안 누르면 서버가 한 번 더 알리고, 하루가 지나면 카드를 내린다 (backend/app/services/alerts.py).
 * 어르신이 하신 말은 여기에도 보이지 않는다 (D15).
 */
import { useState } from 'react'
import { api } from '../api/client'
import type { AlertOut } from '../api/types'
import { useFetch } from '../hooks/useFetch'
import './UrgentCard.css'

const GUIDE = {
  MOOD: {
    title: '지금 전화 한 통 드려 보세요',
    lines: [
      '많이 힘들어하시는 말씀이 있었어요. 무슨 말씀이었는지는 전하지 않아요.',
      '먼저 안부를 묻고 끝까지 들어 주세요. “힘내세요”보다 “많이 힘드셨겠어요”가 좋아요.',
      '혼자 계시면 곁에 있어 줄 분을 찾아 주세요.',
    ],
  },
  BODY: {
    title: '지금 바로 전화해 보세요',
    lines: [
      '몸이 많이 불편하다고 하셨어요.',
      '전화를 안 받으시면 가까이 사는 분께 가 봐 달라고 부탁하세요.',
      '숨쉬기 힘들어하시거나 의식이 흐리면 바로 119 에 알리세요.',
    ],
  },
} as const

const clock = (iso: string) => new Date(iso).toLocaleTimeString('ko-KR', { hour: 'numeric', minute: '2-digit' })

export default function UrgentCard({ roomId, who }: { roomId: number; who: string }) {
  const { data, reload } = useFetch<AlertOut | null>(`/api/rooms/${roomId}/alert`)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  if (!data) return null

  if (data.acked_at) {
    return (
      <section className="fam-card urgent urgent--done" role="status">
        <b>{data.acked_by_me ? '내가' : `${data.acked_by_name ?? '가족'}님이`} 연락했어요</b>
        <small>
          {clock(data.acked_at)} · {who} 급한 알림
        </small>
      </section>
    )
  }

  async function ack(alert: AlertOut) {
    setBusy(true)
    setFailed(false)
    try {
      await api(`/api/rooms/${roomId}/alerts/${alert.alert_id}/ack`, { method: 'POST' })
      reload()
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  const guide = GUIDE[data.kind]
  return (
    <section className="fam-card urgent" role="alert">
      <h2>{guide.title}</h2>
      <small>
        {who} · {clock(data.created_at)}
      </small>
      <ul>
        {guide.lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <p className="urgent-tel">
        {data.kind === 'MOOD' && <a href="tel:109">자살예방 상담전화 109</a>}
        <a href="tel:119">응급 119</a>
      </p>
      <button type="button" className="fam-btn fam-btn--block urgent-ack" disabled={busy} onClick={() => ack(data)}>
        제가 연락했어요
      </button>
      {failed && <p className="urgent-fail">저장하지 못했어요. 다시 눌러 주세요.</p>}
    </section>
  )
}
