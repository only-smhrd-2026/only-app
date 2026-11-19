/**
 * ELDER_FAMILY_001 — 아직 듣지 않은 가족 일기를 한 장씩 읽는다 (FR-FD-003·004, D53).
 * 가족이 내 일기에 보낸 하트·웃음·박수가 있으면 첫 장 '하트가 왔어요'로 먼저 알려 준다 (D63·D64).
 * 가족 일기마다 [좋아요] 하나 — 안 눌러도 넘어간다 (D54). 사진은 자르지 않고 ElderPhoto 로(누르면 크게, D60).
 * 가족이 내 일기에 남긴 한마디도 첫 장에서 "큰딸이 ‘…’래요."로 읽는다. 새 소식이 없으면 [지난 소식 다시 듣기] —
 * 들은 가족 일기 최근 5개를 같은 방식으로 다시 읽고, 읽음 표시는 바꾸지 않는다 (11/19).
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { FamilyNewsOut, Heart } from '../../api/types'
import ElderPhoto from '../../components/ElderPhoto'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import { speak, stopSpeaking } from '../../lib/audio'
import './ELDER_FAMILY_001.css'

const KIND_WORD = { HEART: '하트', SMILE: '웃음', CLAP: '박수' } as const
const MAX_HEART_LINES = 4 // 한 화면(384×700)에 들어가는 줄 수
// 새 소식이 없을 때. 들은 가족 일기가 있으면 둘째 문장과 [지난 소식 다시 듣기]를 같이 보이고 읽는다 (11/19)
const NO_NEWS = '오늘은 새 소식이 없어요.'
const AGAIN_GUIDE = '지난 소식 다시 듣기를 누르면 다시 읽어 드려요.'

/** 받침이 있으면 앞의 조사, 없으면 뒤의 조사 — '큰딸이'·'손주가', '웃음을'·'하트를' */
function josa(word: string, withFinal: string, without: string) {
  const code = word.charCodeAt(word.length - 1)
  return code >= 0xac00 && code <= 0xd7a3 && (code - 0xac00) % 28 !== 0 ? withFinal : without
}

/** 받은 이모지 → 한 사람 한 줄. 줄이 넘치면 마지막 줄을 '다른 가족 N명도 보냈어요.'로 */
function heartLines(hearts: Heart[]): string[] {
  const byWho = new Map<string, string[]>()
  for (const heart of hearts) {
    if (heart.kind === 'REPLY') continue // 한마디는 replyLines 가 따로 만든다
    const who = heart.name || '가족'
    const words = byWho.get(who) ?? []
    if (!words.includes(KIND_WORD[heart.kind])) words.push(KIND_WORD[heart.kind])
    byWho.set(who, words)
  }
  const lines = [...byWho].map(([who, words]) => {
    const what = words.map((w, i) => w + (i < words.length - 1 ? josa(w, '과', '와') : josa(w, '을', '를'))).join(' ')
    return `${who}${josa(who, '이', '가')} ${what} 보냈어요.`
  })
  if (lines.length <= MAX_HEART_LINES) return lines
  const shown = lines.slice(0, MAX_HEART_LINES - 1)
  return [...shown, `다른 가족 ${lines.length - shown.length}명도 보냈어요.`]
}

/** 받은 한마디 → 하나에 한 줄 "큰딸이 ‘엄마 김치 최고’래요." 받침은 글 끝의 느낌표·이모지를 건너뛰고 마지막 한글로 본다 */
function replyLines(hearts: Heart[]): string[] {
  return hearts.flatMap((heart) => {
    if (heart.kind !== 'REPLY' || !heart.text) return []
    const who = heart.name || '가족'
    const tail = heart.text.replace(/[^가-힣]+$/, '')
    return [`${who}${josa(who, '이', '가')} ‘${heart.text}’${josa(tail, '이래요', '래요')}.`]
  })
}

const speaker = (
  <svg className="elder-spk" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 9.5v5h3.2L12 18.5v-13L7.2 9.5z" />
    <path d="M15.5 9a4.2 4.2 0 0 1 0 6M18.3 6.3a8 8 0 0 1 0 11.4" />
  </svg>
)
const heartIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 20.5s-7.5-4.6-7.5-10.2a4.3 4.3 0 0 1 7.5-2.8 4.3 4.3 0 0 1 7.5 2.8c0 5.6-7.5 10.2-7.5 10.2z" />
  </svg>
)

