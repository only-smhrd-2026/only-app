/**
 * ME_001 — 내 정보 (/me, 11/27 가족화면 설정 개선안: 가족방 탭의 '올린 사진' 칸 자리에서 온다).
 * 프로필 사진(올리기·바꾸기·지우기) · 이름 · 가족방마다 내 호칭(어르신이 부르는 말) · 비밀번호 바꾸기(카카오 가입은 없음)
 * · 알림 설정 · 로그아웃 · 회원 탈퇴. 서버: PATCH /api/auth/me · PUT·DELETE /api/auth/me/photo ·
 * PATCH /api/rooms/{id}/members/{나} · POST /api/auth/password.
 */
import { useState, type ChangeEvent, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { MemberOut, RoomOut, UserOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import { Avatar } from '../../components/FamilyFrame'
import PhotoCrop from '../../components/PhotoCrop'
import { useFetch } from '../../hooks/useFetch'
import { logout } from '../../lib/logout'
import './ACCOUNT_001.css' // 입력 칸(acc-input·acc-label)이 같은 모양
import './ME_001.css'

const NAME_MAX = 30 // 서버 NameIn 과 같은 값
const NICK_MAX = 12 // 서버 MemberUpdateIn 과 같은 값

type Run = (work: () => Promise<void>, done: string, fail: string) => Promise<void>

export default function ME_001() {
  const nav = useNavigate()
  const meFetch = useFetch<UserOut>('/api/auth/me')
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  const [edited, setMe] = useState<UserOut>() // 바꾼 뒤 서버가 돌려준 나 — 없으면 처음 받은 그대로
  const me = edited ?? meFetch.data ?? undefined
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string>() // 바꾼 뒤 한 줄 안내
  const [error, setError] = useState<string>()
  const [nameDraft, setName] = useState<string>()
  const [cropFile, setCropFile] = useState<File>() // 고른 사진 — 동그라미 자르기 판이 열려 있다
  const name = nameDraft ?? me?.name ?? ''

  /** 버튼 하나 = 요청 하나. 끝나면 안내 한 줄 */
  const run: Run = async (work, done, fail) => {
    setBusy(true)
    setNote(undefined)
    setError(undefined)
    try {
      await work()
      setNote(done)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : fail)
    } finally {
      setBusy(false)
    }
  }

  function pickPhoto(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // 같은 사진을 다시 골라도 onChange 가 오게
    if (file) setCropFile(file) // 동그라미로 맞춘 뒤 올린다 (PhotoCrop)
  }

  function uploadPhoto(jpeg: Blob) {
    setCropFile(undefined)
    const form = new FormData()
    form.append('file', jpeg, 'me.jpg')
    void run(
      async () => setMe(await api<UserOut>('/api/auth/me/photo', { method: 'PUT', form })),
      '프로필 사진을 바꿨어요',
      '사진을 올리지 못했어요. 다시 해 주세요.',
    )
  }

  function saveName(e: FormEvent) {
    e.preventDefault()
    void run(
      async () => setMe(await api<UserOut>('/api/auth/me', { method: 'PATCH', body: { name } })),
      '이름을 바꿨어요',
      '이름을 바꾸지 못했어요. 다시 해 주세요.',
    )
  }

  if (meFetch.error) return <p className="fam-error me-pad">{meFetch.error.message}</p>
  if (!me) return <p className="st-hint me-pad" aria-busy="true">불러오는 중…</p>

  return (
    <main className="me">
      <section className="fam-card me-card me-top">
        <span className="me-av">
          <Avatar name={me.name} src={me.profile_url} />
        </span>
        <div className="me-photo-btns">
          <label className="fam-btn fam-btn--tonal fam-btn--sm me-file">
            <input className="st-file" type="file" accept="image/jpeg,image/png" onChange={pickPhoto} disabled={busy} />
            <FamIcon name="imagePlus" />
            {me.profile_url ? '사진 바꾸기' : '사진 넣기'}
          </label>
          {me.profile_url && (
            <button
              type="button"
              className="fam-text-btn"
              disabled={busy}
              onClick={() =>
                void run(
                  async () => setMe(await api<UserOut>('/api/auth/me/photo', { method: 'DELETE' })),
                  '프로필 사진을 지웠어요',
                  '사진을 지우지 못했어요. 다시 해 주세요.',
                )
              }
            >
              사진 지우기
            </button>
          )}
        </div>
        {me.email && <p className="fam-mini">{me.email}</p>}
      </section>
      {cropFile && (
        <PhotoCrop file={cropFile} title="프로필 사진" onCancel={() => setCropFile(undefined)} onDone={uploadPhoto} />
      )}

      {(note || error) && (
        <p className={error ? 'fam-error' : 'me-note'} role={error ? 'alert' : 'status'}>
          {error ?? note}
        </p>
      )}

      <form className="fam-card me-card" onSubmit={saveName}>
        <label className="acc-label" htmlFor="me-name">이름</label>
        <div className="me-row">
          <input id="me-name" className="acc-input" value={name} maxLength={NAME_MAX} autoComplete="name" onChange={(e) => setName(e.target.value)} disabled={busy} />
          <button type="submit" className="fam-btn fam-btn--primary fam-btn--sm" disabled={busy || !name.trim() || name.trim() === me.name}>
            저장
          </button>
        </div>
      </form>

      {rooms.data?.map((r) => <Nickname key={r.room_id} room={r} me={me} busy={busy} run={run} />)}

      {me.login_type !== 'KAKAO' && <Password busy={busy} run={run} />}

      <section className="fam-card me-card me-links">
        <Link className="me-link" to="/notifications">
          알림 설정
          <FamIcon name="chevRight" />
        </Link>
        <button type="button" className="me-link" onClick={() => logout(nav)}>
          로그아웃
          <FamIcon name="chevRight" />
        </button>
        <Link className="me-link me-quiet" to="/account/withdraw">
          회원 탈퇴
          <FamIcon name="chevRight" />
        </Link>
      </section>
    </main>
  )
}

/** 가족방마다 내 호칭 — 어르신이 나를 부르는 말 (11/27: 방장이 아니어도 내 것은 내가 고친다). 비우면 이름으로 부른다 */
function Nickname({ room, me, busy, run }: { room: RoomOut; me: UserOut; busy: boolean; run: Run }) {
  const members = useFetch<MemberOut[]>(`/api/rooms/${room.room_id}/members`)
  const saved = members.data?.find((m) => m.user_id === me.user_id)?.nickname ?? ''
  const [nick, setNick] = useState<string>()
  const value = nick ?? saved
  const id = `me-nick-${room.room_id}`
  if (!members.data) return null
  return (
    <form
      className="fam-card me-card"
      onSubmit={(e) => {
        e.preventDefault()
        void run(
          async () => {
            await api<MemberOut>(`/api/rooms/${room.room_id}/members/${me.user_id}`, { method: 'PATCH', body: { nickname: value.trim() || null } })
            setNick(undefined)
            members.reload()
          },
          '호칭을 바꿨어요',
          '호칭을 바꾸지 못했어요. 다시 해 주세요.',
        )
      }}
    >
      <label className="acc-label" htmlFor={id}>
        {room.elder_name} {room.elder_honorific}께서 부르는 내 호칭
      </label>
      <div className="me-row">
        <input id={id} className="acc-input" value={value} maxLength={NICK_MAX} placeholder="예) 큰딸 · 비우면 이름으로 불러요" onChange={(e) => setNick(e.target.value)} disabled={busy} />
        <button type="submit" className="fam-btn fam-btn--primary fam-btn--sm" disabled={busy || value.trim() === saved}>
          저장
        </button>
      </div>
    </form>
  )
}

/** 비밀번호 바꾸기 — 지금 비밀번호 + 새 비밀번호(8~64자). 틀린 비밀번호·같은 비밀번호는 서버가 거절한다 */
function Password({ busy, run }: { busy: boolean; run: Run }) {
  const [cur, setCur] = useState('')
  const [next, setNext] = useState('')
  return (
    <form
      className="fam-card me-card"
      onSubmit={(e) => {
        e.preventDefault()
        void run(
          async () => {
            await api('/api/auth/password', { body: { current_password: cur, new_password: next } })
            setCur('')
            setNext('')
          },
          '비밀번호를 바꿨어요',
          '비밀번호를 바꾸지 못했어요. 다시 해 주세요.',
        )
      }}
    >
      <h2 className="acc-label">비밀번호 바꾸기</h2>
      <input className="acc-input" type="password" placeholder="지금 비밀번호" aria-label="지금 비밀번호" value={cur} maxLength={64} autoComplete="current-password" onChange={(e) => setCur(e.target.value)} disabled={busy} required />
      <input className="acc-input" type="password" placeholder="새 비밀번호 (8자 이상)" aria-label="새 비밀번호" value={next} minLength={8} maxLength={64} autoComplete="new-password" onChange={(e) => setNext(e.target.value)} disabled={busy} required />
      <button type="submit" className="fam-btn fam-btn--primary" disabled={busy || !cur || next.length < 8}>
        비밀번호 바꾸기
      </button>
    </form>
  )
}
