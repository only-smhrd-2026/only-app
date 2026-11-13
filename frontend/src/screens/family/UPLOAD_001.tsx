/**
 * UPLOAD_001 — 사진 올리기 1/2: 사진 고르기 (FR-ME-001, D17). 폰 앨범에서 여러 장 골라 [다음] → UPLOAD_002 가족방 고르기·보내기.
 * → UPLOAD_003 결과. 모양은 11/12 목업 가족 화면 값(.fam-skin, 이 파일의 CSS).
 */
import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { Link, Navigate, useNavigate, useNavigationType } from 'react-router-dom'
import type { RoomOut } from '../../api/types'
import { useFetch } from '../../hooks/useFetch'
import { uploadDraft } from '../../lib/uploadDraft'
import './UPLOAD_001.css'

// 서버 config.py 의 UPLOAD_MAX_FILES·UPLOAD_MAX_BYTES 와 같게
const MAX_FILES = 20
const MAX_BYTES = 10 * 1024 * 1024

/** 고른 사진 작은 격자 — UPLOAD_002 도 같이 쓴다 */
export function PhotoGrid({ files }: { files: File[] }) {
  return (
    <ul className="upload-grid">
      {files.map((file, i) => (
        <li key={i}><Thumb file={file} alt={`고른 사진 ${i + 1}`} /></li>
      ))}
    </ul>
  )
}

/**
 * 사진 한 장 미리보기. 미리보기 주소(URL.createObjectURL)를 이 그림이 직접 만들고, 사라질 때 지운다(안 지우면 사진이 메모리에 남음).
 * 화면이 주소를 한 번만 만들어 두면, 개발 모드(StrictMode)의 '열기→닫기→다시 열기'에서 닫을 때 지운 주소를 다시 써서
 * 뒤로 가기로 돌아온 사진이 깨졌다(그림 폭 0 으로 재현). 열 때마다 새로 만들면 안 깨진다.
 */
function Thumb({ file, alt }: { file: File; alt: string }) {
  const img = useRef<HTMLImageElement>(null)
  useEffect(() => {
    const url = URL.createObjectURL(file)
    if (img.current) img.current.src = url
    return () => URL.revokeObjectURL(url)
  }, [file])
  return <img ref={img} alt={alt} />
}

export default function UPLOAD_001() {
  const nav = useNavigate()
  // 로그인·가족방 0개는 사진을 고르기 전에 알린다 (보낼 가족방 고르기는 UPLOAD_002)
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  // 다음 화면에서 뒤로 가기로 돌아올 때(POP)만 고른 사진과 번호를 되살린다.
  // 링크·버튼으로 들어오면 빈 상태 — 같은 창에서 로그아웃 뒤 다른 계정이 들어와도 앞 사람이 고른 사진이 남지 않게(재현함).
  // ponytail: 다른 계정이 브라우저 뒤로 가기로 여기까지 거슬러 오면 남을 수 있음. 막으려면 로그아웃 때 uploadDraft 비우기(HOME_001)
  const fromBack = useNavigationType() === 'POP'
  const [files, setFiles] = useState<File[]>(() => (fromBack ? uploadDraft.files : []))
  const [batchId, setBatchId] = useState(() => (fromBack ? uploadDraft.batchId : ''))
  const [error, setError] = useState('')

  function onPick(e: ChangeEvent<HTMLInputElement>) {
    const chosen = Array.from(e.target.files ?? [])
    e.target.value = '' // 같은 사진을 다시 골라도 onChange 가 오게
    if (chosen.length === 0) return // 고르다 취소 — 앞서 고른 것 그대로
    // 받지 않는 선택이면 앞서 고른 사진과 요청 번호를 둘 다 그대로 둔다
    if (chosen.length > MAX_FILES) return setError(`사진은 한 번에 ${MAX_FILES}장까지 고를 수 있어요`)
    const big = chosen.findIndex((f) => f.size > MAX_BYTES)
    if (big >= 0) return setError(`${big + 1}번째 사진이 ${MAX_BYTES / 1024 / 1024}MB보다 커요`)
    setError('')
    setFiles(chosen)
    // 새 요청 번호는 사진을 고를 때만 (D17). 다시 보내기는 UPLOAD_002 가 같은 번호로 → 서버가 두 번 저장하지 않음
    setBatchId(crypto.randomUUID())
  }

  function next() {
    // 사진을 새로 골랐으면(번호가 다름) 앞 사진에 적은 한마디·사진 속 사람을 비운다 — 새 사진에 붙지 않게
    if (uploadDraft.batchId !== batchId) {
      uploadDraft.caption = ''
      uploadDraft.peopleNote = ''
    }
    uploadDraft.files = files
    uploadDraft.batchId = batchId
    nav('/upload/target')
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

  if (rooms.data.length === 0) {
    return (
      <main className="page fam-skin">
        <h1>사진 올리기</h1>
        <p>먼저 가족방을 만들어 주세요</p>
        <Link className="btn" to="/groups/new">가족방 만들기</Link>
      </main>
    )
  }

  return (
    <main className="page fam-skin">
      <h1>사진 올리기</h1>
      <section className="card">
        {/* HEIC 는 서버가 받지 않는다(D17). 아이폰 Safari 는 이 accept 면 JPEG 로 바꿔 보낸다 */}
        <input
          className="upload-file"
          type="file"
          multiple
          accept="image/jpeg,image/png"
          onChange={onPick}
          aria-label="사진 고르기"
        />
        <p className="muted">여러 장 고를 수 있어요. 한 번에 {MAX_FILES}장, 한 장 {MAX_BYTES / 1024 / 1024}MB까지</p>
        {error && <p className="error" role="alert">{error}</p>}
        {files.length > 0 && <PhotoGrid files={files} />}
        <button className="btn" onClick={next} disabled={files.length === 0}>
          사진 {files.length}장 · 다음
        </button>
      </section>
    </main>
  )
}
