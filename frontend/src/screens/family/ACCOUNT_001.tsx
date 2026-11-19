/**
 * ACCOUNT_001 — 회원 탈퇴 (/account/withdraw). 처리방침(POLICY_001) '지우는 방법'에서 온다.
 * 무엇이 지워지고 남는지 → 내가 방장인 가족방마다 '방장을 넘길 분' 고르기(다른 가족이 있을 때) 또는 '모두 지워져요'(혼자일 때)
 * → 지금 비밀번호 → [탈퇴하기] → 확인 판 한 번 더 → 시작 화면.
 * 서버는 화면이 보여 준 그대로만 한다(backend/app/routers/account.py) — 그사이 구성원이 바뀌었으면 거절하고,
 * 화면은 가족방을 다시 읽어 바뀐 모습으로 다시 고르게 한다.
 */
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { MemberOut, RoomOut, UserOut, WithdrawIn } from '../../api/types'
import { Avatar } from '../../components/FamilyFrame'
import { useFetch } from '../../hooks/useFetch'
import { clearFamilyDiaryDraft } from '../../lib/familyDiaryDraft'
import { clearUploadDraft } from '../../lib/uploadDraft'
import './ACCOUNT_001.css'

// 서버가 본 가족방 구성원이 화면과 다를 때의 오류 코드
const ROOM_CHANGED = ['OWNER_TRANSFER_REQUIRED', 'ROOM_DELETE_CONFIRM_REQUIRED']

