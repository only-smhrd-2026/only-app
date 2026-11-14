/**
 * ELDER_FAMILY_001 — 아직 듣지 않은 가족 일기를 한 장씩 읽는다 (FR-FD-003·004, D53).
 * 가족이 내 일기에 보낸 하트·웃음·박수가 있으면 첫 장 '하트가 왔어요'로 먼저 알려 준다 (D63·D64).
 * 가족 일기마다 [좋아요] 하나 — 안 눌러도 넘어간다 (D54). 사진은 자르지 않고 ElderPhoto 로(누르면 크게, D60).
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { FamilyNewsOut, Heart } from '../../api/types'
import ElderPhoto from '../../components/ElderPhoto'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import { speak, stopSpeaking } from '../../lib/audio'

const KIND_WORD = { HEART: '하트', SMILE: '웃음', CLAP: '박수' } as const
const MAX_HEART_LINES = 4 // 한 화면(384×700)에 들어가는 줄 수

/** 받침이 있으면 앞의 조사, 없으면 뒤의 조사 — '큰딸이'·'손주가', '웃음을'·'하트를' */
function josa(word: string, withFinal: string, without: string) {
  const code = word.charCodeAt(word.length - 1)
  return code >= 0xac00 && code <= 0xd7a3 && (code - 0xac00) % 28 !== 0 ? withFinal : without
}

/** 받은 이모지 → 한 사람 한 줄. 줄이 넘치면 마지막 줄을 '다른 가족 N명도 보냈어요.'로 */
function heartLines(hearts: Heart[]): string[] {
  const byWho = new Map<string, string[]>()
  for (const heart of hearts) {
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

export default function ELDER_FAMILY_001() {
  const nav = useNavigate()
  const { home } = (useLocation().state ?? {}) as ElderNavState
  const speed = Number(home?.settings.tts_speed) || 0.85
  const { data, error, loading, reload } = useFetch<FamilyNewsOut>('/api/elder/family-news')
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
  const lines = hearts ? heartLines(hearts) : []
  const heartsText = lines.join(' ')
  const diary = hearts ? undefined : data?.diaries[index]
  const sender = [diary?.author_nickname, diary?.author_name].filter(Boolean).join(' ') || '가족'
  const isLiked = diary ? (liked[diary.diary_id] ?? diary.reactions.some((r) => r.by === 'ELDER')) : false
  // 사진이 없는 가족 일기는 '사진 일기'라고 읽지 않는다 (D64)
  const message = loading ? undefined : error
    ? error.code === 'DEVICE_REQUIRED' ? '가족이 보낸 연결 링크를 먼저 열어 주세요.' : error.message
    : hearts ? `하트가 왔어요. ${heartsText}`
      : diary ? `${sender}${josa(sender, '이', '가')} ${diary.illustration_url ? '사진 일기' : '일기'}를 보냈어요. 읽어 드릴게요. ${diary.body}`
        : data ? '오늘은 새 소식이 없어요.' : undefined

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
    void send(`/api/elder/diaries/${diary.diary_id}/read`, undefined, () => {
      // 목록을 다시 읽으면 읽은 일기가 빠져 번호가 밀린다. 받은 목록에서 번호만 바꾼다.
      if (index === data!.diaries.length - 1) nav('/elder', { replace: true })
      else setIndex((value) => value + 1)
    })
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
    <main className="elder elder--fit">
      {loading ? (
        <p className="elder-text" role="status">잠시만요…</p>
      ) : error ? (
        <>
          <p className="elder-text" role="alert">{message}</p>
          {error.code !== 'DEVICE_REQUIRED' && <button className="elder-btn" onClick={reload}>다시 보기</button>}
        </>
      ) : hearts ? (
        <>
          <p className="elder-text elder-text--lg elder-hearts-title">{heartIcon}하트가 왔어요</p>
          <button type="button" className={`elder-paper${saying ? ' elder-saying' : ''}`} onClick={() => replay(heartsText)}>
            <span>{lines.map((line) => <span key={line} className="elder-hearts-line">{line}</span>)}</span>
            {speaker}
          </button>
          {readError && <p className="elder-text" role="alert">{readError}</p>}
          <button className="elder-btn elder-bottom" disabled={busy} onClick={heardHearts}>
            {busy ? '잠시만요…' : data!.diaries.length ? '다음 소식' : '다 들었어요'}
          </button>
        </>
      ) : diary ? (
        <>
          <div className="elder-who"><span>{sender}</span><small>{index + 1} / {data!.diaries.length}</small></div>
          {diary.illustration_url && <ElderPhoto src={diary.illustration_url} alt="가족이 보낸 사진" />}
          <button type="button" className={`elder-paper${saying ? ' elder-saying' : ''}`} onClick={() => replay(diary.body)}>
            <span>{diary.body}</span>
            {speaker}
          </button>
          {readError && <p className="elder-text" role="alert">{readError}</p>}
          <div className="elder-two elder-bottom">
            <button type="button" className="elder-btn elder-btn--secondary elder-like" aria-pressed={isLiked} onClick={() => void toggleLike()}>
              {heartIcon}<span>{isLiked ? '보냈어요' : '좋아요'}</span>
            </button>
            <button className="elder-btn" disabled={busy} onClick={markRead}>
              {busy ? '잠시만요…' : index === data!.diaries.length - 1 ? '다 들었어요' : '다음 소식'}
            </button>
          </div>
        </>
      ) : data && (
        <>
          <p className="elder-text">오늘은 새 소식이 없어요.</p>
          <button className="elder-btn" onClick={() => nav('/elder', { replace: true })}>홈으로</button>
        </>
      )}
    </main>
  )
}
