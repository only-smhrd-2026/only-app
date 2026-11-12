/**
 * UPLOAD_001 — 사진 올리기 (FR-ME-001, D17). 폰 앨범에서 여러 장 골라 내 첫 번째 가족방으로 보낸다.
 * 가족방 고르기는 UPLOAD_002, 결과 화면은 UPLOAD_003 (나중에). 디자인 없음 (김승희 교체).
 */
import { useEffect, useState, type ChangeEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { PhotoBatchOut, RoomOut } from '../../api/types'
import { useFetch } from '../../hooks/useFetch'
import './UPLOAD_001.css'

// 서버 config.py 의 UPLOAD_MAX_FILES·UPLOAD_MAX_BYTES 와 같게
const MAX_FILES = 20
const MAX_BYTES = 10 * 1024 * 1024

type Picked = { file: File; url: string } // url = 미리보기용 주소 (URL.createObjectURL)

export default function UPLOAD_001() {
  const nav = useNavigate()
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  const [picked, setPicked] = useState<Picked[]>([])
  const [batchId, setBatchId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [doneCount, setDoneCount] = useState<number | null>(null)

  // 고른 사진이 바뀌거나 화면을 떠나면 앞 미리보기 주소를 지운다 (안 지우면 사진이 메모리에 남음)
  useEffect(() => () => picked.forEach((p) => URL.revokeObjectURL(p.url)), [picked])

  function onPick(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    e.target.value = '' // 같은 사진을 다시 골라도 onChange 가 오게
    if (files.length === 0) return // 고르다 취소 — 앞서 고른 것 그대로
    // 받지 않는 선택이면 앞서 고른 사진과 요청 번호를 둘 다 그대로 둔다
    if (files.length > MAX_FILES) return setError(`사진은 한 번에 ${MAX_FILES}장까지 고를 수 있어요`)
    const big = files.findIndex((f) => f.size > MAX_BYTES)
    if (big >= 0) return setError(`${big + 1}번째 사진이 ${MAX_BYTES / 1024 / 1024}MB보다 커요`)
    setError('')
    setPicked(files.map((file) => ({ file, url: URL.createObjectURL(file) })))
    // 새 요청 번호는 사진을 고를 때만 (D17). [올리기]를 다시 누를 때는 같은 번호 → 서버가 두 번 저장하지 않음
    setBatchId(crypto.randomUUID())
  }

  async function upload(room: RoomOut) {
    setBusy(true)
    setError('')
    const form = new FormData()
    picked.forEach((p) => form.append('files', p.file))
    form.append('upload_batch_id', batchId)
    try {
      const r = await api<PhotoBatchOut>(`/api/rooms/${room.room_id}/photos`, { form })
      setDoneCount(r.photos.length)
    } catch (e) {
      // 고르는 사이 로그인이 풀림 — 다시 눌러도 계속 실패하니 가족방 읽기(아래 401)처럼 로그인 화면으로
      if (e instanceof ApiError && e.status === 401) return nav('/login', { replace: true })
      // 실패해도 고른 사진과 번호는 그대로 — 다시 누르면 같은 번호로 다시 보낸다
      setError(e instanceof ApiError ? e.message : '연결이 잠깐 끊겼어요. 다시 해 주세요.')
    } finally {
      setBusy(false)
    }
  }

  function again() {
    setPicked([])
    setDoneCount(null)
  }

  if (rooms.error?.status === 401) return <Navigate to="/login" replace />
  if (rooms.error) return <main className="page"><p className="error">{rooms.error.message}</p></main>
  if (!rooms.data) return <main className="page"><p className="muted">불러오는 중…</p></main>

  const room = rooms.data[0] // 가족방 고르기는 UPLOAD_002 에서
  if (!room) {
    return (
      <main className="page">
        <h1>사진 올리기</h1>
        <p>먼저 가족방을 만들어 주세요</p>
        <Link className="btn" to="/groups/new">가족방 만들기</Link>
      </main>
    )
  }
  const to = `${room.elder_name} ${room.elder_honorific}`

  return (
    <main className="page">
      <h1>사진 올리기</h1>
      <p>{to}께 보내요</p>
      {doneCount !== null ? (
        <section className="card">
          <p>{to}께 사진 {doneCount}장을 올렸어요. 내일부터 오늘의 한 장 후보가 돼요.</p>
          <div className="row">
            <button className="btn secondary" onClick={again}>사진 더 올리기</button>
            <Link className="btn" to="/">가족 홈으로</Link>
          </div>
        </section>
      ) : (
        <section className="card">
          {/* HEIC 는 서버가 받지 않는다(D17). 아이폰 Safari 는 이 accept 면 JPEG 로 바꿔 보낸다 */}
          <input
            className="upload-file"
            type="file"
            multiple
            accept="image/jpeg,image/png"
            onChange={onPick}
            disabled={busy}
            aria-label="사진 고르기"
          />
          <p className="muted">여러 장 고를 수 있어요. 한 번에 {MAX_FILES}장, 한 장 {MAX_BYTES / 1024 / 1024}MB까지</p>
          {error && <p className="error" role="alert">{error}</p>}
          {picked.length > 0 && (
            <ul className="upload-grid">
              {picked.map((p, i) => (
                <li key={p.url}><img src={p.url} alt={`고른 사진 ${i + 1}`} /></li>
              ))}
            </ul>
          )}
          <button className="btn" onClick={() => upload(room)} disabled={busy || picked.length === 0}>
            {busy ? '올리는 중…' : `사진 ${picked.length}장 올리기`}
          </button>
        </section>
      )}
    </main>
  )
}