export default function ACCOUNT_001() {
  const nav = useNavigate()
  const me = useFetch<UserOut>('/api/auth/me')
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  // 내가 방장인 가족방의 구성원 (room_id → 목록). 가족방 목록을 다시 읽으면 같이 다시 읽는다
  const [members, setMembers] = useState<Record<number, MemberOut[]>>()
  const [membersError, setMembersError] = useState<ApiError>()
  const [picked, setPicked] = useState<Record<number, number>>({}) // room_id → 방장을 넘길 가족
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const sheet = useRef<HTMLDialogElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)

  const list = rooms.data
  useEffect(() => {
    if (!list) return
    let alive = true
    const owned = list.filter((r) => r.is_owner)
    Promise.all(owned.map((r) => api<MemberOut[]>(`/api/rooms/${r.room_id}/members`)))
      .then((lists) => {
        if (!alive) return
        setMembers(Object.fromEntries(owned.map((r, i) => [r.room_id, lists[i]])))
        setMembersError(undefined)
      })
      .catch((e) => alive && setMembersError(e as ApiError))
    return () => {
      alive = false
    }
  }, [list])

  // 확인 판은 <dialog> (HOME_002 일기 지우기와 같은 방법) — 뒤 화면이 눌리지 않고, 처음 초점은 [취소]
  useEffect(() => {
    if (confirm) {
      sheet.current?.showModal()
      cancel.current?.focus()
    } else {
      sheet.current?.close()
    }
  }, [confirm])

  if (me.error?.status === 401 || rooms.error?.status === 401) return <Navigate to="/login" replace />
  const failed = me.error ?? rooms.error ?? membersError
  if (failed) {
    return (
      <main className="fam-stack acc">
        <p className="fam-error" role="alert">{failed.message}</p>
        <button type="button" className="fam-btn fam-btn--tonal acc-retry" onClick={() => { me.reload(); rooms.reload() }}>
          다시 시도
        </button>
      </main>
    )
  }
  if (!me.data || !list || !members) {
    return (
      <main className="fam-stack acc" aria-busy="true">
        <p className="acc-note" role="status">불러오는 중…</p>
      </main>
    )
  }

  const myId = me.data.user_id
  // 방장인 가족방마다 할 일 — to: 넘길 가족 번호 | null(혼자라 가족방을 지움) | undefined(아직 못 정함)
  const plans = list.filter((r) => r.is_owner).map((room) => {
    const others = members[room.room_id]?.filter((m) => m.user_id !== myId)
    const pick = others?.find((m) => m.user_id === picked[room.room_id])?.user_id // 그사이 나간 분은 고른 것에서 뺀다
    return { room, others, to: !others ? undefined : others.length ? pick : null }
  })
  const deleting = plans.filter((p) => p.to === null).map((p) => `${p.room.elder_name} ${p.room.elder_honorific}네`)
  const undecided = plans.some((p) => p.to === undefined) // 가족방 구성원을 아직 읽는 중이거나, 고른 분이 그사이 나감

  // 빈 칸(넘길 분·비밀번호)은 브라우저가 알려 준다(required) — 여기까지 오면 다 채운 것
  function ask(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (undecided) return
    setError(undefined)
    setConfirm(true)
  }

  async function withdraw() {
    if (busy) return
    // 판을 연 뒤에 가족방이 바뀌었으면 보내지 않는다 — 아래 `?? null` 이 '이 가족방을 지워요'로 가면 안 된다
    if (undecided) return setConfirm(false)
    setBusy(true)
    const body: WithdrawIn = {
      password,
      transfers: plans.map((p) => ({ room_id: p.room.room_id, new_owner_user_id: p.to ?? null })),
    }
    try {
      await api('/api/auth/withdraw', { body })
    } catch (e) {
      // 401 = 이미 탈퇴했거나(응답을 못 받고 다시 누름) 로그인이 끝남 → 시작 화면으로
      if (!(e instanceof ApiError && e.status === 401)) {
        setError(e instanceof ApiError ? e.message : '탈퇴하지 못했어요. 다시 해 주세요')
        setConfirm(false)
        setBusy(false)
        if (e instanceof ApiError && ROOM_CHANGED.includes(e.code)) rooms.reload()
        return
      }
    }
    clearUploadDraft() // 고르다 만 사진·쓰다 만 일기를 이 폰에 남기지 않는다 (로그아웃과 같게)
    clearFamilyDiaryDraft()
    nav('/login', { replace: true })
  }

  return (
    <main className="fam-stack acc">
      <header className="acc-head">
        <h1>회원 탈퇴</h1>
      </header>

      <section className="fam-card acc-card">
        <h2>탈퇴하면</h2>
        <ul className="acc-list">
          <li>이메일·이름·비밀번호는 바로 지워지고, 되돌릴 수 없어요.</li>
          <li>
            내가 쓴 일기와 올린 사진은 가족방에 '탈퇴한 가족' 이름으로 남아요. 지우려면 탈퇴하기 전에 직접 지워
            주세요.
          </li>
          <li>
            내가 방장인 가족방은 다른 가족에게 방장을 넘겨요. 다른 가족이 없는 가족방은 어르신 일기·대화·사진까지
            모두 지워져요.
          </li>
          <li>같은 이메일로 다시 가입하면 새 계정이에요.</li>
        </ul>
      </section>

      <form className="acc-form" onSubmit={ask}>
        {plans.map(({ room, others }) => (
          <section className="fam-card acc-card" key={room.room_id}>
            <h2>
              {room.elder_name} {room.elder_honorific}네 가족방
            </h2>
            {!others ? (
              <p className="acc-note" role="status">불러오는 중…</p>
            ) : others.length ? (
              <fieldset className="acc-pick" disabled={busy}>
                <legend>방장을 넘길 분을 골라 주세요</legend>
                {others.map((m) => (
                  <label className="fam-opt acc-opt" key={m.user_id}>
                    <input
                      type="radio"
                      name={`acc-owner-${room.room_id}`}
                      checked={picked[room.room_id] === m.user_id}
                      onChange={() => setPicked((p) => ({ ...p, [room.room_id]: m.user_id }))}
                      required
                    />
                    <Avatar name={m.name} />
                    <span>
                      <b>{m.name}</b>
                      {m.nickname && <small>{m.nickname}</small>}
                    </span>
                  </label>
                ))}
              </fieldset>
            ) : (
              <p className="acc-warn">
                다른 가족이 없어요. 탈퇴하면 이 가족방과 {room.elder_name} {room.elder_honorific}의 일기·대화·사진이
                모두 지워지고, {room.elder_honorific} 폰 연결도 끊겨요.
              </p>
            )}
          </section>
        ))}

        <section className="fam-card acc-card">
          <label className="acc-label" htmlFor="acc-password">지금 비밀번호</label>
          <input
            id="acc-password"
            className="acc-input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            maxLength={64}
            autoComplete="current-password"
            disabled={busy}
            required
          />
          {error && <p className="fam-error" role="alert">{error}</p>}
          <button className="fam-btn fam-btn--block acc-danger" disabled={busy}>
            탈퇴하기
          </button>
        </section>
      </form>

      <dialog
        ref={sheet}
        className="fam-sheet acc-sheet"
        aria-labelledby="acc-confirm-title"
        aria-describedby="acc-confirm-text"
        aria-busy={busy}
        onCancel={(e) => { e.preventDefault(); if (!busy) setConfirm(false) }}
      >
        <span className="fam-grab" />
        <h2 id="acc-confirm-title">정말 탈퇴할까요?</h2>
        <p id="acc-confirm-text">
          되돌릴 수 없어요.
          {deleting.length > 0 && ` ${deleting.join(', ')} 가족방과 어르신 기록도 모두 지워져요.`}
        </p>
        <div className="acc-two">
          <button ref={cancel} type="button" className="fam-btn fam-btn--tonal" disabled={busy} onClick={() => setConfirm(false)}>
            취소
          </button>
          <button type="button" className="fam-btn acc-danger" disabled={busy} onClick={withdraw}>
            {busy ? '탈퇴하는 중…' : '탈퇴하기'}
          </button>
        </div>
      </dialog>
    </main>
  )
}