/** 긴 가족 소식도 글자 크기를 유지하며 한 화면 안에서 쪽을 넘겨 읽는다. children 을 주면 body 대신 그것을 보인다(첫 장의 줄들). */
function FamilyPaper({ body, saying, onRead, children }: { body: string; saying: boolean; onRead: () => void; children?: ReactNode }) {
  const text = useRef<HTMLSpanElement>(null)
  const [page, setPage] = useState(0)
  const [count, setCount] = useState(1)

  useEffect(() => {
    const element = text.current
    if (!element) return
    const measure = () => {
      if (!element.clientWidth) return
      const pages = Math.max(1, Math.round(element.scrollWidth / element.clientWidth))
      setCount(pages)
      setPage((current) => Math.min(current, pages - 1))
    }
    const size = new ResizeObserver(measure)
    size.observe(element)
    const font = new MutationObserver(measure)
    font.observe(document.documentElement, { attributes: true, attributeFilter: ['data-font'] })
    void document.fonts.ready.then(measure)
    return () => {
      size.disconnect()
      font.disconnect()
    }
  }, [body])

  return (
    <div className="family-reading">
      <button type="button" className={`elder-paper family-paper${saying ? ' elder-saying' : ''}`} onClick={onRead}>
        <span className="family-paper-window">
          <span ref={text} className="family-paper-pages" style={{ transform: `translateX(-${page * 100}%)` }}>{children ?? body}</span>
        </span>
        {speaker}
      </button>
      {count > 1 && (
        <div className="family-pages" aria-label="가족 소식 글 넘기기">
          <button type="button" className="elder-chip" disabled={page === 0} onClick={() => setPage((current) => current - 1)}>이전 글</button>
          <span role="status" aria-label={`전체 ${count}쪽 중 ${page + 1}쪽`}>{page + 1} / {count}</span>
          <button type="button" className="elder-chip" disabled={page === count - 1} onClick={() => setPage((current) => current + 1)}>다음 글</button>
        </div>
      )}
    </div>
  )
}

