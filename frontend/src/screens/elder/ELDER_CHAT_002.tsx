/**
 * ELDER_CHAT_002 — 지난 이야기 (D106). 잡담(ELDER_CHAT_001) 오른쪽 위 [지난 이야기]에서 온다.
 * /elder/chat/past = 최근 30일 잡담 목록(최신 순, 제목은 심심이가 붙임) — 이 목록만 스크롤한다(지난 일기와 같음, D60).
 * /elder/chat/past/:sessionId = 그날 나눈 말 + [이 이야기 이어서 하기] → 새 잡담이 그 이야기로 시작한다(resume_of).
 *   지금(30분 안) 하던 잡담이면 새로 열지 않고 그 잡담으로 돌아간다 (D107).
 * 폰의 뒤로 키·위 [뒤로]는 한 단계씩 돌아간다(주소가 둘이라).
 */
import { useEffect } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import type { ChatItemOut, ElderHomeOut, SessionGetOut } from '../../api/types'
import { ElderStop } from '../../components/ElderUi'
import Sim from '../../components/Sim'
import { useFetch } from '../../hooks/useFetch'
import { speak, stopSpeaking } from '../../lib/audio'
import { readChat } from '../../lib/pausedSession'
import type { ChatNavState } from './ELDER_CHAT_001'
import './ELDER_CHAT.css'

const GUIDE = '지난 이야기예요. 보고 싶은 이야기를 눌러 주세요.'
const EMPTY = '아직 심심이랑 나눈 이야기가 없어요.'
type PastState = { home?: ElderHomeOut; item?: ChatItemOut }

const KST = { timeZone: 'Asia/Seoul' } as const
const dayOf = (iso: string) => new Date(iso).toLocaleDateString('ko-KR', { ...KST, month: 'long', day: 'numeric', weekday: 'long' })
const timeOf = (iso: string) => new Date(iso).toLocaleTimeString('ko-KR', { ...KST, hour: 'numeric', minute: '2-digit' })

export default function ELDER_CHAT_002() {
  const { sessionId } = useParams()
  return sessionId ? <View sessionId={sessionId} /> : <List />
}

function List() {
  const nav = useNavigate()
  const { home } = (useLocation().state ?? {}) as PastState
  const speed = Number(home?.settings.tts_speed) || 0.9
  const { data, error, loading, reload } = useFetch<ChatItemOut[]>('/api/elder/sessions?kind=CHAT')

  useEffect(() => {
    if (data) void speak(data.length ? GUIDE : EMPTY, speed)
    return () => stopSpeaking()
  }, [data, speed])

  return (
    <main className="elder echat-list">
      <h1>지난 이야기</h1>
      {loading ? (
        <p className="elder-text" role="status">
          잠시만요…
        </p>
      ) : error ? (
        <ElderStop text={error.message} onRetry={reload} />
      ) : !data?.length ? (
        <p className="elder-sub">{EMPTY}</p>
      ) : (
        <>
          <p className="elder-sub">보고 싶은 이야기를 눌러 주세요.</p>
          <div className="elder-col echat-items">
            {data.map((c) => (
              <button
                key={c.session_id}
                type="button"
                className="elder-btn elder-btn--secondary echat-item"
                onClick={() => nav(`/elder/chat/past/${c.session_id}`, { state: { home, item: c } })}
              >
                <Sim face="smile" size={56} />
                <span>
                  {c.title}
                  <small>
                    {dayOf(c.started_at)} · {timeOf(c.started_at)}
                  </small>
                </span>
              </button>
            ))}
          </div>
        </>
      )}
    </main>
  )
}

function View({ sessionId }: { sessionId: string }) {
  const nav = useNavigate()
  const { home, item } = (useLocation().state ?? {}) as PastState
  const { data, error, loading, reload } = useFetch<SessionGetOut>(`/api/elder/sessions/${sessionId}`)
  const day = item ? dayOf(item.started_at) : undefined

  function resume() {
    if (!data) return
    if (readChat()?.id === sessionId) return nav('/elder/chat', { state: { home } }) // 지금 하던 잡담 — 그대로 잇는다
    const state: ChatNavState = { home, resumeOf: sessionId, earlier: data.turns, earlierLabel: day ? `${day} 이야기` : '지난 이야기' }
    nav('/elder/chat', { state })
  }

  if (loading)
    return (
      <main className="elder elder--fit elder-center">
        <p className="elder-text" role="status">
          잠시만요…
        </p>
      </main>
    )
  if (error || !data)
    return (
      <main className="elder elder--fit elder-center">
        <ElderStop text={error?.message} onRetry={reload} />
      </main>
    )
  return (
    <main className="elder elder--fit echat-view">
      <h1 className="elder-text elder-text--lg">{item?.title ?? '지난 이야기'}</h1>
      {day && <p className="elder-sub">{day}</p>}
      <div className="echat-log">
        {data.turns.map((t, i) => (
          <p key={i} className={`echat-bub echat-bub--${t.speaker === 'AI' ? 'ai' : 'me'}`}>
            {t.text}
          </p>
        ))}
      </div>
      <button type="button" className="elder-btn" onClick={resume}>
        이 이야기 이어서 하기
      </button>
    </main>
  )
}
