/**
 * FDIARY_002 — 오늘 한 장 2/3: 한마디·일기 동무 (이슈 #41, 목업 설계자료/목업_1115_가족 ④ '오늘 한 장 2/3'). 하위 화면(위 ←).
 * 한마디(200자) → [다음] → 일기 동무(AI) 질문 하나 → 답(안 써도 됨)·기분 → [초안 만들기] → FDIARY_003.
 * 질문은 한 편에 한 번만 — 한마디를 고쳐도 다시 받지 않는다. 쓴 것은 lib/familyDiaryDraft 에 바로 담아 003 에서 돌아와도 남는다.
 * 내 PC(AI 키 없음)는 고정 질문·쓴 말을 이은 초안이 온다(진짜 AI 문장은 배포 서버).
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { MOOD_LABEL, type FamilyAskOut, type FamilyDraftOut, type Mood, type UserOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import MoodIcon from '../../components/MoodIcon'
import { useFetch } from '../../hooks/useFetch'
import { familyDiaryDraft as d } from '../../lib/familyDiaryDraft'
import { Thumb } from './UPLOAD_001'
import './steps.css'
import './FDIARY_002.css'

const MAX = 200 // 서버 config.py FAMILY_TEXT_MAX (한마디·답)
const MOODS: Mood[] = ['GOOD', 'SO_SO', 'UPSET', 'LONELY'] // D75 — 날씨 그림 대신 말·얼굴

const msgOf = (e: unknown) => (e instanceof ApiError ? e.message : '잘 안 됐어요. 다시 해 주세요')

/** 일기 동무 말풍선 (목업 .buddy). 화면 읽기 기능이 새 질문을 읽게 하는 aria-live 칸은 부르는 쪽에 늘 그려 둔다 */
function Buddy({ children }: { children: ReactNode }) {
  return (
    <div className="fd2-buddy">
      <span className="fam-av fam-tone-a" aria-hidden="true">
        <FamIcon name="sparkle" />
      </span>
      <div>
        <p className="fd2-buddy-name">일기 동무</p>
        <div className="fd2-bubble">{children}</div>
      </div>
    </div>
  )
}