export default function ELDER_FAMILY_001() {
  const nav = useNavigate()
  const { home } = (useLocation().state ?? {}) as ElderNavState
  const speed = Number(home?.settings.tts_speed) || 0.9
  const { data, error, loading, reload } = useFetch<FamilyNewsOut>('/api/elder/family-news')
  // 새 소식이 없을 때만 지난 소식(들은 가족 일기 최근 5개)을 받아 둔다 — 있으면 [지난 소식 다시 듣기]를 보인다
  const empty = !!data && !data.diaries.length && !data.hearts.length
  const past = useFetch<FamilyNewsOut>(empty ? '/api/elder/family-news?again=1' : null)
  const [again, setAgain] = useState(false)
  const live = useLive()
  const [index, setIndex] = useState(0)
  const [heartsHeard, setHeartsHeard] = useState(false)
  const [liked, setLiked] = useState<Record<number, boolean>>({}) // 이 화면에서 누른 [좋아요] — 받은 목록은 다시 읽지 않는다
  const [busy, setBusy] = useState(false)
  const [readError, setReadError] = useState<string>()
  const [saying, setSaying] = useState(false)
  const reading = useRef(false)
  const sayingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const hearts = !heartsHeard && data?.hearts.length ? data.hearts : undefined
  // 이모지 줄 다음에 한마디 줄. 같은 줄(같은 사람이 일기 두 편에 같은 한마디)은 한 번만 읽는다
  const lines = hearts ? [...new Set([...heartLines(hearts), ...replyLines(hearts)])] : []
  const heartsText = lines.join(' ')
  const heartsTitle = hearts?.every((heart) => heart.kind === 'REPLY') ? '한마디가 왔어요' : '하트가 왔어요'
  // 지난 소식을 받는 동안은 '새 소식이 없어요'를 읽지 않는다 — 받은 뒤 문장이 바뀌면 두 번 읽게 된다
  const waiting = loading || (empty && !past.data && !past.error)
  const canAgain = !!past.data?.diaries.length
  const news = again ? past.data : data
  const diary = hearts ? undefined : news?.diaries[index]
  const sender = [diary?.author_nickname, diary?.author_name].filter(Boolean).join(' ') || '가족'
  const isLiked = diary ? (liked[diary.diary_id] ?? diary.reactions.some((r) => r.by === 'ELDER')) : false
  // 사진이 없는 가족 일기는 '사진 일기'라고 읽지 않는다 (D64)
  const message = waiting ? undefined : error
    ? error.code === 'DEVICE_REQUIRED' ? '가족이 보낸 연결 링크를 먼저 열어 주세요.' : error.message
    : hearts ? `${heartsTitle}. ${heartsText}`
      : diary ? `${sender}${josa(sender, '이', '가')} ${diary.illustration_url ? '사진 일기' : '일기'}를 보냈어요. 읽어 드릴게요. ${diary.body}`
        : !data ? undefined
          : canAgain ? `${NO_NEWS} ${AGAIN_GUIDE}` : NO_NEWS

  useEffect(() => {
    if (message) void speak(message, speed)
    return () => stopSpeaking()
  }, [message, diary?.diary_id, speed])

  useEffect(() => () => clearTimeout(sayingTimer.current), [])

  function replay(text: string) {
    void speak(text, speed)
    setSaying(true)
    clearTimeout(sayingTimer.current)
    sayingTimer.current = setTimeout(() => setSaying(false), 1_400)
  }

  function fail(e: unknown) {
    const text = e instanceof ApiError ? e.message : '연결이 잠깐 끊겼어요. 다시 해 주세요.'
    setReadError(text)
    void speak(text, speed)
  }

  /** 서버에 적은 뒤에만 다음 장으로 넘어간다. 두 번 눌러도 한 번만 보낸다 */
  async function send(path: string, body: unknown, next: () => void) {
    if (reading.current) return
    reading.current = true
    setBusy(true)
    setReadError(undefined)
    try {
      await api(path, body === undefined ? { method: 'POST' } : { body })
      if (!live.current) return
      clearTimeout(sayingTimer.current)
      setSaying(false)
      next()
    } catch (e) {
      if (live.current) fail(e)
    } finally {
      reading.current = false
      if (live.current) setBusy(false)
    }
  }

  function heardHearts() {
    if (!hearts) return
    // 읽어 드린 마지막 하트까지만 '들음' — 그사이에 온 것은 다음에 읽어 드린다 (D63)
    void send('/api/elder/hearts/heard', { until: hearts[hearts.length - 1].at }, () => {
      if (data!.diaries.length) setHeartsHeard(true)
      else nav('/elder', { replace: true })
    })
  }

  function markRead() {
    if (!diary) return
    const next = () => {
      // 목록을 다시 읽으면 읽은 일기가 빠져 번호가 밀린다. 받은 목록에서 번호만 바꾼다.
      if (index === news!.diaries.length - 1) nav('/elder', { replace: true })
      else setIndex((value) => value + 1)
    }
    if (again) {
      // 다시 듣기는 읽음 표시를 바꾸지 않는다 — 서버에 적지 않고 넘긴다
      clearTimeout(sayingTimer.current)
      setSaying(false)
      next()
    } else void send(`/api/elder/diaries/${diary.diary_id}/read`, undefined, next)
  }

  async function toggleLike() {
    if (!diary) return
    const id = diary.diary_id
    const on = !isLiked
    setReadError(undefined)
    setLiked((map) => ({ ...map, [id]: on })) // 먼저 바꿔 보이고, 실패하면 되돌린다
    try {
      // on = '이 상태로 만들어 줘' — 같은 요청이 두 번 가도 결과가 같다
      await api(`/api/elder/diaries/${id}/like`, { body: { on } })
    } catch (e) {
      if (!live.current) return
      setLiked((map) => ({ ...map, [id]: !on }))
      fail(e)
    }
  }

  return (
    <main className="elder elder--fit elder-family">
      {waiting ? (
        <p className="elder-text" role="status">잠시만요…</p>
      ) : error ? (
        <>
          <p className="elder-text" role="alert">{message}</p>
          {error.code !== 'DEVICE_REQUIRED' && <button className="elder-btn" onClick={reload}>다시 보기</button>}
        </>
      ) : hearts ? (
        <>
          <p className="elder-text elder-text--lg elder-hearts-title">{heartIcon}{heartsTitle}</p>
          {/* 한마디가 여럿이면 한 화면을 넘는다 — 가족 일기 글과 같이 쪽을 넘겨 읽는다 */}
          <FamilyPaper body={heartsText} saying={saying} onRead={() => replay(heartsText)}>
            {lines.map((line) => <span key={line} className="elder-hearts-line">{line}</span>)}
          </FamilyPaper>
          {readError && <p className="elder-text" role="alert">{readError}</p>}
          <button className="elder-btn elder-bottom" disabled={busy} onClick={heardHearts}>
            {busy ? '잠시만요…' : data!.diaries.length ? '다음 소식' : '다 들었어요'}
          </button>
        </>
      ) : diary ? (
        <>
          <div className="elder-who"><span>{sender}</span><small>{index + 1} / {news!.diaries.length}</small></div>
          {diary.illustration_url && <ElderPhoto src={diary.illustration_url} alt="가족이 보낸 사진" />}
          <FamilyPaper key={diary.diary_id} body={diary.body} saying={saying} onRead={() => replay(diary.body)} />
          {readError && <p className="elder-text" role="alert">{readError}</p>}
          <div className="elder-two elder-bottom">
            <button type="button" className="elder-btn elder-btn--secondary elder-like" aria-pressed={isLiked} onClick={() => void toggleLike()}>
              {heartIcon}<span>{isLiked ? '보냈어요' : '좋아요'}</span>
            </button>
            <button className="elder-btn" disabled={busy} onClick={markRead}>
              {busy ? '잠시만요…' : index === news!.diaries.length - 1 ? '다 들었어요' : '다음 소식'}
            </button>
          </div>
        </>
      ) : data && (
        <>
          <p className="elder-text">{NO_NEWS}</p>
          {canAgain && <p className="elder-text">{AGAIN_GUIDE}</p>}
          {canAgain && <button className="elder-btn" onClick={() => setAgain(true)}>지난 소식 다시 듣기</button>}
          <button className={`elder-btn${canAgain ? ' elder-btn--secondary' : ''}`} onClick={() => nav('/elder', { replace: true })}>홈으로</button>
        </>
      )}
    </main>
  )
}
