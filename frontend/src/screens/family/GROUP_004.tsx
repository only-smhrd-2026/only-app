/**
 * GROUP_004 — 올린 사진 (11/14 밤 새 화면, D73 — 목업 설계자료/목업_1115_가족 ⑦). 가족방 탭의 하위 화면(위 ←).
 * 가족이 올린 사진(FAMILY)마다 AI 가 본 활동 칩 → 누르면 'AI 가 본 것'(활동·보이는 모습) 판 → [활동 고치기] 판.
 * 고친 활동은 문제 고르기와 다음 대화의 사진 설명으로 쓴다(서버 PATCH …/correction, FR-ME-009). AI 가 본 것은 그대로 남는다.
 */
import { useEffect, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { PhotoListOut, PhotoOut, RoomOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import { useFetch } from '../../hooks/useFetch'
import './GROUP_004.css'

// data/taxonomy.json 의 activity 20개와 같은 글자·순서 (backend/tests/test_data_files.py 가 맞는지 본다)
const ACTIVITIES = [
  '김장', '장 담그기', '떡 만들기', '모내기', '농사', '잔치', '결혼식', '명절 차례', '생일', '가족 식사',
  '장날', '운동회', '소풍', '졸업식', '바닷가', '꽃구경', '등산', '여행', '손주 돌보기', '겨울 놀이',
]
const NONE = 'none' // 맞는 활동 없음 (분류 AI·가족 고치기 둘 다 같은 글자)
const nameOf = (v: string) => (v === NONE ? '맞는 것 없음' : v)
// 받침이 있으면 '과', 없으면 '와' — 할머니와 / 어머님과
const wa = (w: string) => ((w.charCodeAt(w.length - 1) - 0xac00) % 28 ? '과' : '와')

/** 사진 칸의 칩 — 가족이 고친 활동이 먼저, 분류 전이면 'AI 가 보는 중' */
function chipOf(p: PhotoOut): [string, string] {
  if (p.corrected_activity) return [nameOf(p.corrected_activity), ' fixed']
  if (!p.analyzed) return ['AI 가 보는 중', ' wait']
  return [p.ai_activity && p.ai_activity !== NONE ? p.ai_activity : '활동 없음', '']
}

export default function GROUP_004() {
  const { roomId } = useParams()
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  const list = useFetch<PhotoListOut>(`/api/rooms/${roomId}/photos`)
  const [saved, setSaved] = useState<Record<number, PhotoOut>>({}) // 고친 뒤 서버가 돌려준 사진으로 덮어쓴다
  const [open, setOpen] = useState<{ id: number; step: 'ai' | 'fix' }>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [note, setNote] = useState<string>()

  useEffect(() => {
    if (!note) return
    const timer = window.setTimeout(() => setNote(undefined), 2600)
    return () => window.clearTimeout(timer)
  }, [note])

  async function fix(p: PhotoOut, value: string) {
    if (busy) return
    setBusy(true)
    setError(undefined)
    try {
      const out = await api<PhotoOut>(`/api/rooms/${roomId}/photos/${p.photo_id}/correction`, {
        method: 'PATCH',
        body: { corrected_activity: value },
      })
      setSaved((s) => ({ ...s, [out.photo_id]: out }))
      setOpen(undefined)
      setNote(`고쳤어요 · 다음 대화부터 '${nameOf(value)}' 사진으로 봐요`)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '고치지 못했어요. 다시 해 주세요')
    }
    setBusy(false)
  }

  if (rooms.error?.status === 401 || list.error?.status === 401) return <Navigate to="/login" replace />
  const failed = rooms.error ?? list.error
  if (failed) {
    return (
      <main className="fam-stack">
        <p className="fam-error">{failed.message}</p>
        <button type="button" className="fam-text-btn" onClick={() => (rooms.reload(), list.reload())}>
          다시 시도
        </button>
      </main>
    )
  }
  if (!rooms.data || !list.data) return <main className="fam-stack" aria-busy="true" />
  const room = rooms.data.find((r) => String(r.room_id) === roomId)
  if (!room) {
    return (
      <main className="fam-stack">
        <p className="fam-error">가족방을 찾을 수 없어요</p>
        <Link className="fam-text-btn" to="/">가족 홈으로</Link>
      </main>
    )
  }

  const hon = room.elder_honorific
  // 가족이 올린 사진만 — 어르신이 일기에 찍은 사진(ELDER_CAMERA)은 일기 대화 때 따로 분류한다
  const photos = list.data.photos.filter((p) => p.source === 'FAMILY').map((p) => saved[p.photo_id] ?? p)
  const cur = open && photos.find((p) => p.photo_id === open.id)
  const curAct = cur && (cur.corrected_activity ?? cur.ai_activity ?? NONE)
  const close = () => (setOpen(undefined), setError(undefined))

  return (
    <main className="fam-stack gp">
      <div className="gp-head">
        <h1>올린 사진</h1>
        <p>
          {room.elder_name} {hon}네 · {photos.length}장
        </p>
      </div>
      <p className="gp-intro">
        AI 가 사진을 보고 {hon}
        {wa(hon)} 나눌 이야기 거리를 골라요. {hon}께는 사실처럼 말하지 않고 '~같아요'로만 말해요.
      </p>

      {photos.length === 0 ? (
        <section className="fam-card gp-empty">
          <p>아직 올린 사진이 없어요</p>
          <Link className="fam-btn fam-btn--primary" to="/upload">
            사진 올리기
          </Link>
        </section>
      ) : (
        <div className="gp-grid">
          {photos.map((p) => {
            const [label, cls] = chipOf(p)
            return (
              <button
                key={p.photo_id}
                type="button"
                className="gp-tile"
                onClick={() => (setError(undefined), setOpen({ id: p.photo_id, step: 'ai' }))}
                aria-label={`올린 사진 · ${label}`}
              >
                <img src={p.url} alt="" loading="lazy" />
                <span className={`gp-ai${cls}`}>{label}</span>
              </button>
            )
          })}
        </div>
      )}

      {cur && open?.step === 'ai' && (
        <>
          <button type="button" className="fam-scrim" aria-label="닫기" onClick={close} />
          <div className="fam-sheet gp-sheet" role="dialog" aria-label="AI 가 본 것">
            <span className="fam-grab" />
            <h2>{cur.analyzed ? 'AI 가 본 것' : 'AI 가 보는 중이에요'}</h2>
            <div className="gp-pic">
              <img src={cur.url} alt="올린 사진" />
            </div>
            {cur.analyzed ? (
              <>
                <div className="gp-chips">
                  <span className="gp-chip">활동 · {nameOf(curAct ?? NONE)}</span>
                  {cur.corrected_activity && <span className="gp-chip on">가족이 고침</span>}
                </div>
                {cur.ai_scene && <p className="gp-line">{cur.ai_scene}</p>}
                <p className="gp-fine">
                  {hon}
                  {wa(hon)} 이야기할 때 첫 질문과 생각 문제 거리로 써요. {hon}께는 사실처럼 말하지 않고 '~같아요'로만
                  말해요.
                </p>
                <div className="gp-cta">
                  <button
                    type="button"
                    className="fam-btn fam-btn--primary fam-btn--block"
                    onClick={() => setOpen({ id: cur.photo_id, step: 'fix' })}
                  >
                    활동 고치기
                  </button>
                </div>
              </>
            ) : (
              <p className="gp-fine">올린 뒤 10분 안에 끝나요. 끝나면 여기에서 AI 가 본 것을 볼 수 있어요.</p>
            )}
          </div>
        </>
      )}

      {cur && open?.step === 'fix' && (
        <>
          <button type="button" className="fam-scrim" aria-label="닫기" onClick={close} />
          <div className="fam-sheet" role="dialog" aria-label="어떤 일을 하는 사진인가요?">
            <span className="fam-grab" />
            <h2>어떤 일을 하는 사진인가요?</h2>
            <p className="gp-sheet-text">고르면 바로 저장돼요 · {hon}의 다음 대화부터 써요</p>
            <div className="gp-opts">
              {[...ACTIVITIES, NONE].map((v) => {
                const on = v === curAct
                return (
                  <button
                    key={v}
                    type="button"
                    className={on ? 'fam-opt on' : 'fam-opt'}
                    onClick={() => fix(cur, v)}
                    disabled={busy}
                  >
                    <span>
                      <b>{nameOf(v)}</b>
                    </span>
                    {on && <FamIcon name="check" className="fam-ok" />}
                  </button>
                )
              })}
            </div>
            {error && (
              <p className="fam-error" role="alert">
                {error}
              </p>
            )}
          </div>
        </>
      )}

      {note && (
        <p className="gp-snack" role="status">
          {note}
        </p>
      )}
    </main>
  )
}