export default function FDIARY_002() {
  const nav = useNavigate()
  // 하위 화면 틀이라 useFamily() 가 없다 → 지금 로그인한 사람을 직접 읽어 쓰기 시작한 사람과 같은지 본다 (FDIARY_001 리뷰 1번)
  const me = useFetch<UserOut>('/api/auth/me')
  const [text, setText] = useState(d.text)
  const [question, setQuestion] = useState(d.question)
  const [answer, setAnswer] = useState(d.answer)
  const [mood, setMood] = useState<Mood | null>(d.mood)
  const [busy, setBusy] = useState<'ask' | 'draft' | null>(null)
  const [error, setError] = useState('')
  // 화면을 떠나면(← · 다른 탭) 기다리던 질문·초안 요청을 멈춘다 (UPLOAD_002 와 같은 방법). 안 멈추면 늦게 온 초안이
  // 떠난 사람을 3단계로 끌고 가고, 늦게 온 질문이 새로 시작한 일기(또는 다음 계정)의 칸에 붙는다
  const leaving = useRef<AbortController | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    leaving.current = controller
    return () => controller.abort()
  }, [])

  if (me.error?.status === 401) return <Navigate to="/login" replace />
  // 1단계를 거치지 않았거나(주소로 바로 옴·새로고침) 다른 계정이 쓰던 것이면 처음부터 — FDIARY_001 이 [다음] 때 비운다
  if (!d.room || (me.data && d.userId !== me.data.user_id)) return <Navigate to="/fdiary" replace />
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
  if (!me.data) return <main className="st" aria-busy="true" />
  const roomId = d.room.room_id // 쓰기 시작할 때 보던 분 — 여러 방에 보내도 질문·초안은 이 방으로 한 번만 (routers/family_diary.py)

  /** 실패 처리 — 떠나서 멈춘 요청은 조용히 끝, 쓰는 사이 로그인이 풀렸으면(401) 로그인 화면으로(쓴 글은 메모리에 남음) */
  function fail(e: unknown, signal?: AbortSignal) {
    if (signal?.aborted) return
    if (e instanceof ApiError && e.status === 401) return nav('/login', { replace: true })
    setError(msgOf(e))
    setBusy(null)
  }

  async function ask() {
    if (busy || !text.trim()) return
    const signal = leaving.current?.signal
    setBusy('ask')
    setError('')
    try {
      const out = await api<FamilyAskOut>(`/api/rooms/${roomId}/family-diary/ask`, { body: { text }, signal })
      if (signal?.aborted) return
      setQuestion(out.question)
      d.question = out.question
      setBusy(null)
    } catch (e) {
      fail(e, signal)
    }
  }

  async function makeDraft() {
    if (busy || !text.trim() || !mood) return
    const signal = leaving.current?.signal
    setBusy('draft')
    setError('')
    try {
      const out = await api<FamilyDraftOut>(`/api/rooms/${roomId}/family-diary/draft`, {
        body: { text, question, answer },
        signal,
      })
      if (signal?.aborted) return
      d.draft = out.body
      nav('/fdiary/confirm') // 다음 화면으로 가니 busy 를 풀지 않는다 — 두 번 눌러도 한 번만
    } catch (e) {
      fail(e, signal)
    }
  }

  return (
    <main className="st">
      <div className="st-prog" aria-hidden="true">
        <i style={{ width: '66.6%' }} />
      </div>
      <div className="st-body">
        <div className="st-head">
          <p className="st-step">2/3 · 한마디</p>
          <h1>오늘 한 장</h1>
        </div>
        {d.photo && (
          <div className="fd2-mini">
            <Thumb file={d.photo} alt="고른 사진" />
          </div>
        )}

        <section className="fam-card fd2-form">
          {/* 글자 수는 이름(label) 밖에 둔다 — 안에 두면 칠 때마다 칸 이름이 바뀌어 화면 읽기 기능이 다시 읽는다 */}
          <div className="fd2-field">
            <label className="fd2-label" htmlFor="fd2-text">
              오늘 어떤 하루였어요?
            </label>
            <textarea
              id="fd2-text"
              className="fd2-input"
              rows={3}
              maxLength={MAX}
              value={text}
              placeholder="예: 엄마 생각하며 꽃 사진을 찍었어요"
              onChange={(e) => (setText(e.target.value), (d.text = e.target.value))}
            />
            <span className="fd2-count">
              {text.length}/{MAX}
            </span>
          </div>

          {/* 늘 그려 두는 aria-live 칸 — 안의 말풍선이 바뀌어야 화면 읽기 기능이 새 질문을 읽어 준다 */}
          <div aria-live="polite" className="fd2-live">
            {busy === 'ask' ? (
              <Buddy>
                <span className="fd2-dots" role="img" aria-label="질문을 생각하는 중">
                  <i />
                  <i />
                  <i />
                </span>
              </Buddy>
            ) : (
              question && <Buddy>{question}</Buddy>
            )}
          </div>
          {question && (
            <>
              <div className="fd2-field">
                <textarea
                  className="fd2-input"
                  rows={2}
                  maxLength={MAX}
                  value={answer}
                  aria-label="일기 동무 질문에 대한 답"
                  placeholder="답 (안 적어도 돼요)"
                  onChange={(e) => (setAnswer(e.target.value), (d.answer = e.target.value))}
                />
                <span className="fd2-count">
                  {answer.length}/{MAX}
                </span>
              </div>
              <div className="fd2-field" role="group" aria-labelledby="fd2-mood-label">
                <span className="fd2-label" id="fd2-mood-label">
                  오늘 기분
                </span>
                <div className="fd2-moods">
                  {MOODS.map((m) => (
                    <button
                      key={m}
                      type="button"
                      className={mood === m ? 'fd2-mood on' : 'fd2-mood'}
                      aria-pressed={mood === m}
                      onClick={() => (setMood(m), (d.mood = m))}
                    >
                      <MoodIcon mood={m} />
                      {MOOD_LABEL[m]}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </section>
        {error && (
          <p className="fam-error" role="alert">
            {error}
          </p>
        )}
      </div>

      <div className="st-cta">
        {question ? (
          <button
            type="button"
            className="fam-btn fam-btn--primary"
            disabled={!text.trim() || !mood || !!busy}
            onClick={makeDraft}
          >
            {busy === 'draft' ? '초안을 쓰는 중…' : '초안 만들기'}
          </button>
        ) : (
          <button type="button" className="fam-btn fam-btn--primary" disabled={!text.trim() || !!busy} onClick={ask}>
            {busy === 'ask' ? '질문을 생각하는 중…' : '다음'}
          </button>
        )}
      </div>
    </main>
  )
}
