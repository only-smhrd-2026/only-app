/**
 * UPLOAD_002 — 추억 올리기 2/3: 보낼 분·사진 속 사람·한마디 (FR-ME-002, D17, 목업 설계자료/목업_1115_가족 ④ '추억 올리기 2/3').
 * UPLOAD_001 이 uploadDraft 에 넣은 사진·요청 번호를 고른 가족방마다 보낸다 → UPLOAD_003 결과. 하위 화면(위 ←).
 * 한마디·사진 속 사람은 묶음에 한 번 — 그 묶음의 모든 사진에 같은 값. 단, 사진 속 사람은 가족방마다
 * 그 방 호칭으로 바꿔 보낸다(할머니가 부르는 말로 AI 가 물어보게).
 * 진행 막대·아래 버튼은 steps.css, 칩·입력 칸은 FDIARY_002.css 를 같이 쓴다.
 */
import { useEffect, useRef, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { MemberOut, PhotoBatchOut, RoomOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import { useFetch } from '../../hooks/useFetch'
import { clearUploadDraft, PHOTO_PROBLEMS, uploadDraft, uploadResult, type UploadRoomResult } from '../../lib/uploadDraft'
import { Thumb } from './UPLOAD_001'
import './steps.css'
import './FDIARY_002.css'
import './UPLOAD_002.css'

// 서버 config.py 의 UPLOAD_MAX_NOTE_CHARS 와 같게 (한마디·사진 속 사람 글자 수)
const MAX_NOTE = 100

const nameOf = (r: RoomOut) => `${r.elder_name} ${r.elder_honorific}`

export default function UPLOAD_002() {
  const nav = useNavigate()
  // 열 때 한 번만 복사 — 전부 성공해서 uploadDraft 를 비워도 이 화면의 사진·결과는 그대로 남게
  const [draft] = useState(() => ({ ...uploadDraft }))
  const rooms = useFetch<RoomOut[]>(draft.files.length > 0 ? '/api/rooms' : null)
  // 같은 묶음의 앞선 결과가 있으면 결과 화면 UPLOAD_003 의 [실패한 곳 다시 보내기]로 온 것
  const [before] = useState(() => (uploadResult.batchId === draft.batchId ? uploadResult.rooms : []))
  const retry = before.length > 0
  const done = new Set(before.filter((r) => r.ok).map((r) => r.room_id)) // 이미 보낸 곳 — 잠그고 '보냄'
  const failedBefore = new Set(before.filter((r) => !r.ok).map((r) => r.room_id))
  // 처음 고름: 다시 보내기면 실패한 곳만, 아니면 전부(내가 속한 가족방 전부).
  // 사용자가 눌러 처음과 달라진 가족방만 적어 두면 목록이 늦게 와도 따로 채울 필요가 없다
  const [flipped, setFlipped] = useState<Set<number>>(() => new Set())
  const isChecked = (roomId: number) =>
    !done.has(roomId) && (!retry || failedBefore.has(roomId)) !== flipped.has(roomId)
  const [results, setResults] = useState<Record<number, UploadRoomResult>>({})
  const [busy, setBusy] = useState(false)
  const [caption, setCaption] = useState(draft.caption)
  const [peopleNote, setPeopleNote] = useState(draft.peopleNote)
  const [peopleIds, setPeopleIds] = useState<number[]>(draft.peopleIds)
  const [custom, setCustom] = useState(!!draft.peopleNote) // '직접 쓰기' 칸을 열었는지
  // 가족방마다 구성원(호칭). 못 읽은 방은 null — 그 방에는 이름으로 보낸다
  const [members, setMembers] = useState<Record<number, MemberOut[] | null>>({})
  // 화면을 떠나면(뒤로 가기 등) 올리던 요청을 멈춘다. 안 멈추면 남은 가족방에 계속 올라가고,
  // 그 사이 사진을 다시 골라 보내면 요청 번호가 달라 같은 사진이 두 번 저장된다
  const leaving = useRef<AbortController | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    leaving.current = controller
    return () => controller.abort()
  }, [])

  // 보내는 동안만 화면이 안 꺼지게 — 꺼지면 보내기가 멈출 수 있다. 끝나거나(busy=false) 화면을 떠나면 놓는다.
  // 다른 앱에 갔다 오면 브라우저가 잠금을 풀어서, 다시 보일 때 또 잡는다(VoiceSession 과 같은 방법).
  // 지원 안 하는 폰·거절은 조용히 넘어간다
  useEffect(() => {
    if (!busy) return
    let lock: WakeLockSentinel | undefined
    let over = false
    // 요청했는데 아직 답이 안 옴 — 이때 또 요청하면(다른 앱 갔다 바로 오기) 잠금이 둘 생기고 하나는 안 풀린다
    let asking = false
    // 요청 중이라 건너뛴 적이 있음 — 그 요청이 숨은 사이 거절·풀릴 수 있어서, 답이 오면 한 번만 다시 잡는다
    // (늘 다시 잡으면 계속 거절하는 폰에서 요청이 끝없이 되풀이된다)
    let missed = false
    const grab = () => {
      if (document.hidden || (lock && !lock.released) || !navigator.wakeLock) return
      if (asking) {
        missed = true
        return
      }
      asking = true
      navigator.wakeLock
        .request('screen')
        .then(
          (l) => {
            if (over) l.release().catch(() => {})
            else lock = l
          },
          () => {},
        )
        .finally(() => {
          asking = false // 답이 오거나 실패하면 내려놓기
          if (missed && !over) {
            missed = false
            grab()
          }
        })
    }
    grab()
    document.addEventListener('visibilitychange', grab)
    return () => {
      over = true
      document.removeEventListener('visibilitychange', grab)
      lock?.release().catch(() => {})
    }
  }, [busy])

  const roomIds = rooms.data?.map((r) => r.room_id).join(',') ?? ''
  useEffect(() => {
    if (!roomIds) return
    const stop = new AbortController() // 화면을 떠나면 받던 구성원 목록을 버린다
    for (const id of roomIds.split(',').map(Number)) {
      api<MemberOut[]>(`/api/rooms/${id}/members`, { signal: stop.signal })
        .then((list) => setMembers((m) => ({ ...m, [id]: list })))
        .catch(() => !stop.signal.aborted && setMembers((m) => ({ ...m, [id]: null })))
    }
    return () => stop.abort()
  }, [roomIds])

  // 고친 글·고른 사람을 uploadDraft 에도 적는다 — draft 는 열 때 만든 복사본이라, 뒤로 갔다 와도 남게
  useEffect(() => {
    uploadDraft.caption = caption
    uploadDraft.peopleNote = peopleNote
    uploadDraft.peopleIds = peopleIds
  }, [caption, peopleNote, peopleIds])

  if (draft.files.length === 0) return <Navigate to="/upload" replace /> // 새로고침 등으로 고른 사진이 없음
  if (rooms.error?.status === 401) return <Navigate to="/login" replace />
  if (rooms.error) {
    // 새로고침하면 고른 사진이 사라진다 — 그 자리에서 다시 읽게 한다
    return (
      <main className="st">
        <div className="st-body">
          <p className="fam-error up2-pad">{rooms.error.message}</p>
          <button type="button" className="fam-btn fam-btn--tonal up2-pad" onClick={rooms.reload}>
            다시 시도
          </button>
        </div>
      </main>
    )
  }
  if (!rooms.data) {
    return (
      <main className="st" aria-busy="true">
        <div className="st-body">
          <p className="up2-pad up2-res">불러오는 중…</p>
        </div>
      </main>
    )
  }
  if (rooms.data.length === 0) {
    return (
      <main className="st">
        <div className="st-body">
          <p className="up2-pad">
            먼저 가족방을 만들어 주세요 · <Link to="/groups/new">가족방 만들기</Link>
          </p>
        </div>
      </main>
    )
  }

  const list = rooms.data
  const checked = list.filter((r) => isChecked(r.room_id))
  const sent = Object.keys(results).length > 0
  const locked = busy || retry // 보내는 중·한 번 보낸 묶음(다시 보내기)은 글을 못 고친다 (아래 form 주석)

  // 사람 칩 — 내 가족방 구성원을 한 번씩(user_id), 가족방 목록 순서
  const people = new Map<number, string>()
  for (const r of list) for (const m of members[r.room_id] ?? []) if (!people.has(m.user_id)) people.set(m.user_id, m.name)
  const membersReady = list.every((r) => r.room_id in members)

  /** 이 가족방에 보낼 '사진 속 사람' 한 줄 — 고른 사람은 그 방 호칭(없으면 이름), 끝에 직접 쓴 글.
   *  그 방 구성원이 아닌 사람(구성원 목록을 못 읽은 방 포함)은 뺀다 — 다른 가족방 사람의 이름이 이 방에 가지 않게 */
  function noteFor(roomId: number) {
    const parts = peopleIds.map((id) => {
      const m = members[roomId]?.find((x) => x.user_id === id)
      return m ? m.nickname || m.name : ''
    })
    if (peopleNote.trim()) parts.push(peopleNote.trim())
    return parts.filter(Boolean).join(', ')
  }
  const tooLong = checked.filter((r) => noteFor(r.room_id).length > MAX_NOTE)

  function toggleRoom(roomId: number) {
    setFlipped((s) => {
      const next = new Set(s)
      if (next.has(roomId)) next.delete(roomId)
      else next.add(roomId)
      return next
    })
  }

  function togglePerson(id: number) {
    setPeopleIds(peopleIds.includes(id) ? peopleIds.filter((x) => x !== id) : [...peopleIds, id])
  }

  async function send(targets: RoomOut[]) {
    const signal = leaving.current?.signal
    setBusy(true)
    const next: Record<number, UploadRoomResult> = {}
    // 차례로 보낸다(동시에 말고) — 서버가 사진 변환을 한 번에 한 요청씩 하므로
    for (const room of targets) {
      const form = new FormData()
      draft.files.forEach((f) => form.append('files', f))
      // 가족방마다 같은 번호여도 된다 — 서버는 '같은 가족방 + 같은 번호'만 같은 요청으로 본다 (D17)
      form.append('upload_batch_id', draft.batchId)
      // 적은 글만 보낸다 — 빈 칸은 칸 자체를 보내지 않음. 사진 속 사람은 이 방 호칭으로
      if (caption.trim()) form.append('caption', caption.trim())
      const note = noteFor(room.room_id)
      if (note) form.append('people_note', note)
      const name = nameOf(room)
      try {
        const r = await api<PhotoBatchOut>(`/api/rooms/${room.room_id}/photos`, { form, signal })
        next[room.room_id] = { room_id: room.room_id, name, ok: true, text: `${name}께 ${r.photos.length}장 보냈어요`, why: '', photos: r.photos }
      } catch (e) {
        // 화면을 떠났다 — 남은 가족방에는 보내지 않는다. 고른 사진(uploadDraft)은 그대로 둔다
        if (signal?.aborted) return
        // 고르는 사이 로그인이 풀림 — 다시 눌러도 계속 실패하니 로그인 화면으로
        if (e instanceof ApiError && e.status === 401) return nav('/login', { replace: true })
        const why = e instanceof ApiError ? e.message : '연결이 잠깐 끊겼어요. 다시 해 주세요.'
        next[room.room_id] = { room_id: room.room_id, name, ok: false, text: `${name}: ${why}`, why, photos: [] }
        // 사진 자체가 문제면 남은 가족방에 같은 사진을 또 올리지 않는다(같은 답을 받으려고 수십 MB 를 다시 보냄).
        // 아직 못 보낸 방에도 같은 이유를 적어 두고 멈춘다
        if (e instanceof ApiError && PHOTO_PROBLEMS.includes(e.code)) {
          for (const rest of targets) {
            if (next[rest.room_id]?.ok) continue
            const restName = nameOf(rest)
            next[rest.room_id] = { room_id: rest.room_id, name: restName, ok: false, text: `${restName}: ${why}`, why, photos: [] }
          }
          setResults({ ...next })
          break
        }
      }
      setResults({ ...next }) // 한 곳씩 끝날 때마다 보여 준다
    }
    setBusy(false)
    // (가) 이번에 보낸 곳이 전부 성공하면 다음 사진 올리기를 위해 비운다. 실패가 남으면 그대로 — 다시 보내기도 같은 사진·같은 번호.
    // 그 사이 사진을 새로 골랐으면(번호가 다름) 건드리지 않는다. (나)보다 먼저 — 비울 때 결과도 같이 지워지므로
    if (Object.values(next).every((x) => x.ok) && uploadDraft.batchId === draft.batchId) clearUploadDraft()
    // (나) 결과 화면에 넘긴다: 앞서 이미 성공한 곳 + 이번에 보낸 곳, 가족방 목록 순서로
    const earlier = Object.fromEntries(before.filter((r) => r.ok).map((r) => [r.room_id, r]))
    Object.assign(uploadResult, {
      batchId: draft.batchId,
      rooms: list.flatMap((room) => next[room.room_id] ?? earlier[room.room_id] ?? []),
    })
    // (다) 결과 화면으로. replace — 뒤로 가기로 이 화면에 돌아와 같은 묶음을 또 보내지 않게
    nav('/upload/result', { replace: true })
  }

  return (
    <main className="st">
      <div className="st-prog" aria-hidden="true">
        <i style={{ width: '66.6%' }} />
      </div>
      <div className="st-body">
        <div className="st-head">
          <p className="st-step">2/3 · 보낼 분</p>
          <h1>어느 분께 보낼까요?</h1>
          {retry && <p className="st-lead">못 보낸 곳에 같은 사진·같은 글로 다시 보내요</p>}
        </div>

        <div className="up2-thumbs">
          {draft.files.slice(0, 4).map((f, i) => (
            <span key={i} className="up2-tb">
              <Thumb file={f} alt={`고른 사진 ${i + 1}`} />
            </span>
          ))}
          <small>사진 {draft.files.length}장</small>
        </div>

        {/*
          보내는 중·한 번 보낸 묶음(다시 보내기)은 글을 못 고친다. 서버는 같은 번호(upload_batch_id)의
          두 번째 요청에 처음 저장본을 그대로 돌려줘서, 글을 고쳐 다시 보내도 바뀌지 않는다 (D17)
        */}
        <section className="fam-card fd2-form">
          <div className="fd2-field" role="group" aria-labelledby="up2-to">
            <span className="fd2-label" id="up2-to">
              보낼 분
            </span>
            <div className="fd2-moods">
              {list.map((room) => {
                const on = isChecked(room.room_id)
                return (
                  <button
                    key={room.room_id}
                    type="button"
                    className={on ? 'fd2-mood on' : 'fd2-mood'}
                    aria-pressed={on}
                    disabled={busy || done.has(room.room_id)}
                    onClick={() => toggleRoom(room.room_id)}
                  >
                    {done.has(room.room_id) && <FamIcon name="check" />}
                    {nameOf(room)}
                    {done.has(room.room_id) && ' · 보냄'}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="fd2-field" role="group" aria-labelledby="up2-people">
            <span className="fd2-label" id="up2-people">
              사진 속 사람 <small className="up2-opt">선택</small>
            </span>
            <div className="fd2-moods">
              {[...people].map(([id, name]) => (
                <button
                  key={id}
                  type="button"
                  className={peopleIds.includes(id) ? 'fd2-mood on' : 'fd2-mood'}
                  aria-pressed={peopleIds.includes(id)}
                  disabled={locked}
                  onClick={() => togglePerson(id)}
                >
                  {name}
                </button>
              ))}
              {!custom && (
                <button type="button" className="fd2-mood" disabled={locked} onClick={() => setCustom(true)}>
                  <FamIcon name="plus" />
                  직접 쓰기
                </button>
              )}
            </div>
            {!membersReady && people.size === 0 && <small className="up2-opt">구성원을 불러오는 중…</small>}
            {custom && (
              <input
                className="fd2-input"
                value={peopleNote}
                maxLength={MAX_NOTE}
                placeholder="예: 할머니, 이웃 영자 씨"
                aria-label="사진 속 사람 직접 쓰기"
                autoFocus={!draft.peopleNote}
                disabled={locked}
                onChange={(e) => setPeopleNote(e.target.value)}
              />
            )}
            {tooLong.length > 0 && (
              <p className="fam-error" role="alert">
                사진 속 사람은 {MAX_NOTE}자까지예요 ({tooLong.map(nameOf).join(', ')}께 보낼 글이 길어요). 몇 분 빼 주세요
              </p>
            )}
          </div>

          <div className="fd2-field">
            <label className="fd2-label" htmlFor="up2-caption">
              한마디 <small className="up2-opt">선택</small>
            </label>
            <textarea
              id="up2-caption"
              className="fd2-input"
              rows={2}
              value={caption}
              maxLength={MAX_NOTE}
              placeholder="예: 2019년 설날 큰집에서"
              disabled={locked}
              onChange={(e) => setCaption(e.target.value)}
            />
            <span className="fd2-count">
              {caption.length}/{MAX_NOTE}
            </span>
          </div>

          <p className="up2-note-ai">
            <FamIcon name="sparkle" />
            <span>AI가 사진을 보고 이야기 거리를 찾아요. 사실로 단정해 말하지는 않아요</span>
          </p>
        </section>

        {list.map((room) => {
          const r = results[room.room_id]
          return (
            r && (
              <p key={room.room_id} className={r.ok ? 'up2-pad up2-res' : 'fam-error up2-pad'}>
                {r.text}
              </p>
            )
          )
        })}
      </div>

      <div className="st-cta">
        {/* 사람을 골랐으면 구성원(호칭)을 다 읽은 뒤에 — 덜 읽은 방에 호칭 대신 이름이 가지 않게 */}
        <button
          type="button"
          className="fam-btn fam-btn--primary"
          disabled={busy || sent || checked.length === 0 || tooLong.length > 0 || (peopleIds.length > 0 && !membersReady)}
          onClick={() => send(checked)}
        >
          {busy ? '올리는 중…' : `${retry ? '다시 보내기' : '올리기'} · ${draft.files.length}장`}
        </button>
      </div>
    </main>
  )
}
