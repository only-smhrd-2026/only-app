/**
 * GROUP_002 — 가족방 초대·구성원 (FR-AD-004, 이슈 #24). 방장이 링크 종류를 골라 만들고 복사·보내기·폐기한다.
 * 주소(토큰)는 이 화면 state 에만 둔다 (D16 — localStorage·console 금지). 서버는 토큰을 저장하지 않아 나가면 다시 못 본다.
 * 구성원 목록·기기 상태는 서버 주소가 아직 없어 '준비 중'.
 */
import { useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { InviteCreatedOut, InviteKind, InviteOut, RoomOut } from '../../api/types'
import { useFetch } from '../../hooks/useFetch'
import './GROUP_001.css'

const KINDS: { kind: InviteKind; label: string; hint: string }[] = [
  { kind: 'FAMILY', label: '가족용', hint: '7일 동안 쓸 수 있어요. 가족이 링크를 눌러 이름과 관계를 정하고 들어와요' },
  { kind: 'ELDER_DEVICE', label: '어르신 기기용', hint: '24시간 안에 한 번만 쓸 수 있어요. 사진을 3장 이상 올린 뒤에 만들 수 있어요' },
]
const labelOf = (kind: InviteKind) => KINDS.find((k) => k.kind === kind)?.label

/** 남은 시간 — 24시간 이하면 'N시간 남음', 넘으면 'N일 남음' (올림: 방금 만든 가족용 7일, 기기용 24시간).
 * 1분을 빼고 올린다 — 폰 시계가 서버보다 몇 초 늦으면 방금 만든 링크가 '8일'·'2일'로 보인다 */
function timeLeft(expiresAt: string) {
  const ms = new Date(expiresAt).getTime() - Date.now() - 60_000
  return ms <= 86_400_000 ? `${Math.ceil(ms / 3_600_000)}시간 남음` : `${Math.ceil(ms / 86_400_000)}일 남음`
}

export default function GROUP_002() {
  const { roomId } = useParams()
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  const room = rooms.data?.find((r) => String(r.room_id) === roomId)
  // 링크 목록은 방장만 부를 수 있다 — 방장이 아니면 부르지 않는다
  const invites = useFetch<InviteOut[]>(room?.is_owner ? `/api/rooms/${roomId}/invites` : null)
  const [kind, setKind] = useState<InviteKind>('FAMILY')
  const [urls, setUrls] = useState<Partial<Record<InviteKind, string>>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError>()
  const [copyNote, setCopyNote] = useState<{ kind: InviteKind; text: string }>()

  async function create() {
    if (busy) return
    setBusy(true)
    setError(undefined)
    setCopyNote(undefined) // 앞 주소의 '복사했어요'가 새 주소 옆에 남지 않게
    try {
      const created = await api<InviteCreatedOut>(`/api/rooms/${roomId}/invites`, { body: { kind } })
      setUrls((u) => ({ ...u, [created.kind]: created.url }))
      invites.reload()
    } catch (e) {
      setError(e as ApiError)
    }
    setBusy(false)
  }

  async function revoke(k: InviteKind) {
    if (busy) return
    setBusy(true)
    setError(undefined)
    setCopyNote(undefined)
    try {
      await api(`/api/rooms/${roomId}/invites/${k}`, { method: 'DELETE' })
      setUrls((u) => ({ ...u, [k]: undefined })) // 폐기한 링크 주소는 화면에서도 지운다
      invites.reload()
    } catch (e) {
      setError(e as ApiError)
    }
    setBusy(false)
  }

  function copy(k: InviteKind, url: string) {
    // http 주소 등 복사 기능이 없는 곳에서는 navigator.clipboard 가 없어 바로 오류 → 같이 잡는다
    Promise.resolve()
      .then(() => navigator.clipboard.writeText(url))
      .then(
        () => setCopyNote({ kind: k, text: '복사했어요' }),
        () => setCopyNote({ kind: k, text: '복사하지 못했어요. 주소를 길게 눌러 복사해 주세요' }),
      )
  }

  if (rooms.error?.status === 401) return <Navigate to="/login" replace />
  if (rooms.error) {
    return (
      <main className="page fam-skin">
        <p className="error">{rooms.error.message}</p>
        <button className="btn" onClick={rooms.reload}>다시 시도</button>
      </main>
    )
  }
  if (!rooms.data) return <main className="page fam-skin"><p className="muted">불러오는 중…</p></main>
  if (!room) {
    return (
      <main className="page fam-skin">
        <p>가족방을 찾을 수 없어요</p>
        <Link className="btn" to="/">가족 홈으로</Link>
      </main>
    )
  }

  const alive = invites.data ?? []
  const hint = KINDS.find((k) => k.kind === kind)?.hint

  return (
    <main className="page fam-skin">
      <h1>{room.elder_name} {room.elder_honorific} 가족방</h1>
      <section className="card">
        <p><strong>초대 링크</strong></p>
        {!room.is_owner ? (
          <p className="muted">초대 링크는 방장만 만들 수 있어요</p>
        ) : (
          <div className="form">
            <fieldset className="chips">
              <legend>링크 종류</legend>
              <div className="row">
                {KINDS.map((k) => (
                  <label key={k.kind} className="chip">
                    <input
                      type="radio"
                      name="invite_kind"
                      checked={kind === k.kind}
                      onChange={() => (setKind(k.kind), setError(undefined))}
                    />
                    {k.label}
                  </label>
                ))}
              </div>
            </fieldset>
            <p className="muted">{hint}</p>
            {alive.some((i) => i.kind === kind) && <p>새로 만들면 전에 보낸 링크는 더 쓸 수 없어요</p>}
            <button className="btn" onClick={create} disabled={busy}>{busy ? '만드는 중…' : '링크 만들기'}</button>
            {error && (
              <div className="row">
                <p className="error" role="alert">{error.message}</p>
                {error.code === 'NEED_PHOTOS' && <Link className="btn secondary" to="/upload">사진 올리기</Link>}
              </div>
            )}
            {KINDS.map(({ kind: k, label }) => {
              const url = urls[k]
              if (!url) return null
              return (
                <div key={k}>
                  <p className="mono">{label} 링크<br />{url}</p>
                  <div className="row">
                    <button className="btn secondary" onClick={() => copy(k, url)}>복사</button>
                    {'share' in navigator && (
                      <button
                        className="btn secondary"
                        // 기기용 링크를 가족이 열어 [시작하기]를 누르면 그 폰이 어르신 기기가 되고 원래 기기는 끊긴다
                        onClick={() => navigator.share(k === 'ELDER_DEVICE' ? { url, text: '어르신 폰에서만 열어 주세요.' } : { url }).catch(() => {})}
                      >
                        보내기
                      </button>
                    )}
                    {copyNote?.kind === k && <span className="muted">{copyNote.text}</span>}
                  </div>
                </div>
              )
            })}
            {(urls.FAMILY || urls.ELDER_DEVICE) && (
              <p className="muted">이 주소는 지금만 보여요. 화면을 나가면 다시 볼 수 없어요(새로 만들어야 해요)</p>
            )}
            {invites.error && <p className="error">{invites.error.message}</p>}
            {alive.length > 0 && <p><strong>쓸 수 있는 링크</strong></p>}
            {alive.map((i) => (
              <div key={i.kind} className="row">
                <span>{labelOf(i.kind)} · {timeLeft(i.expires_at)}</span>
                <button className="btn secondary" onClick={() => revoke(i.kind)} disabled={busy}>폐기</button>
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="card">
        <p><strong>구성원</strong></p>
        <p className="muted">구성원 목록은 준비 중이에요</p>
      </section>
    </main>
  )
}
