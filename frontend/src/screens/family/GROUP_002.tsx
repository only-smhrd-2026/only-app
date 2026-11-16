/**
 * GROUP_002 — 가족방 탭 (목업 설계자료/목업_1115_가족 ⑥, 이슈 #24). 위 막대에서 고른 분의 가족방 한 화면:
 * 할머니 폰(연결 상태·연결 해제·링크 보내기) → '올린 사진 n장 ›'(GROUP_004) → 구성원(초대·내보내기·쓸 수 있는 링크).
 * 버튼은 방장에게만. 할머니 화면 설정 카드는 다음 칸(#52).
 * 링크 주소(토큰)는 이 화면 state 에만 둔다 (D16 — localStorage·console 금지). 서버는 토큰을 저장하지 않아 나가면 다시 못 본다.
 */
import { useEffect, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { InviteCreatedOut, InviteKind, InviteOut, MemberOut, RelationTag, RoomOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import { Avatar } from '../../components/FamilyFrame'
import { useFamily } from '../../hooks/useFamily'
import { useFetch } from '../../hooks/useFetch'
import './GROUP_002.css'

const RELATION: Record<RelationTag, string> = { CHILD: '자녀', GRANDCHILD: '손주', OTHER: '기타' }

type Sheet =
  | { t: 'invite'; kind: InviteKind }
  | { t: 'member'; m: MemberOut }
  | { t: 'kick'; m: MemberOut }
  | { t: 'unlink' }

// 받침이 있으면 '과', 없으면 '와' — 할머니와 / 어머님과 (GROUP_004 와 같은 식)
// 끝 글자가 한글이 아니면(예: 할머니2) '와' — 계산이 음수가 돼 '과'로 잘못 고르지 않게
function wa(w: string) {
  const c = w.charCodeAt(w.length - 1) - 0xac00
  return c >= 0 && c <= 11171 && c % 28 ? '과' : '와'
}
const msgOf = (e: unknown) => (e instanceof ApiError ? e.message : '잘 안 됐어요. 다시 해 주세요')

/** 남은 시간 — 24시간 이하면 'N시간 남음', 넘으면 'N일 남음' (올림: 방금 만든 가족용 7일, 기기용 24시간).
 * 1분을 빼고 올린다 — 폰 시계가 서버보다 몇 초 늦으면 방금 만든 링크가 '8일'·'2일'로 보인다 */
function timeLeft(expiresAt: string) {
  const ms = new Date(expiresAt).getTime() - Date.now() - 60_000
  return ms <= 86_400_000 ? `${Math.ceil(ms / 3_600_000)}시간 남음` : `${Math.ceil(ms / 86_400_000)}일 남음`
}

/** 마지막으로 연 때 — '오늘 오전 9:12' · '어제 오후 3:05' · '11월 14일 오전 9:12' (한국 시간, D12) */
function seenLabel(iso: string) {
  const KST = { timeZone: 'Asia/Seoul' } as const
  const d = new Date(iso)
  const dayOf = (x: Date) => x.toLocaleDateString('sv-SE', KST)
  const time = d.toLocaleTimeString('ko-KR', { ...KST, hour: 'numeric', minute: '2-digit' })
  if (dayOf(d) === dayOf(new Date())) return `오늘 ${time}`
  if (dayOf(d) === dayOf(new Date(Date.now() - 86_400_000))) return `어제 ${time}`
  return `${d.toLocaleDateString('ko-KR', { ...KST, month: 'long', day: 'numeric' })} ${time}`
}

/** 위 막대에서 다른 분으로 바꾸면 주소의 방 번호만 바뀌고 화면은 그대로 남는다 →
 * key 로 화면을 새로 그려 앞 방의 구성원·링크·판이 새 방 아래에 남지 않게 한다 */
export default function GROUP_002() {
  const { roomId } = useParams()
  return <RoomTab key={roomId} />
}

function RoomTab() {
  const { roomId } = useParams()
  const { me, reloadRooms } = useFamily()
  // 이 탭을 열 때마다 새로 읽는다 — 갤럭시를 연결하고 돌아오면 '연결됐어요', 사진을 올리고 오면 사진 수가 바뀐다
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  const room = rooms.data?.find((r) => String(r.room_id) === roomId)
  const members = useFetch<MemberOut[]>(room ? `/api/rooms/${roomId}/members` : null)
  // 링크 목록은 방장만 부를 수 있다 — 방장이 아니면 부르지 않는다
  const invites = useFetch<InviteOut[]>(room?.is_owner ? `/api/rooms/${roomId}/invites` : null)
  const [sheet, setSheet] = useState<Sheet>()
  // 보내기·복사가 안 됐을 때 판 안에 보여 줄 주소 — 서버가 다시 보여 주지 않으므로 판을 닫거나 칩을 바꿔도 이 화면에 있는 동안 둔다
  const [made, setMade] = useState<Partial<Record<InviteKind, string>>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [note, setNote] = useState<string>()

  useEffect(() => {
    if (!note) return
    const timer = window.setTimeout(() => setNote(undefined), 2600)
    return () => window.clearTimeout(timer)
  }, [note])

  const open = (s: Sheet) => (setError(undefined), setSheet(s))
  const close = () => (setSheet(undefined), setError(undefined))

  /** 서버에 바꾸기를 보내고 → 다시 읽고 → 판을 닫고 → 한 줄 알림. 두 번 눌러도 한 번만 (busy) */
  async function change(path: string, done: string, after: () => void) {
    if (busy) return
    setBusy(true)
    setError(undefined)
    try {
      await api(path, { method: 'DELETE' })
      after()
      setSheet(undefined)
      setNote(done)
    } catch (e) {
      setError(msgOf(e))
    }
    setBusy(false)
  }

  /** [링크 만들고 보내기] — 폰 공유 창(카카오톡·문자), 없으면 복사, 둘 다 안 되면 판 안에 주소 (HOME_001 시작 3단계와 같은 방법) */
  async function makeLink(r: RoomOut, kind: InviteKind) {
    if (busy) return
    setBusy(true)
    setError(undefined)
    try {
      const created = await api<InviteCreatedOut>(`/api/rooms/${r.room_id}/invites`, { body: { kind } })
      invites.reload()
      const text =
        kind === 'ELDER_DEVICE'
          ? `${r.elder_honorific} 폰에서 이 링크를 열어 주세요 — 하루한장`
          : `${r.elder_name} ${r.elder_honorific}네 가족방에 초대해요 — 하루한장`
      let done: string | undefined
      if (navigator.share) {
        // 공유 창을 그냥 닫으면 실패로 온다 → 주소를 보여 줘 다시 보내거나 복사할 수 있게
        done = await navigator.share({ text, url: created.url }).then(
          () => '링크를 보냈어요',
          () => undefined,
        )
      } else if (navigator.clipboard) {
        done = await navigator.clipboard.writeText(created.url).then(
          () => '링크를 복사했어요 · 붙여 넣어 보내 주세요',
          () => undefined,
        )
      }
      // 새 링크를 만들면 전 주소는 못 쓴다 → 보냈으면 지우고, 못 보냈으면 새 주소로 바꾼다
      setMade((m) => ({ ...m, [kind]: done ? undefined : created.url }))
      if (done) {
        setSheet(undefined)
        setNote(done)
      }
    } catch (e) {
      setError(msgOf(e))
    }
    setBusy(false)
  }

  if (rooms.error?.status === 401) return <Navigate to="/login" replace />
  if (rooms.error) {
    return (
      <main className="fam-stack">
        <p className="fam-error">{rooms.error.message}</p>
        <button type="button" className="fam-text-btn" onClick={rooms.reload}>
          다시 시도
        </button>
      </main>
    )
  }
  if (!rooms.data) return <main className="fam-stack" aria-busy="true" />
  if (!room) {
    return (
      <main className="fam-stack">
        <p className="fam-error">가족방을 찾을 수 없어요</p>
        <Link className="fam-text-btn" to="/">
          가족 홈으로
        </Link>
      </main>
    )
  }

  const hon = room.elder_honorific
  const owner = room.is_owner
  const alive = invites.data ?? []
  const elderLinkAlive = alive.some((i) => i.kind === 'ELDER_DEVICE')
  const list = members.data ?? []
  const reloadAll = () => (rooms.reload(), reloadRooms()) // 이 화면 + 위 막대·가족 홈이 같은 숫자를 보게

  // 할머니 폰 카드 — 연결됨 / 사진 3장 전 / 링크 보낼 차례
  const dev = room.device_connected
    ? {
        on: true,
        title: '연결됐어요',
        sub: room.device_last_seen_at ? `마지막으로 연 때 · ${seenLabel(room.device_last_seen_at)}` : `${hon} 폰에서 하루한장이 열려요`,
      }
    : room.photo_count < 3
      ? { on: false, title: '아직 연결 전이에요', sub: `추억 사진을 3장 올리면 연결 링크를 만들 수 있어요 (지금 ${room.photo_count}장)` }
      : {
          on: false,
          title: '아직 연결 전이에요',
          sub: !owner
            ? '방장이 링크를 보내면 연결돼요'
            : elderLinkAlive
              ? `링크를 보냈어요 · ${hon} 폰에서 열면 연결돼요`
              : `${hon} 폰에 링크를 보내 주세요`,
        }

  return (
    <main className="fam-stack gr">
      <div className="gr-head">
        <h1>가족방</h1>
        <p>
          {room.elder_name} {hon}네
        </p>
      </div>

      <section className="fam-card">
        <h2 className="gr-h">{hon} 폰</h2>
        <div className="gr-dev">
          <span className={dev.on ? 'gr-dev-ic on' : 'gr-dev-ic'}>
            <FamIcon name="phone" />
          </span>
          <div>
            <b>{dev.title}</b>
            <small>{dev.sub}</small>
          </div>
          {owner && room.device_connected && (
            <button type="button" className="fam-text-btn gr-danger" onClick={() => open({ t: 'unlink' })}>
              연결 해제
            </button>
          )}
          {owner && !room.device_connected && room.photo_count >= 3 && (
            <button
              type="button"
              className="fam-btn fam-btn--primary fam-btn--sm"
              onClick={() => open({ t: 'invite', kind: 'ELDER_DEVICE' })}
            >
              링크 보내기
            </button>
          )}
        </div>
      </section>

      <section className="fam-card">
        <Link className="gr-row" to={`/groups/${roomId}/photos`}>
          <span>올린 사진</span>
          <b>{room.photo_count}장</b>
          <FamIcon name="chevRight" className="gr-chev" />
        </Link>
        <p className="gr-note">AI 가 사진을 보고 {hon}
          {wa(hon)} 나눌 이야기 거리를 찾아요 · 틀리면 고쳐 주세요</p>
      </section>

      <section className="fam-card">
        <div className="gr-h gr-h-row">
          <span>구성원 {members.data ? list.length : room.member_count}명</span>
          {owner && (
            <button
              type="button"
              className="fam-btn fam-btn--tonal fam-btn--sm"
              onClick={() => open({ t: 'invite', kind: 'FAMILY' })}
            >
              <FamIcon name="plus" />
              초대
            </button>
          )}
        </div>
        {members.error ? (
          <div className="gr-members">
            <p className="fam-error">{members.error.message}</p>
            <button type="button" className="fam-text-btn" onClick={members.reload}>
              다시 시도
            </button>
          </div>
        ) : (
          <div className="gr-members">
            {list.map((m) => (
              <div key={m.user_id} className="gr-member">
                <Avatar name={m.name} />
                <div>
                  <b>
                    {m.name}
                    {m.nickname ? ` · ${m.nickname}` : ''}
                  </b>
                  <small>
                    {RELATION[m.relation_tag]}
                    {m.is_owner ? ' · 방장' : ''}
                  </small>
                </div>
                {m.user_id === me?.user_id ? (
                  <i className="gr-me">나</i>
                ) : (
                  owner && (
                    <button
                      type="button"
                      className="fam-icon-btn gr-more"
                      onClick={() => open({ t: 'member', m })}
                      aria-label={`${m.name} 더 보기`}
                    >
                      ⋮
                    </button>
                  )
                )}
              </div>
            ))}
          </div>
        )}
        {alive.map((i) => (
          <div key={i.kind} className="gr-link">
            <span>
              {i.kind === 'FAMILY' ? '가족 초대 링크' : `${hon} 폰 링크`} · {timeLeft(i.expires_at)}
            </span>
            <button
              type="button"
              className="fam-text-btn gr-danger"
              disabled={busy}
              onClick={() =>
                change(`/api/rooms/${roomId}/invites/${i.kind}`, '링크를 폐기했어요 · 이제 열리지 않아요', () => {
                  invites.reload()
                  setMade((m) => ({ ...m, [i.kind]: undefined })) // 폐기한 주소는 판에서도 지운다
                })
              }
            >
              폐기
            </button>
          </div>
        ))}
        {!sheet && error && (
          <p className="fam-error" role="alert">
            {error}
          </p>
        )}
      </section>

      {sheet && (
        <>
          <button type="button" className="fam-scrim" aria-label="닫기" onClick={close} />
          <div className="fam-sheet" role="dialog" aria-label={sheetLabel(sheet, hon)}>
            <span className="fam-grab" />
            {sheet.t === 'invite' && (
              <>
                <h2>초대하기</h2>
                <div className="gr-chips">
                  {(['FAMILY', 'ELDER_DEVICE'] as const).map((k) => (
                    <button
                      key={k}
                      type="button"
                      className={sheet.kind === k ? 'gr-chip on' : 'gr-chip'}
                      onClick={() => open({ t: 'invite', kind: k })}
                    >
                      {k === 'FAMILY' ? '가족' : `${hon} 폰`}
                    </button>
                  ))}
                </div>
                <p className="gr-sheet-text">
                  {sheet.kind === 'FAMILY'
                    ? '가족이 링크를 열어 이름과 호칭을 정하고 들어와요 · 7일 동안 쓸 수 있어요'
                    : `${hon} 폰에서 한 번 열면 연결돼요 · 24시간 안에 한 번만 쓸 수 있어요`}
                </p>
                {sheet.kind === 'ELDER_DEVICE' && room.photo_count < 3 ? (
                  <>
                    <p className="gr-warn">
                      <FamIcon name="lock" />
                      추억 사진을 3장 올리면 만들 수 있어요 (지금 {room.photo_count}장)
                    </p>
                    <Link className="fam-text-btn gr-to-upload" to="/upload">
                      사진 올리기
                    </Link>
                  </>
                ) : (
                  alive.some((i) => i.kind === sheet.kind) && (
                    <p className="gr-sheet-text">새로 만들면 전에 보낸 링크는 더 쓸 수 없어요</p>
                  )
                )}
                {/* 기기 링크를 열면 그 폰이 새 기기가 되고 지금 폰은 끊긴다 (가족방당 1대, D38) */}
                {sheet.kind === 'ELDER_DEVICE' && room.device_connected && (
                  <p className="gr-warn">
                    이 링크를 열면 지금 연결된 {hon} 폰은 끊겨요. 폰을 바꿀 때만 보내 주세요
                  </p>
                )}
                {made[sheet.kind] && (
                  <p className="gr-url">
                    주소를 길게 눌러 복사해 보내 주세요 (화면을 나가면 다시 볼 수 없어요)
                    <br />
                    {made[sheet.kind]}
                  </p>
                )}
                <div className="gr-cta">
                  <button
                    type="button"
                    className="fam-btn fam-btn--primary fam-btn--block"
                    disabled={busy || (sheet.kind === 'ELDER_DEVICE' && room.photo_count < 3)}
                    onClick={() => makeLink(room, sheet.kind)}
                  >
                    {busy ? '만드는 중…' : made[sheet.kind] ? '새로 만들고 다시 보내기' : '링크 만들고 보내기'}
                  </button>
                </div>
              </>
            )}
            {sheet.t === 'member' && (
              <>
                <div className="gr-person">
                  <Avatar name={sheet.m.name} />
                  <div>
                    <b>
                      {sheet.m.name}
                      {sheet.m.nickname ? ` · ${sheet.m.nickname}` : ''}
                    </b>
                    <small>{RELATION[sheet.m.relation_tag]}</small>
                  </div>
                </div>
                <button type="button" className="fam-opt gr-opt-danger" onClick={() => open({ t: 'kick', m: sheet.m })}>
                  <span>
                    <b>가족방에서 내보내기</b>
                    <small>내보내면 되돌릴 수 없어요</small>
                  </span>
                </button>
              </>
            )}
            {sheet.t === 'kick' && (
              <>
                <h2>{sheet.m.name}님을 내보낼까요?</h2>
                <p className="gr-sheet-text">
                  {room.elder_name} {hon}네 일기와 알림을 더 볼 수 없고, 되돌릴 수 없어요.
                </p>
                <div className="gr-cta gr-cta-two">
                  <button type="button" className="fam-btn fam-btn--tonal" onClick={close}>
                    취소
                  </button>
                  <button
                    type="button"
                    className="fam-btn gr-btn-danger"
                    disabled={busy}
                    onClick={() =>
                      change(`/api/rooms/${roomId}/members/${sheet.m.user_id}`, `${sheet.m.name}님을 내보냈어요`, () => {
                        members.reload()
                        reloadAll()
                      })
                    }
                  >
                    내보내기
                  </button>
                </div>
              </>
            )}
            {sheet.t === 'unlink' && (
              <>
                <h2>{hon} 폰 연결을 해제할까요?</h2>
                <p className="gr-sheet-text">
                  해제하면 {hon} 폰에서 하루한장이 열리지 않아요. 다시 쓰려면 {hon} 폰 링크를 새로 보내 주세요.
                </p>
                <div className="gr-cta gr-cta-two">
                  <button type="button" className="fam-btn fam-btn--tonal" onClick={close}>
                    취소
                  </button>
                  <button
                    type="button"
                    className="fam-btn gr-btn-danger"
                    disabled={busy}
                    onClick={() => change(`/api/rooms/${roomId}/device`, '연결을 해제했어요', reloadAll)}
                  >
                    연결 해제
                  </button>
                </div>
              </>
            )}
            {error && (
              <p className="fam-error" role="alert">
                {error}
              </p>
            )}
          </div>
        </>
      )}

      {note && (
        <p className="gr-snack" role="status">
          {note}
        </p>
      )}
    </main>
  )
}

function sheetLabel(s: Sheet, hon: string) {
  if (s.t === 'invite') return '초대하기'
  if (s.t === 'member') return `${s.m.name} 더 보기`
  if (s.t === 'kick') return `${s.m.name}님 내보내기`
  return `${hon} 폰 연결 해제`
}
