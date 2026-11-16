/**
 * FDIARY_003 — 오늘 한 장 3/3: 초안 확인·게시 (이슈 #41, 목업 설계자료/목업_1115_가족 ④ '오늘 한 장 3/3'). 하위 화면(위 ←).
 * 일기 동무 초안을 바로 고치고(200자), 보낼 분(내 가족방 — 기본 전부)마다 할머니께 실제로 읽어 드리는 첫 문장을 보여 준다.
 * [게시하기] → 방마다 (사진이 있으면) 사진 올리기 → 일기 올리기. 다 되면 가족 홈 맨 위 카드, 어르신 '가족 소식'.
 * 한 방이라도 올라가면 보낸 그대로(lib/familyDiaryDraft 의 sent)를 고정해 남은 방에 같은 일기만 다시 보낸다.
 */
import { useEffect, useRef, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { MOOD_LABEL, type DiaryOut, type PhotoBatchOut, type RoomOut, type UserOut } from '../../api/types'
import MoodIcon from '../../components/MoodIcon'
import { useFetch } from '../../hooks/useFetch'
import { clearFamilyDiaryDraft, familyDiaryDraft as d } from '../../lib/familyDiaryDraft'
import { PHOTO_PROBLEMS } from '../../lib/uploadDraft'
import { Thumb } from './UPLOAD_001'
import './steps.css'
import './FDIARY_002.css'
import './FDIARY_003.css'

const MAX = 200 // 초안 글자 수 (D61 — 어르신 화면에 한 번에 보이는 길이)
// 이 답이 오면 남은 방에 보내도 같은 답이라 멈춘다: 사진 자체가 문제(UPLOAD_002 와 같은 목록) · 서버 전체 사진 차례 기다림(방마다 60초씩 기다리지 않게)
const STOP = [...PHOTO_PROBLEMS, 'UPLOAD_BUSY']
// GET /api/rooms/{id}/members 에서 쓰는 칸만 — 온전한 MemberOut 은 #173 에서 types.ts 에 들어간다(합칠 때 겹치지 않게 여기만)
type Member = { user_id: number; nickname: string | null }
type Result = { ok: boolean; why?: string }

const nameOf = (r: RoomOut) => `${r.elder_name} ${r.elder_honorific}`
/** 받침이 있으면 앞의 조사, 없으면 뒤의 조사 — 어르신 화면 ELDER_FAMILY_001 의 josa 와 같은 식 */
function josa(word: string, withFinal: string, without: string) {
  const code = word.charCodeAt(word.length - 1)
  return code >= 0xac00 && code <= 0xd7a3 && (code - 0xac00) % 28 !== 0 ? withFinal : without
}

export default function FDIARY_003() {
  const nav = useNavigate()
  // 하위 화면 틀이라 useFamily() 가 없다 → 지금 로그인한 사람을 직접 읽는다 (FDIARY_002 와 같음)
  const me = useFetch<UserOut>('/api/auth/me')
  // 2단계를 거쳐 왔는지·누가 쓰던 것인지·기분은 처음 열 때 한 번만 본다 — 게시 뒤 일기 칸을 비운 순간에 '다른 사람' 검사가
  // 걸려 홈 대신 1단계로 튕기지 않게(크롬에서 재현함). 초안이 비어 있어도 들어온다(비우고 다시 쓰는 중일 수 있음)
  const [start] = useState(() => ({ ready: !!d.room && !!d.mood, userId: d.userId, mood: d.mood }))
  // 한 방이라도 올라갔으면 보낸 그대로를 보여 준다(잠금). 아니면 지금 쓰는 것
  const [done, setDone] = useState<number[]>(() => [...d.done])
  const locked = done.length > 0 && !!d.sent
  const [body, setBody] = useState(() => (locked ? d.sent!.body : d.draft))
  const [targets, setTargets] = useState<number[]>(() => (locked ? d.sent!.targets : d.rooms.map((r) => r.room_id)))
  const [nick, setNick] = useState<Record<number, string | null>>({}) // 방마다 내 호칭(없으면 null)
  // 다시 들어왔을 때: 올라간 방은 '보냈어요', 보내기로 했는데 아직 못 간 방은 실패로 — 버튼이 '실패한 곳 다시 보내기'가 되게
  const [results, setResults] = useState<Record<number, Result>>(() =>
    locked
      ? Object.fromEntries(
          d.sent!.targets.map((id) => [id, done.includes(id) ? { ok: true } : { ok: false, why: '아직 못 보냈어요' }]),
        )
      : {},
  )
  const [busy, setBusy] = useState(false)
  const sending = useRef(false)
  const leaving = useRef<AbortController | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    leaving.current = controller
    return () => controller.abort()
  }, [])

  // 방마다 내 호칭 — 읽어 드리는 첫 문장이 어르신 화면과 같게. 못 읽은 방은 이름만으로 보여 준다
  const myId = me.data?.user_id
  useEffect(() => {
    if (!myId) return
    let alive = true
    for (const r of d.rooms) {
      api<Member[]>(`/api/rooms/${r.room_id}/members`)
        .then((list) => alive && setNick((n) => ({ ...n, [r.room_id]: list.find((m) => m.user_id === myId)?.nickname ?? null })))
        .catch(() => alive && setNick((n) => ({ ...n, [r.room_id]: null })))
    }
    return () => {
      alive = false
    }
  }, [myId])

  if (me.error?.status === 401) return <Navigate to="/login" replace />
  if (!start.ready || (me.data && start.userId !== me.data.user_id)) return <Navigate to="/fdiary" replace />
  if (me.error) {
    return (
      <main className="st">
        <p className="fam-error">{me.error.message}</p>
        <button type="button" className="fam-text-btn" onClick={me.reload}>
          다시 시도
        </button>
      </main>
    )
  }
  const mood = locked ? d.sent!.mood : start.mood
  if (!me.data || !mood) return <main className="st" aria-busy="true" />
  const user = me.data
  const photo = locked ? d.sent!.photo : d.photo
  const what = photo ? '사진 일기' : '일기'
  const failed = d.rooms.filter((r) => results[r.room_id] && !results[r.room_id].ok)

  function toggle(id: number) {
    setTargets((t) => (t.includes(id) ? t.filter((x) => x !== id) : [...t, id]))
  }

  async function post() {
    // busy(state)는 다시 그린 뒤에야 바뀌어 아주 빠른 두 번 누르기를 못 막는다 → ref 로 한 번 더 (서버도 같은 번호면 1개만)
    if (busy || sending.current || !body.trim() || targets.length === 0 || !mood) return
    sending.current = true
    const signal = leaving.current?.signal
    // 아직 한 방도 안 올라갔으면 지금 화면 그대로 새로 보낸다(새 번호) — 앞서 다 실패한 뒤 글·사진을 고쳤어도 새것으로.
    // 한 방이라도 올라갔으면 그때 보낸 그대로·같은 번호로 남은 방만 — 할머니마다 같은 일기
    if (d.done.length === 0) {
      d.sent = {
        postId: crypto.randomUUID(),
        batchId: crypto.randomUUID(),
        body: body.trim(),
        mood,
        photo: d.photo,
        targets: [...targets],
      }
    }
    const s = d.sent!
    setBusy(true)
    const next: Record<number, Result> = { ...results }
    // 차례로 보낸다(동시에 말고) — 서버가 사진 변환을 한 번에 한 요청씩 하므로 (UPLOAD_002 와 같음)
    const todo = d.rooms.filter((r) => s.targets.includes(r.room_id) && !d.done.includes(r.room_id))
    for (const room of todo) {
      try {
        let photoId: number | null = null
        if (s.photo) {
          const form = new FormData()
          form.append('files', s.photo)
          form.append('upload_batch_id', s.batchId)
          form.append('source', 'FAMILY_DIARY') // 사진첩·올린 사진·오늘의 한 장에 섞이지 않게 (#142)
          const up = await api<PhotoBatchOut>(`/api/rooms/${room.room_id}/photos`, { form, signal })
          photoId = up.photos[0].photo_id
        }
        await api<DiaryOut>(`/api/rooms/${room.room_id}/diaries`, {
          body: {
            request_id: s.postId,
            body: s.body,
            mood: s.mood,
            photo_id: photoId,
            illustration_type: photoId ? 'PHOTO' : 'NONE',
          },
          signal,
        })
        d.done.push(room.room_id) // 화면을 떠나도 남게 일기 칸에 바로 적는다
        next[room.room_id] = { ok: true }
      } catch (e) {
        if (signal?.aborted) return // 화면을 떠났다 — 남은 방에는 보내지 않는다
        if (e instanceof ApiError && e.status === 401) return nav('/login', { replace: true })
        const why = e instanceof ApiError ? e.message : '연결이 잠깐 끊겼어요. 다시 해 주세요.'
        next[room.room_id] = { ok: false, why }
        if (e instanceof ApiError && STOP.includes(e.code)) {
          for (const rest of todo) if (!next[rest.room_id]) next[rest.room_id] = { ok: false, why }
          break
        }
      }
      setResults({ ...next }) // 한 곳씩 끝날 때마다 보여 준다
    }
    setResults({ ...next })
    setDone([...d.done])
    if (s.targets.every((id) => d.done.includes(id))) {
      clearFamilyDiaryDraft()
      nav('/', { replace: true }) // 가족 홈 맨 위에 방금 쓴 일기. replace — 뒤로 가기로 이 화면에 돌아와 또 보내지 않게
      return
    }
    sending.current = false
    setBusy(false)
  }

  return (
    <main className="st">
      <div className="st-prog" aria-hidden="true">
        <i style={{ width: '100%' }} />
      </div>
      <div className="st-body">
        <div className="st-head">
          <p className="st-step">3/3 · 확인</p>
          <h1>초안을 확인해 주세요</h1>
          <p className="st-lead">
            {locked ? '보낸 일기 그대로 남은 분께 다시 보내요' : '일기 동무가 다듬었어요. 고쳐도 돼요'}
          </p>
        </div>

        <section className="fam-card fd2-form">
          <div className="fd3-top">
            {photo && (
              <span className="fd3-thumb">
                <Thumb file={photo} alt="고른 사진" />
              </span>
            )}
            <span className="fd3-chip">
              <MoodIcon mood={mood} />
              기분 · {MOOD_LABEL[mood]}
            </span>
          </div>
          <div className="fd2-field">
            <textarea
              className="fd2-input fd3-draft"
              rows={5}
              maxLength={MAX}
              value={body}
              disabled={locked}
              aria-label="일기 초안"
              onChange={(e) => (setBody(e.target.value), (d.draft = e.target.value))}
            />
            <span className="fd2-count">
              {body.length}/{MAX}
            </span>
          </div>

          <div className="fd2-field" role="group" aria-labelledby="fd3-to-label">
            <span className="fd2-label" id="fd3-to-label">
              보낼 분
            </span>
            <div className="fd2-moods">
              {d.rooms.map((r) => (
                <button
                  key={r.room_id}
                  type="button"
                  className={targets.includes(r.room_id) ? 'fd2-mood on' : 'fd2-mood'}
                  aria-pressed={targets.includes(r.room_id)}
                  disabled={locked}
                  onClick={() => toggle(r.room_id)}
                >
                  {nameOf(r)}
                </button>
              ))}
            </div>
          </div>

          {targets.length > 0 && (
            <div className="fd3-readout">
              <p className="fd3-readout-h">이렇게 읽어 드려요</p>
              <ul>
                {d.rooms
                  .filter((r) => targets.includes(r.room_id))
                  .map((r) => {
                    // 어르신 화면 ELDER_FAMILY_001 의 sender 와 같은 모양 — 호칭 + 이름, 없으면 '가족'
                    const sender = [nick[r.room_id], user.name].filter(Boolean).join(' ') || '가족'
                    return (
                      <li key={r.room_id}>
                        <b>{nameOf(r)}께</b>“{sender}
                        {josa(sender, '이', '가')} {what}를 보냈어요. 읽어 드릴게요.”
                        {results[r.room_id] && (
                          <small className={results[r.room_id].ok ? 'fd3-ok' : 'fd3-fail'}>
                            {results[r.room_id].ok ? '보냈어요' : results[r.room_id].why}
                          </small>
                        )}
                      </li>
                    )
                  })}
              </ul>
              <p className="fd3-fine">그다음에 위 글을 그대로 읽어 드려요</p>
            </div>
          )}
        </section>
        {failed.length > 0 && (
          <p className="fam-error" role="alert">
            {failed.map(nameOf).join(', ')}께 보내지 못했어요. 다시 보내 주세요
          </p>
        )}
      </div>

      <div className="st-cta">
        {/* 한 방이라도 올라가면 고쳐 쓰기를 숨긴다 — 남은 방에도 같은 일기가 가야 해서. 다 실패했으면 사진·글을 고치러 갈 수 있다 */}
        {!locked && (
          <button type="button" className="fam-btn fam-btn--tonal" disabled={busy} onClick={() => nav(-1)}>
            고쳐 쓰기
          </button>
        )}
        <button
          type="button"
          className="fam-btn fam-btn--primary st-wide"
          disabled={busy || !body.trim() || targets.length === 0}
          onClick={post}
        >
          {busy ? '보내는 중…' : failed.length > 0 ? '실패한 곳 다시 보내기' : '게시하기'}
        </button>
      </div>
    </main>
  )
}
