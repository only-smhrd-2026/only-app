/**
 * UPLOAD_001 — 추억 올리기 1/3: 사진 고르기 (FR-ME-001, D17, 목업 설계자료/목업_1115_가족 ④ '추억 올리기 1/3').
 * 폰 앨범에서 여러 장 골라 [다음] → UPLOAD_002 보낼 분·한마디·올리기 → UPLOAD_003 결과.
 * 진행 막대·아래 버튼은 steps.css, 고른 사진 3열·× 빼기·[더 고르기]는 이 파일의 CSS.
 */
import { useEffect, useRef, useState, type ChangeEvent, type ReactNode } from 'react'
import { Link, Navigate, useNavigate, useNavigationType } from 'react-router-dom'
import type { RoomOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import { useFetch } from '../../hooks/useFetch'
import { fitPhoto, MAX_BYTES } from '../../lib/fitPhoto'
import { uploadDraft } from '../../lib/uploadDraft'
import './steps.css'
import './UPLOAD_001.css'

// 서버 config.py 의 UPLOAD_MAX_FILES 와 같게 (용량·화소 상한은 lib/fitPhoto)
const MAX_FILES = 20

/** 줄인 사진 → 원본 사진의 fileKey. 줄이면 크기가 바뀌어도 같은 사진을 또 고른 것을 알아보게 */
const originalKey = new WeakMap<File, string>()

/** 같은 사진인지 가리는 값 — 이름·크기·찍은(고친) 시각(줄인 사진은 원본 것). 두 번 고르기를 막고, 격자의 이름표(key)로도 쓴다 */
const fileKey = (f: File) => originalKey.get(f) ?? `${f.name}:${f.size}:${f.lastModified}`

/**
 * 고른 사진 3열 격자 (이 화면만 쓴다. Thumb 는 UPLOAD_002·003·FDIARY 도 같이 쓴다).
 * onRemove 를 주면 사진마다 × (빼기), add 를 주면 맨 끝 칸에 그것(이 화면의 [더 고르기])을 놓는다.
 */
export function PhotoGrid({ files, onRemove, add }: { files: File[]; onRemove?: (i: number) => void; add?: ReactNode }) {
  return (
    <ul className="upload-grid">
      {/* 순서 번호를 이름표로 쓰면 × 로 가운데를 뺄 때 뒤 사진이 전부 다시 그려지고 포커스가 다른 사진으로 간다 */}
      {files.map((file, i) => (
        <li key={fileKey(file)}>
          <Thumb file={file} alt={`고른 사진 ${i + 1}`} />
          {onRemove && (
            <button type="button" className="up-rm" onClick={() => onRemove(i)} aria-label={`${i + 1}번째 사진 빼기`}>
              ×
            </button>
          )}
        </li>
      ))}
      {add && <li>{add}</li>}
    </ul>
  )
}

/**
 * 사진 한 장 미리보기. 미리보기 주소(URL.createObjectURL)를 이 그림이 직접 만들고, 사라질 때 지운다(안 지우면 사진이 메모리에 남음).
 * 화면이 주소를 한 번만 만들어 두면, 개발 모드(StrictMode)의 '열기→닫기→다시 열기'에서 닫을 때 지운 주소를 다시 써서
 * 뒤로 가기로 돌아온 사진이 깨졌다(그림 폭 0 으로 재현). 열 때마다 새로 만들면 안 깨진다. 가족 일기 FDIARY_001 도 같이 쓴다.
 */
export function Thumb({ file, alt }: { file: File; alt: string }) {
  const img = useRef<HTMLImageElement>(null)
  useEffect(() => {
    const url = URL.createObjectURL(file)
    if (img.current) img.current.src = url
    return () => URL.revokeObjectURL(url)
  }, [file])
  return <img ref={img} alt={alt} />
}

/** 폰 사진 창을 여는 칸 — 보이지 않게 두고 감싼 label 전체를 누르면 열린다. HEIC 는 서버가 받지 않는다(D17).
 *  아이폰 Safari 는 이 accept 면 JPEG 로 바꿔 보낸다 */
function FileInput({ onPick, disabled }: { onPick: (e: ChangeEvent<HTMLInputElement>) => void; disabled: boolean }) {
  return (
    <input className="up-file" type="file" multiple accept="image/jpeg,image/png" onChange={onPick} disabled={disabled} />
  )
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
  const [preparing, setPreparing] = useState(false) // 큰 사진 줄이는 중 — 그동안 고르기·[다음] 막기

  /** 고른 사진에 더한다([사진 고르기]·[더 고르기] 둘 다) */
  async function onPick(e: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? [])
    e.target.value = '' // 같은 사진을 다시 골라도 onChange 가 오게
    if (picked.length === 0) return // 고르다 취소 — 앞서 고른 것 그대로
    // 이미 고른 사진은 빼고 더한다 — 안 빼면 같은 사진이 서버에 두 번 저장된다(서버는 사진 내용을 비교하지 않음)
    const seen = new Set(files.map(fileKey))
    const chosen: File[] = []
    for (const f of picked) {
      if (seen.has(fileKey(f))) continue
      seen.add(fileKey(f))
      chosen.push(f)
    }
    if (chosen.length === 0) return setError('이미 고른 사진이에요')
    // 받지 않는 선택이면 앞서 고른 사진과 요청 번호를 둘 다 그대로 둔다
    if (files.length + chosen.length > MAX_FILES) {
      return setError(`사진은 한 번에 ${MAX_FILES}장까지 올릴 수 있어요 (지금 ${files.length}장)`)
    }
    // 한 장씩 — 20장을 한꺼번에 열면 폰 메모리가 모자랄 수 있다
    setError('')
    setPreparing(true)
    const fitted: File[] = []
    try {
      for (const f of chosen) {
        const fit = await fitPhoto(f)
        originalKey.set(fit, fileKey(f)) // 줄인 사진도 원본 이름표로 — 같은 큰 사진을 또 고르면 위에서 걸러진다
        fitted.push(fit)
      }
    } finally {
      setPreparing(false)
    }
    // 줄여도 큰 사진(긴 변 2560 안인데 10MB 넘는 png 등)
    const big = fitted.findIndex((f) => f.size > MAX_BYTES)
    if (big >= 0) return setError(`방금 고른 ${big + 1}번째 사진이 ${MAX_BYTES / 1024 / 1024}MB보다 커요`)
    // 준비하는 동안 × 로 뺀 사진이 있을 수 있어 그때의 목록에 더한다
    setFiles((prev) => [...prev, ...fitted])
    // 사진 묶음이 바뀔 때마다(더하기·빼기) 새 요청 번호 (D17). 묶음이 달라졌는데 번호가 같으면 서버가 같은 묶음으로 보고
    // 저장을 건너뛸 수 있다. 다시 보내기는 UPLOAD_002 가 같은 번호로 → 서버가 두 번 저장하지 않음
    setBatchId(crypto.randomUUID())
  }

  function remove(i: number) {
    setError('')
    setFiles(files.filter((_, j) => j !== i))
    setBatchId(crypto.randomUUID()) // 위 onPick 과 같은 이유
  }

  function next() {
    // 사진을 통째로 새로 골랐으면 앞 사진에 적은 한마디·사진 속 사람을 비운다 — 새 사진에 붙지 않게.
    // 앞 사진이 한 장이라도 남아 있으면(더하기·빼기만 함) 같은 묶음을 고친 것이라 적은 글을 둔다
    const sameSet = files.some((f) => uploadDraft.files.includes(f))
    if (uploadDraft.batchId !== batchId && !sameSet) {
      uploadDraft.caption = ''
      uploadDraft.peopleNote = ''
      uploadDraft.peopleIds = []
    }
    uploadDraft.files = files
    uploadDraft.batchId = batchId
    nav('/upload/target')
  }

  if (rooms.error?.status === 401) return <Navigate to="/login" replace />

  return (
    <main className="st">
      <div className="st-prog" aria-hidden="true">
        <i style={{ width: '33.3%' }} />
      </div>
      <div className="st-body">
        <div className="st-head">
          <p className="st-step">1/3 · 사진 고르기</p>
          <h1>추억 올리기</h1>
          <p className="st-lead">
            {files.length > 0 ? `${files.length}장 골랐어요` : '어르신과 이야기할 옛 사진을 골라 주세요'}
          </p>
        </div>

        {rooms.error ? (
          <>
            <p className="fam-error up-error">{rooms.error.message}</p>
            <button type="button" className="fam-btn fam-btn--tonal up-retry" onClick={rooms.reload}>
              다시 시도
            </button>
          </>
        ) : !rooms.data ? (
          <p className="up-hint">불러오는 중…</p>
        ) : rooms.data.length === 0 ? (
          <p className="up-hint">
            먼저 가족방을 만들어 주세요 · <Link to="/groups/new">가족방 만들기</Link>
          </p>
        ) : files.length === 0 ? (
          <>
            <label className="up-picker">
              <FileInput onPick={onPick} disabled={preparing} />
              <span className="up-ring">
                <FamIcon name="imagePlus" />
              </span>
              <b>사진 고르기</b>
              <small>
                여러 장 고를 수 있어요 · 한 번에 {MAX_FILES}장까지
              </small>
            </label>
            <p className="up-hint">올린 사진은 내일부터 '오늘의 한 장' 후보가 돼요</p>
          </>
        ) : (
          <div className="up-grid">
            <PhotoGrid
              files={files}
              onRemove={remove}
              add={
                files.length < MAX_FILES && (
                  <label className="up-add">
                    <FileInput onPick={onPick} disabled={preparing} />
                    <FamIcon name="plus" />
                    더 고르기
                  </label>
                )
              }
            />
          </div>
        )}
        {/* 사진 국외 전송 안내 (D71) — 가족방이 있어 사진을 고를 수 있을 때만. 자세히는 처리방침의 '맡기는 곳' */}
        {!!rooms.data?.length && (
          <p className="up-hint">
            사진은 AI가 살펴보도록 미국(Anthropic)으로 보내져요 · <Link to="/policy#vendors">자세히 ›</Link>
          </p>
        )}
        {preparing && (
          <p className="up-hint" role="status">
            사진을 준비하는 중…
          </p>
        )}
        {error && (
          <p className="fam-error up-error" role="alert">
            {error}
          </p>
        )}
      </div>

      {/* 가족방 목록이 온 뒤에만 — 뒤로 돌아온 직후 목록을 못 불러왔으면 보낼 곳을 모른 채 넘어가지 않게 */}
      {files.length > 0 && !!rooms.data?.length && (
        <div className="st-cta">
          <button type="button" className="fam-btn fam-btn--primary" onClick={next} disabled={preparing}>
            다음 · {files.length}장
          </button>
        </div>
      )}
    </main>
  )
}
