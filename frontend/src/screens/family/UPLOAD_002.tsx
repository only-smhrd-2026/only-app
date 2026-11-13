/**
 * UPLOAD_002 — 사진 올리기 2/2: 보낼 가족방 고르기·보내기 (FR-ME-002 중 받는 가족방 고르기, D17).
 * UPLOAD_001 이 uploadDraft 에 넣은 사진·요청 번호를 체크한 가족방마다 보낸다.
 * 한마디·사진 속 사람은 묶음에 한 번 — 그 묶음의 모든 사진에 같은 값(FR-ME-002).
 * → UPLOAD_003 결과. 모양은 11/12 목업 가족 화면 값(.fam-skin, UPLOAD_001.css).
 */
import { useEffect, useRef, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { PhotoBatchOut, RoomOut } from '../../api/types'
import { useFetch } from '../../hooks/useFetch'
import { clearUploadDraft, uploadDraft, uploadResult, type UploadRoomResult } from '../../lib/uploadDraft'
import { PhotoGrid } from './UPLOAD_001'
import './UPLOAD_002.css'

// 사진 자체가 문제일 때 서버가 주는 코드 (routers/photos.py) — 어느 가족방에 보내도 같은 답이다
const PHOTO_PROBLEMS = ['BAD_IMAGE', 'IMAGE_TOO_LARGE', 'PHOTO_TOO_BIG', 'TOO_MANY_PHOTOS']
// 서버 config.py 의 UPLOAD_MAX_NOTE_CHARS 와 같게 (한마디·사진 속 사람 글자 수)
const MAX_NOTE = 100

export default function UPLOAD_002() {
  const nav = useNavigate()
  // 열 때 한 번만 복사 — 전부 성공해서 uploadDraft 를 비워도 이 화면의 사진·결과는 그대로 남게
  const [draft] = useState(() => ({ ...uploadDraft }))
  const rooms = useFetch<RoomOut[]>(draft.files.length > 0 ? '/api/rooms' : null)
  // 같은 묶음의 앞선 결과가 있으면 결과 화면 UPLOAD_003 의 [실패한 곳 다시 보내기]로 온 것
  const [before] = useState(() => (uploadResult.batchId === draft.batchId ? uploadResult.rooms : []))
  const retry = before.length > 0
  const done = new Set(before.filter((r) => r.ok).map((r) => r.room_id)) // 이미 보낸 곳 — 잠그고 '(보냄)'
  const failedBefore = new Set(before.filter((r) => !r.ok).map((r) => r.room_id))
  // 처음 체크: 다시 보내기면 실패한 곳만, 아니면 전부(내가 속한 가족방 전부).
  // 사용자가 눌러 처음과 달라진 가족방만 적어 두면 목록이 늦게 와도 따로 채울 필요가 없다
  const [flipped, setFlipped] = useState<Set<number>>(() => new Set())
  const isChecked = (roomId: number) =>
    !done.has(roomId) && (!retry || failedBefore.has(roomId)) !== flipped.has(roomId)
  const [results, setResults] = useState<Record<number, UploadRoomResult>>({})
  const [busy, setBusy] = useState(false)
  const [caption, setCaption] = useState(draft.caption)
  const [peopleNote, setPeopleNote] = useState(draft.peopleNote)
  // 화면을 떠나면(뒤로 가기 등) 올리던 요청을 멈춘다. 안 멈추면 남은 가족방에 계속 올라가고,
  // 그 사이 사진을 다시 골라 보내면 요청 번호가 달라 같은 사진이 두 번 저장된다
  const leaving = useRef<AbortController | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    leaving.current = controller
    return () => controller.abort()
  }, [])

  if (draft.files.length === 0) return <Navigate to="/upload" replace /> // 새로고침 등으로 고른 사진이 없음
  if (rooms.error?.status === 401) return <Navigate to="/login" replace />
  if (rooms.error) {
    // 새로고침하면 고른 사진이 사라진다 — 그 자리에서 다시 읽게 한다
    return (
      <main className="page fam-skin">
        <p className="error">{rooms.error.message}</p>
        <button className="btn" onClick={rooms.reload}>다시 시도</button>
      </main>
    )
  }
  if (!rooms.data) return <main className="page fam-skin"><p className="muted">불러오는 중…</p></main>
  if (rooms.data.length === 0) {
    return (
      <main className="page fam-skin">
        <h1>올릴 가족방 고르기</h1>
        <p>먼저 가족방을 만들어 주세요</p>
        <Link className="btn" to="/groups/new">가족방 만들기</Link>
      </main>
    )
  }

  const list = rooms.data
  const checked = list.filter((r) => isChecked(r.room_id))
  const sent = Object.keys(results).length > 0

  function toggle(roomId: number) {
    setFlipped((s) => {
      const next = new Set(s)
      if (next.has(roomId)) next.delete(roomId)
      else next.add(roomId)
      return next
    })
  }

  async function send(targets: RoomOut[]) {
    const signal = leaving.current?.signal
    setBusy(true)
    const form = new FormData()
    draft.files.forEach((f) => form.append('files', f))
    // 가족방마다 같은 번호여도 된다 — 서버는 '같은 가족방 + 같은 번호'만 같은 요청으로 본다 (D17)
    form.append('upload_batch_id', draft.batchId)
    // 적은 글만 보낸다 — 빈 칸은 칸 자체를 보내지 않음
    if (caption.trim()) form.append('caption', caption.trim())
    if (peopleNote.trim()) form.append('people_note', peopleNote.trim())
    const next: Record<number, UploadRoomResult> = {}
    // 차례로 보낸다(동시에 말고) — 서버가 사진 변환을 한 번에 한 요청씩 하므로
    for (const room of targets) {
      const name = `${room.elder_name} ${room.elder_honorific}`
      try {
        const r = await api<PhotoBatchOut>(`/api/rooms/${room.room_id}/photos`, { form, signal })
        next[room.room_id] = { room_id: room.room_id, name, ok: true, text: `${name}께 ${r.photos.length}장 보냈어요`, photos: r.photos }
      } catch (e) {
        // 화면을 떠났다 — 남은 가족방에는 보내지 않는다. 고른 사진(uploadDraft)은 그대로 둔다
        if (signal?.aborted) return
        // 고르는 사이 로그인이 풀림 — 다시 눌러도 계속 실패하니 로그인 화면으로
        if (e instanceof ApiError && e.status === 401) return nav('/login', { replace: true })
        const why = e instanceof ApiError ? e.message : '연결이 잠깐 끊겼어요. 다시 해 주세요.'
        next[room.room_id] = { room_id: room.room_id, name, ok: false, text: `${name}: ${why}`, photos: [] }
        // 사진 자체가 문제면 남은 가족방에 같은 사진을 또 올리지 않는다(같은 답을 받으려고 수십 MB 를 다시 보냄).
        // 아직 못 보낸 방에도 같은 이유를 적어 두고 멈춘다
        if (e instanceof ApiError && PHOTO_PROBLEMS.includes(e.code)) {
          for (const rest of targets) {
            if (next[rest.room_id]?.ok) continue
            const restName = `${rest.elder_name} ${rest.elder_honorific}`
            next[rest.room_id] = { room_id: rest.room_id, name: restName, ok: false, text: `${restName}: ${why}`, photos: [] }
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
    uploadResult.batchId = draft.batchId
    uploadResult.rooms = list.flatMap((room) => next[room.room_id] ?? earlier[room.room_id] ?? [])
    // (다) 결과 화면으로. replace — 뒤로 가기로 이 화면에 돌아와 같은 묶음을 또 보내지 않게
    nav('/upload/result', { replace: true })
  }

  return (
    <main className="page fam-skin">
      <h1>올릴 가족방 고르기</h1>
      <section className="card">
        <p className="upload-count">사진 {draft.files.length}장</p>
        <PhotoGrid files={draft.files} />
        {/*
          보내는 중·한 번 보낸 묶음(다시 보내기)은 글을 못 고친다. 서버는 같은 번호(upload_batch_id)의
          두 번째 요청에 처음 저장본을 그대로 돌려줘서, 글을 고쳐 다시 보내도 바뀌지 않는다 (D17).
          고칠 때마다 uploadDraft 에도 적는다 — draft 는 열 때 만든 복사본이라, 뒤로 갔다 와도 글이 남게
        */}
        <div className="form">
          <label>
            한마디 (선택)
            <input
              value={caption}
              maxLength={MAX_NOTE}
              placeholder="예: 설날 온 가족이 모인 날"
              disabled={busy || retry}
              onChange={(e) => {
                setCaption(e.target.value)
                uploadDraft.caption = e.target.value
              }}
            />
          </label>
          <label>
            사진 속 사람 (선택)
            <input
              value={peopleNote}
              maxLength={MAX_NOTE}
              placeholder="예: 할머니, 큰딸, 손주 둘"
              disabled={busy || retry}
              onChange={(e) => {
                setPeopleNote(e.target.value)
                uploadDraft.peopleNote = e.target.value
              }}
            />
          </label>
          <p className="muted">안 적어도 돼요. 적어 두면 AI 가 어르신과 이야기할 때 참고해요.</p>
        </div>
      </section>
      <section className="card">
        {list.map((room) => (
          <label key={room.room_id} className="row upload-room">
            {/* 보내는 동안, 그리고 다시 보내기에서 이미 보낸 곳은 잠근다 */}
            <input
              type="checkbox"
              checked={isChecked(room.room_id)}
              onChange={() => toggle(room.room_id)}
              disabled={busy || done.has(room.room_id)}
            />
            {room.elder_name} {room.elder_honorific}{done.has(room.room_id) && ' (보냄)'}
          </label>
        ))}
        {!sent && (
          <button className="btn" onClick={() => send(checked)} disabled={busy || checked.length === 0}>
            {busy ? '보내는 중…' : '보내기'}
          </button>
        )}
        {list.map((room) => {
          const r = results[room.room_id]
          return r && <p key={room.room_id} className={r.ok ? undefined : 'error'}>{r.text}</p>
        })}
        {sent && busy && <p className="muted">보내는 중…</p>}
      </section>
    </main>
  )
}
