/**
 * HOME_003 — 일기 달력 (11/25 사용자 — 인스타 스토리 보관함처럼, D104). 가족 홈 위 막대 [달력]에서 온다(하위 화면 틀의 ←).
 * 달력: 어르신 일기·가족 오늘 소식이 있는 날에 그날 사진(없으면 심심이)·2개 이상이면 수. 일기가 있는 가장 최근 달부터,
 * 아래 [N월 더 보기]로 일기가 있는 앞 달을 붙인다.
 * 날을 누르면(?day=YYYY-MM-DD) 그날 일기를 올린 시각 순서(아침 → 저녁)로 쭉 — 위 ‹ › 는 일기가 있는 전날·다음 날,
 * ← 는 달력으로. 카드를 누르면 일기 상세(HOME_002, 이모지·댓글·답장). 홈 피드는 그대로다.
 */
import { useState } from 'react'
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { MOOD_LABEL, type CalendarDayOut, type CalendarOut, type DiaryOut, type RoomOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import { Avatar } from '../../components/FamilyFrame'
import MoodIcon from '../../components/MoodIcon'
import Sim from '../../components/Sim'
import { useFetch } from '../../hooks/useFetch'
import './HOME_001.css' // 일기 카드(home-post)는 가족 홈과 같은 모양
import './HOME_003.css'

const WD = ['일', '월', '화', '수', '목', '금', '토']
const DAY = /^\d{4}-\d{2}-\d{2}$/
/** 한국 날짜 'YYYY-MM-DD' */
const kstDay = (iso: string) => new Date(iso).toLocaleDateString('en-CA', { timeZone: 'Asia/Seoul' })
const clock = (iso: string) => new Date(iso).toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul', hour: 'numeric', minute: '2-digit' })
const dayTitle = (d: string) =>
  new Date(`${d}T12:00:00+09:00`).toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', weekday: 'long' })
const iga = (word: string) => ((word.charCodeAt(word.length - 1) - 0xac00) % 28 ? '이' : '가')

export default function HOME_003() {
  const { roomId = '' } = useParams()
  const [params] = useSearchParams()
  const day = params.get('day')
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  if (rooms.error?.status === 401) return <Navigate to="/login" replace />
  const room = rooms.data?.find((r) => String(r.room_id) === roomId)
  const showDay = !!day && DAY.test(day)
  return (
    <main className="fam-stack cal">
      {/* 날을 봤다가 ← 로 돌아와도 붙여 둔 앞 달이 남게 달력은 숨기기만 한다 */}
      <Months roomId={roomId} hidden={showDay} />
      {showDay && <Day key={day} roomId={roomId} day={day} room={room} />}
    </main>
  )
}

function Months({ roomId, hidden }: { roomId: string; hidden: boolean }) {
  const nav = useNavigate()
  const first = useFetch<CalendarOut>(`/api/rooms/${encodeURIComponent(roomId)}/calendar`)
  const [older, setOlder] = useState<CalendarOut[]>([])
  const [busy, setBusy] = useState(false)
  const [moreError, setMoreError] = useState<string>()
  const shown = first.data ? [first.data, ...older] : []
  const prev = shown.at(-1)?.prev_month

  async function more() {
    if (!prev || busy) return
    setBusy(true)
    setMoreError(undefined)
    try {
      const out = await api<CalendarOut>(`/api/rooms/${encodeURIComponent(roomId)}/calendar?month=${prev}`)
      setOlder((list) => (list.some((m) => m.month === out.month) ? list : [...list, out]))
    } catch (e) {
      setMoreError(e instanceof ApiError ? e.message : '달력을 더 불러오지 못했어요')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="cal-months" hidden={hidden} aria-labelledby="cal-title">
      <h1 id="cal-title" className="cal-title">일기 달력</h1>
      {first.error ? (
        <>
          <p className="fam-error">{first.error.message}</p>
          <button type="button" className="fam-btn fam-btn--tonal" onClick={first.reload}>
            다시 시도
          </button>
        </>
      ) : !first.data ? (
        <p className="cal-sub" aria-busy="true">불러오는 중…</p>
      ) : !first.data.days.length ? (
        <section className="fam-card cal-empty">
          <Sim face="hello" size={72} />
          <p>아직 일기가 없어요</p>
        </section>
      ) : (
        <>
          {shown.map((m) => (
            <Month key={m.month} mo={m} onDay={(d) => nav(`?day=${d}`)} />
          ))}
          {moreError && <p className="fam-error">{moreError}</p>}
          {prev && (
            <button type="button" className="fam-btn fam-btn--tonal" disabled={busy} onClick={() => void more()}>
              {busy ? '불러오는 중…' : `${Number(prev.slice(5))}월 더 보기`}
            </button>
          )}
        </>
      )}
    </section>
  )
}

/** 한 달 — 일기 있는 날 = 그날 사진 칸(누름), 나머지는 날짜 글자만 */
function Month({ mo, onDay }: { mo: CalendarOut; onDay: (date: string) => void }) {
  const [y, m] = mo.month.split('-').map(Number)
  const lead = new Date(y, m - 1, 1).getDay()
  const days = new Date(y, m, 0).getDate()
  const [today] = useState(() => kstDay(new Date().toISOString()))
  const byDate = new Map(mo.days.map((d) => [d.date, d]))
  return (
    <section className="cal-month" aria-label={`${y}년 ${m}월`}>
      <h2>
        {y}년 {m}월
      </h2>
      <div className="cal-week" aria-hidden="true">
        {WD.map((w) => (
          <span key={w}>{w}</span>
        ))}
      </div>
      <div className="cal-grid">
        {Array.from({ length: lead }, (_, i) => (
          <span key={`b${i}`} />
        ))}
        {Array.from({ length: days }, (_, i) => {
          const date = `${mo.month}-${String(i + 1).padStart(2, '0')}`
          const d = byDate.get(date)
          if (!d) {
            return (
              <span key={date} className={`cal-cell${date === today ? ' today' : ''}${date > today ? ' fut' : ''}`}>
                {i + 1}
              </span>
            )
          }
          return (
            <button
              key={date}
              type="button"
              className={`cal-cell${d.thumb_url ? '' : ' sim'}`}
              onClick={() => onDay(date)}
              aria-label={`${m}월 ${i + 1}일 일기 ${d.count}개`}
            >
              {d.thumb_url ? <img src={d.thumb_url} alt="" loading="lazy" /> : <Sim face="smile" size={32} />}
              <span className="cal-num">{i + 1}</span>
              {d.count > 1 && <span className="cal-cnt">{d.count}</span>}
            </button>
          )
        })}
      </div>
    </section>
  )
}

/** 그날 일기를 올린 시각 순서로 — ‹ › 는 일기가 있는 전날·다음 날(주소만 바꿔 ← 는 달력으로) */
function Day({ roomId, day, room }: { roomId: string; day: string; room?: RoomOut }) {
  const nav = useNavigate()
  const out = useFetch<CalendarDayOut>(`/api/rooms/${encodeURIComponent(roomId)}/calendar/${day}`)
  const go = (d: string | null | undefined) => d && nav(`?day=${d}`, { replace: true })
  return (
    <section className="cal-day" aria-labelledby="cal-day-title">
      <div className="cal-dayh">
        <button type="button" className="fam-icon-btn cal-arr" disabled={!out.data?.prev_date} onClick={() => go(out.data?.prev_date)} aria-label="일기 있는 전날">
          ‹
        </button>
        <h1 id="cal-day-title">{dayTitle(day)}</h1>
        <button type="button" className="fam-icon-btn cal-arr" disabled={!out.data?.next_date} onClick={() => go(out.data?.next_date)} aria-label="일기 있는 다음 날">
          ›
        </button>
      </div>
      {out.error ? (
        <p className="fam-error">{out.error.message}</p>
      ) : !out.data ? (
        <p className="cal-sub" aria-busy="true">불러오는 중…</p>
      ) : !out.data.diaries.length ? (
        <p className="cal-sub">이날은 일기가 없어요</p>
      ) : (
        <>
          <p className="cal-sub">일기 {out.data.diaries.length}개 · 시간 순서</p>
          {out.data.diaries.map((d) => (
            <div key={d.diary_id} className="cal-tl">
              <span className="cal-time">{clock(d.posted_at)}</span>
              <DayCard d={d} room={room} />
            </div>
          ))}
        </>
      )}
    </section>
  )
}

/** 가족 홈 일기 카드와 같은 모양(사진·글 세 줄) — 누르면 일기 상세. 이모지 누르기는 상세에서 */
function DayCard({ d, room }: { d: DiaryOut; room?: RoomOut }) {
  const elder = d.author_type === 'ELDER'
  const hon = room?.elder_honorific ?? '어르신'
  const name = elder ? (room ? `${room.elder_name} ${room.elder_honorific}` : '어르신') : (d.author_name ?? '가족')
  const sub = elder ? '일기' : [d.author_nickname, '일기'].filter(Boolean).join(' · ')
  const emojis = d.reactions.filter((r) => r.by === 'FAMILY' && r.kind !== 'REPLY').length
  const replies = d.reactions.filter((r) => r.by === 'FAMILY' && r.kind === 'REPLY').length
  const elderReply = d.reactions.some((r) => r.by === 'ELDER' && r.kind === 'REPLY')
  const liked = d.reactions.some((r) => r.by === 'ELDER' && r.kind === 'LIKE')
  return (
    <article className="fam-card home-post">
      <Link className="home-post-link" to={`/diaries/${d.diary_id}`}>
        <header className="home-post-h">
          <Avatar name={elder ? (room?.elder_name ?? name) : name} src={elder ? room?.elder_photo_url : d.author_profile_url} />
          <div className="home-post-who">
            <b>{name}</b>
            <span className="fam-mini">{sub}</span>
          </div>
          <span className="home-post-mood">
            <MoodIcon mood={d.mood} />
            {MOOD_LABEL[d.mood]}
          </span>
        </header>
        {d.illustration_url && (
          <div className="home-post-photo">
            <img src={d.illustration_url} alt={d.illustration_type === 'AI_DRAWING' ? '그림일기 그림' : '일기 사진'} loading="lazy" />
            {d.illustration_type === 'AI_DRAWING' && (
              <span className="home-tag">
                <FamIcon name="sparkle" />
                그림일기
              </span>
            )}
          </div>
        )}
        <p className="home-post-text">
          <span className="home-clamp">{d.body}</span>
        </p>
      </Link>
      <footer className="home-post-f">
        {elder ? (
          <span className="fam-mini">{[emojis && `이모지 ${emojis}`, replies && `댓글 ${replies}`].filter(Boolean).join(' · ') || '아직 반응이 없어요'}</span>
        ) : d.read_by_elder ? (
          <p className="home-heard">
            <FamIcon name="check" />
            {hon}
            {iga(hon)} 들으셨어요{elderReply ? ' · 말로 답하셨어요' : liked ? ' · 좋아요를 보내셨어요' : ''}
          </p>
        ) : (
          <p className="fam-mini">아직 안 들으셨어요</p>
        )}
      </footer>
    </article>
  )
}
