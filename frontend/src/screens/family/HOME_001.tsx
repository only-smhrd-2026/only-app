/**
 * HOME_001 — 가족 홈 (D70, 11/23 시안 f-home '소식 먼저'). 공통 틀(FamilyFrame) 안에서 지금 보는 어르신 한 분의 소식:
 * 급한 알림 → 한 줄 요약 카드(누르면 7일 칸·돌봄 일지, 오른쪽 전화) → 글쓴이 필터 → 날짜별 일기 카드(첫 일기 바로 아래 주간 띠).
 * 폰 연결 전이고 아직 아무 소식이 없으면 '폰을 연결해 주세요' 3단계(링크 보내기 → 폰에서 열기 → 홈 화면에 추가).
 * 실시간 반영은 없다 — 홈을 열 때·앱으로 돌아올 때 읽는다(D36). 회상 대화 원문은 여기 없다(R18) — 11/27 부터 AI 가 만든
 * 가족용 한두 줄 요약만 회상 카드로 섞인다. 피드는 최근 7일만, 그보다 예전은 일기 달력(HOME_003)에서.
 */
import { Fragment, useEffect, useRef, useState, useSyncExternalStore, type MouseEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import {
  MOOD_LABEL,
  type DiaryListOut,
  type DiaryOut,
  type InviteCreatedOut,
  type InviteKind,
  type MemoryCardOut,
  type MemoryListOut,
  type MoodWeekOut,
  type Reaction,
  type RoomOut,
  type UserOut,
  type WeeklyOut,
} from '../../api/types'
import FamIcon from '../../components/FamIcon'
import CareCard from '../../components/CareCard'
import { Avatar } from '../../components/FamilyFrame'
import MoodIcon from '../../components/MoodIcon'
import Sim from '../../components/Sim'
import UrgentCard from '../../components/UrgentCard'
import { useFamily } from '../../hooks/useFamily'
import { useFetch } from '../../hooks/useFetch'
import { getInstallState, promptInstall, subscribeInstallPrompt } from '../../lib/installPrompt'
import { logout } from '../../lib/logout'
import { weeklySeen } from '../../lib/weeklySeen'
import './HOME_001.css'

// 마음 체크 결과 (D56): 점수 없이 3단계 문장만. 많이 힘드신 단계는 상담을 권한다
const CHECK_TEXT = {
  USUAL: '평소와 비슷해요',
  DOWN: '조금 가라앉으신 편이에요',
  HARD: '많이 힘드신 것 같아요 · 전문 상담을 권해 드려요',
} as const
// 그 밖의 체크 이름 (11/23 사용자 — 결과만 보인다)
const OTHER_NAME = { UCLA3: '외로움 체크', GAD7: '걱정 체크', SMCQ: '기억력 체크', MEMGAME: '기억력 놀이' } as const
const WEEK_NO = ['첫째', '둘째', '셋째', '넷째', '다섯째']
const PHOTOS_FOR_LINK = 3 // 서버 ELDER_DEVICE_MIN_PHOTOS — 사진 3장이 있어야 폰 연결 링크를 준다

// 'YYYY-MM-DD' 뒤에 T00:00:00 을 붙여야 날짜가 하루 밀리지 않는다
const day = (ymd: string) => new Date(ymd + 'T00:00:00')
const monthDay = (d: Date) => d.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' }) // 11월 14일 (토)
const clock = (iso: string) => new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
// 받침이 있으면 '이', 없으면 '가' — 할머니가 / 어머님이
const iga = (w: string) => ((w.charCodeAt(w.length - 1) - 0xac00) % 28 ? '이' : '가')

function dayLabel(d: Date) {
  const today = new Date()
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return '오늘'
  if (d.toDateString() === yesterday.toDateString()) return `어제 · ${monthDay(d)}`
  return monthDay(d)
}

/** 마지막 대화 — '오늘 오전 9:24' · '어제 오후 3:05' · '11월 14일 오전 9:12' */
function talkLabel(iso: string) {
  const d = new Date(iso)
  const time = d.toLocaleTimeString('ko-KR', { hour: 'numeric', minute: '2-digit' })
  const label = dayLabel(d)
  return `${label === '오늘' ? '오늘' : label.startsWith('어제') ? '어제' : d.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' })} ${time}`
}

const INSTALL_LATER_KEY = 'haru.fam.install-later'

/** 가족 폰 설치 안내 — 설치 가능한 크롬과 아이폰에서만 보여 준다. */
function InstallCard() {
  const state = useSyncExternalStore(subscribeInstallPrompt, getInstallState)
  const [later, setLater] = useState(() => {
    try {
      return localStorage.getItem(INSTALL_LATER_KEY) !== null
    } catch {
      return false
    }
  })
  const [busy, setBusy] = useState(false)
  const iphone = /iPhone/i.test(navigator.userAgent)
  // 아이폰 안내는 브라우저마다 다르다 — 카톡·네이버 같은 앱 안 브라우저는 '홈 화면에 추가'가 없고(초대 링크가 카톡으로 와서 흔함),
  // 아이폰 크롬·파이어폭스는 공유 버튼이 주소창 오른쪽에 있다
  const guide = /KAKAOTALK|NAVER|Line\/|Instagram|FBAN|FBAV/i.test(navigator.userAgent)
    ? 'Safari 로 열어 주세요(⋯ → 다른 브라우저로 열기) → 아래 공유 버튼 → 홈 화면에 추가'
    : /CriOS|FxiOS|EdgiOS/.test(navigator.userAgent)
      ? '주소창 오른쪽 공유 버튼 → 홈 화면에 추가'
      : '아래 공유 버튼 → 홈 화면에 추가'

  function dismiss() {
    try {
      localStorage.setItem(INSTALL_LATER_KEY, '1')
    } catch {
      /* 저장을 막은 폰에서도 지금 열린 안내는 닫는다. */
    }
    setLater(true)
  }

  async function install() {
    if (busy) return
    setBusy(true)
    try {
      await promptInstall()
    } catch {
      /* 브라우저가 창을 열지 못하면 기본 설치 메뉴로도 설치할 수 있다. */
    } finally {
      setBusy(false)
    }
  }

  if (later || state === 'installed' || (state !== 'available' && !iphone)) return null
  return (
    <section className="fam-card home-install" aria-label="앱 설치 안내">
      <p>폰 홈 화면에 하루한장 아이콘을 만들면 앱처럼 바로 열려요</p>
      {state !== 'available' && <p className="home-install-guide">{guide}</p>}
      <div className="home-install-actions">
        {state === 'available' && (
          <button type="button" className="fam-btn fam-btn--primary fam-btn--sm" onClick={install} disabled={busy}>
            앱으로 설치
          </button>
        )}
        <button type="button" className="fam-text-btn" onClick={dismiss}>다음에</button>
      </div>
    </section>
  )
}

/**
 * 요약 카드 (11/23 시안 — D67②·D85 를 접어 둠, 11/27 팀 회의로 크게): 접힌 상태에서도 한눈에 —
 * 마지막 이야기 시각 · 이번 주 며칠 · 월~일 점 줄 · 마지막 마음 체크 한 줄 · 오른쪽 전화.
 * 카드 어디를 눌러도 펼치고 접는다(11/27 — 전화·링크는 제 일). 펼치면 안부 전화 권유 · 다른 체크 결과 · 요즘 안부(CareCard).
 * 진단 말·점수는 쓰지 않는다(NFR-DE-003)
 */
function SummaryCard({ room, week, notes }: { room: RoomOut; week: MoodWeekOut; notes: string[] }) {
  const [open, setOpen] = useState(false)
  const check = week.last_check
  const who = `${room.elder_name} ${room.elder_honorific}`
  const md = (ymd: string) => `${day(ymd).getMonth() + 1}/${day(ymd).getDate()}`
  const days = thisWeek(week)
  const talked = days.filter((d) => d.talked).length
  const low = days.filter((d) => d.low).length
  // 버튼·링크·펼친 안쪽 카드(CareCard 등)를 누른 건 그쪽 일 — 카드 바탕을 누를 때만 펼치고 접는다
  const toggle = (e: MouseEvent<HTMLElement>) => {
    if (!(e.target as HTMLElement).closest('a, button, input, .home-sum-more')) setOpen((o) => !o)
  }
  return (
    <section className="fam-card home-sum" aria-label={`${who} 요즘`} onClick={toggle}>
      <div className="home-sum-row">
        <div className="home-strip">
          <b>{week.last_talk_at ? `${talkLabel(week.last_talk_at)}에 이야기하셨어요` : '아직 이야기를 나누지 않으셨어요'}</b>
          <span className="home-sum-sub">
            이번 주 <strong>{talked}일</strong> 이야기하셨어요
            {low ? ` · 기운 없어 보인 날 ${low}일` : ''}
          </span>
        </div>
        {/* 번호 없이 전화 앱만 연다 — 어르신 번호는 저장하지 않는다(D57) */}
        <a className="home-call" href="tel:" aria-label={`${who}께 전화 걸기`}>
          <FamIcon name="phone" />
        </a>
      </div>
      <ol className="home-week" aria-label="이번 주 (월~일)">
        {days.map((d) => {
          const s = d.future ? 'later' : d.low ? 'low' : d.talked ? 'on' : 'off'
          return (
            <li key={d.date} className={d.today ? 'today' : undefined}>
              <Dot s={s} />
              <span>{d.today ? '오늘' : day(d.date).toLocaleDateString('ko-KR', { weekday: 'short' })}</span>
              <span className="home-sr">{WORD[s]}</span>
            </li>
          )
        })}
      </ol>
      {check && (
        <p className="home-check">
          <FamIcon name="heart" />
          <span>
            <b>마음</b> · {CHECK_TEXT[check.level]} <small>{md(check.check_date)}</small>
          </span>
        </p>
      )}
      <button type="button" className="home-more" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {open ? '접기' : '자세히 보기'}
        <FamIcon name="chevDown" />
      </button>
      {open && (
        <>
          {notes.map((line) => (
            <a key={line} className="home-callnote" href="tel:">
              <FamIcon name="phone" />
              <span>
                {line} <u>전화하기</u>
              </span>
            </a>
          ))}
          <p className="fam-mini home-legend">
            {(['on', 'low', 'off'] as const).map((s) => (
              <span key={s}>
                <Dot s={s} />
                {WORD[s]}
              </span>
            ))}
          </p>
          {week.other_checks.length > 0 && (
            <ul className="home-others">
              {week.other_checks.map((o) => (
                <li key={o.kind}>
                  <span aria-hidden="true">{o.face}</span>
                  <span>
                    <b>{OTHER_NAME[o.kind]}</b> · {o.title} <small>{md(o.check_date)}</small>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <div className="home-sum-more">
            <CareCard roomId={room.room_id} />
          </div>
          {/* 마음 알림 안내 (D55 — 처리방침 확정 11/17). 11/27 짧게 */}
          <p className="fam-mini">
            진단이 아니에요 · 위급한 말씀은 가족 모두에게 알려요 · <Link to="/policy#mood">자세히 ›</Link>
          </p>
        </>
      )}
    </section>
  )
}

/**
 * 이번 주 월~일 (11/27 — 매일 한 칸씩 밀리던 '최근 7일' 대신 고정). 서버는 오늘까지 최근 7일을 주는데,
 * 이번 주 월요일은 늘 그 안에 있다 → 월요일~오늘은 서버 칸, 내일~일요일은 아직 오지 않은 빈칸.
 */
function thisWeek(week: MoodWeekOut) {
  const last = week.days[week.days.length - 1]
  const today = day(last.date)
  const monday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - ((today.getDay() + 6) % 7))
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + i)
    const ymd = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    const got = week.days.find((x) => x.date === ymd)
    return { date: ymd, talked: !!got?.talked, low: !!got?.low, future: d > today, today: ymd === last.date }
  })
}

// 기운 없어 보인 날도 이야기한 날이라 ✓ 위에 작은 표시를 더한다 (11/27 — '이야기한 날'과 겹치지 않게)
const WORD = { on: '이야기했어요', low: '기운 없어 보였어요', off: '이야기 없음', later: '아직 안 온 날' } as const
function Dot({ s }: { s: keyof typeof WORD }) {
  return (
    <span className={`home-dot ${s}`} aria-hidden="true">
      {(s === 'on' || s === 'low') && <FamIcon name="check" />}
      {s === 'low' && <i />}
    </span>
  )
}

/** '○월 ○째 주 이야기가 도착했어요' 띠 — 그 주를 주간 이야기 화면에서 열어 보기 전까지만 (lib/weeklySeen) */
function WeeklyBanner({ room, data }: { room: RoomOut; data: WeeklyOut | null }) {
  const nav = useNavigate()
  if (!data || weeklySeen(room.room_id) === data.week_start) return null
  const d = day(data.week_start)
  const cards = data.qa_list.length
  return (
    <button type="button" className="fam-card home-banner" onClick={() => nav(`/weekly/${room.room_id}`)}>
      <span className="home-sq">
        <FamIcon name="calendar" />
      </span>
      <span className="home-banner-txt">
        <b>
          {d.getMonth() + 1}월 {WEEK_NO[Math.floor((d.getDate() - 1) / 7)]} 주 이야기가 도착했어요
        </b>
        <span className="fam-mini">
          {cards ? `이야기 카드 ${cards}장 · ` : ''}이야기한 날 {data.memory_days}일
        </span>
      </span>
      <FamIcon name="chevRight" />
    </button>
  )
}

// 좋아요·댓글 (11/27 팀 회의 '인스타처럼'): 이모지 3개 → ♡ 하나. 예전 웃음·박수 칸도 좋아요로 센다
const likeCount = (rs: Reaction[]) => rs.filter((r) => r.by === 'FAMILY' && r.kind !== 'REPLY').length
const myLike = (rs: Reaction[], me: number) => rs.find((r) => r.by === 'FAMILY' && r.kind !== 'REPLY' && r.user_id === me)?.kind
// 댓글(한마디·목소리 답장·어르신 답) — 목소리 답장은 자막이 비어도 (D99)
const replyCount = (rs: Reaction[]) => rs.filter((r) => r.kind === 'REPLY' && (r.text || r.audio_url)).length

/** 💬 n — 누르면 상세 화면의 댓글 쓰기 칸으로 (11/27: 카드 아래 댓글 미리보기는 빼고 개수만) */
function CommentLink({ to, n }: { to: string; n: number }) {
  return (
    <Link className="home-like" to={to} state={{ familyDiaryOrder: true, reply: true }} aria-label={n ? `댓글 ${n}개 보기` : '댓글 달기'}>
      <FamIcon name="chat" />
      {n > 0 && <span className="home-like-n">{n}</span>}
    </Link>
  )
}

/** ♡ n · 💬 n — 일기·회상 카드가 같이 쓴다 (11/27 '하트 2 댓글 3' 처럼 개수만) */
function LikeBar({ liked, count, busy, onLike, to, replies }: {
  liked: boolean
  count: number
  busy: boolean
  onLike: () => void
  to: string
  replies: number
}) {
  return (
    <div className="home-likes">
      <button type="button" className="home-like" onClick={onLike} disabled={busy} aria-pressed={liked} aria-label={liked ? `좋아요 취소, 좋아요 ${count}개` : `좋아요, 좋아요 ${count}개`}>
        <FamIcon name="heart" />
        {count > 0 && <span className="home-like-n">{count}</span>}
      </button>
      <CommentLink to={to} n={replies} />
    </div>
  )
}

/** 일기 카드 — 큰 사진(자르지 않음, 11/14 사용자) · 글 세 줄. 누르면 일기 상세로 간다 */
function Post({ d, room, me, onChange }: { d: DiaryOut; room: RoomOut; me: UserOut; onChange: (d: DiaryOut) => void }) {
  const [busy, setBusy] = useState(false)
  const elder = d.author_type === 'ELDER'
  const name = elder ? `${room.elder_name} ${room.elder_honorific}` : (d.author_name ?? '가족')
  const sub = elder ? `${clock(d.posted_at)} · 일기` : [d.author_nickname, clock(d.posted_at), '일기'].filter(Boolean).join(' · ')
  const mine = myLike(d.reactions, me.user_id)
  const liked = d.reactions.some((r) => r.by === 'ELDER' && r.kind === 'LIKE')
  const elderReply = d.reactions.some((r) => r.by === 'ELDER' && r.kind === 'REPLY')
  const to = `/diaries/${d.diary_id}`

  // ♡ (D54 API 그대로): 켜져 있던 내 칸(예전 웃음·박수 포함)을 끄거나 하트를 켠다 — on = '이 상태로 만들어 줘'
  async function like() {
    setBusy(true)
    try {
      onChange(await api<DiaryOut>(`/api/diaries/${d.diary_id}/reaction`, { body: { kind: mine ?? 'HEART', on: !mine } }))
    } catch {
      /* 실패하면 그대로 둔다 — 다시 누르면 된다 */
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="fam-card home-post">
      <Link className="home-post-link" to={to} state={{ familyDiaryOrder: true }}>
        <header className="home-post-h">
          <Avatar name={elder ? room.elder_name : name} src={elder ? room.elder_photo_url : null} />
          <div className="home-post-who">
            <b>
              {name}
              {!d.read_by_me && <i className="fam-tag">새 일기</i>}
            </b>
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
          <LikeBar liked={!!mine} count={likeCount(d.reactions)} busy={busy} onLike={like} to={to} replies={replyCount(d.reactions)} />
        ) : (
          <>
            {d.read_by_elder ? (
              <p className="home-heard">
                <FamIcon name="check" />
                {room.elder_honorific}
                {iga(room.elder_honorific)} 들으셨어요
                {elderReply ? ' · 말로 답하셨어요' : liked ? ' · 좋아요를 보내셨어요' : ''}
              </p>
            ) : (
              <p className="fam-mini">아직 안 들으셨어요</p>
            )}
            {(!d.is_mine || replyCount(d.reactions) > 0) && (
              <span className="home-f-end">
                <CommentLink to={to} n={replyCount(d.reactions)} />
              </span>
            )}
          </>
        )}
      </footer>
    </article>
  )
}

/**
 * 회상 카드 (11/27 팀 회의 — 회상도 가족 홈에): 사진 · AI 가 만든 가족용 한두 줄 요약(대화 원문은 보이지 않는다) · ♡ · 💬.
 * 누르거나 💬 → 회상 상세(MEMORY_001) — 일기처럼 새 화면에서 댓글 (11/27 가족화면 설정 개선안)
 */
function MemoryPost({ m, room, me, onChange }: { m: MemoryCardOut; room: RoomOut; me: UserOut; onChange: (m: MemoryCardOut) => void }) {
  const [busy, setBusy] = useState(false)
  const mine = myLike(m.reactions, me.user_id)
  const who = `${room.elder_name} ${room.elder_honorific}`
  const to = `/memories/${m.session_id}`

  async function like() {
    setBusy(true)
    try {
      onChange(await api<MemoryCardOut>(`/api/memories/${m.session_id}/reaction`, { body: { kind: 'HEART', on: !mine } }))
    } catch {
      /* 실패하면 그대로 둔다 — 다시 누르면 된다 */
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="fam-card home-post">
      <Link className="home-post-link" to={to}>
        <header className="home-post-h">
          <Avatar name={room.elder_name} src={room.elder_photo_url} />
          <div className="home-post-who">
            <b>{who}</b>
            <span className="fam-mini">{clock(m.ended_at)} · 회상</span>
          </div>
        </header>
        {m.photo_url && (
          <div className="home-post-photo">
            <img src={m.photo_url} alt="이야기 나눈 사진" loading="lazy" />
            <span className="home-tag">
              <FamIcon name="chat" />
              사진 보며 이야기
            </span>
          </div>
        )}
        <p className="home-post-text">{m.summary}</p>
      </Link>
      <footer className="home-post-f">
        <LikeBar liked={!!mine} count={likeCount(m.reactions)} busy={busy} onLike={like} to={to} replies={replyCount(m.reactions)} />
      </footer>
    </article>
  )
}

function Empty({ room }: { room: RoomOut }) {
  return (
    <div className="home-empty">
      <Sim face="smile" size={96} />
      <b>아직 소식이 없어요</b>
      <p>{room.elder_honorific} 일기와 가족이 쓴 일기가 여기에 모여요</p>
    </div>
  )
}

/** 링크 만들고 폰 공유 창으로 보내기 — 공유 창이 없으면 복사, 둘 다 안 되면 주소를 보여 준다 */
function useShareLink(room: RoomOut) {
  const [link, setLink] = useState<{ kind: InviteKind; url: string; sent: boolean }>()
  const [note, setNote] = useState<string>()
  const [busy, setBusy] = useState<InviteKind>()
  async function share(kind: InviteKind) {
    setBusy(kind)
    setNote(undefined)
    try {
      const created = await api<InviteCreatedOut>(`/api/rooms/${room.room_id}/invites`, { body: { kind } })
      const text =
        kind === 'ELDER_DEVICE'
          ? `${room.elder_honorific} 폰에서 이 링크를 열어 주세요 — 하루한장`
          : `${room.elder_name} ${room.elder_honorific}네 가족방에 초대해요 — 하루한장`
      let sent = false
      if (navigator.share) {
        sent = await navigator.share({ text, url: created.url }).then(
          () => true,
          () => false,
        )
      } else if (navigator.clipboard) {
        sent = await navigator.clipboard.writeText(created.url).then(
          () => true,
          () => false,
        )
        if (sent) setNote('링크를 복사했어요 · 붙여 넣어 보내 주세요')
      }
      setLink({ kind, url: created.url, sent })
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : '링크를 만들지 못했어요. 다시 해 주세요')
    } finally {
      setBusy(undefined)
    }
  }
  return { link, note, busy, share }
}

/**
 * 폰 연결 전 가족방 (11/23 시안 homeEmpty): 연결 링크 보내기 → 폰에서 열기 → 홈 화면에 추가.
 * 서버는 사진이 3장 이상이어야 기기 링크를 준다 → 3장 전이면 '사진 올리기' 띠를 먼저, 이유를 한 줄로.
 */
function StartHome({ room, reloadRooms }: { room: RoomOut; reloadRooms: () => void }) {
  const nav = useNavigate()
  const { link, note, busy, share } = useShareLink(room)
  const hon = room.elder_honorific
  const photos = room.photo_count
  const ready = photos >= PHOTOS_FOR_LINK

  // 사진첩에서 사진을 올리고 돌아오면 사진 수가 바뀌어 있다 → 이 화면이 뜰 때마다 가족방을 다시 읽는다
  useEffect(() => {
    reloadRooms()
  }, [reloadRooms])

  const upload = (
    <button type="button" className={ready ? 'fam-card home-banner plain' : 'fam-card home-banner'} onClick={() => nav('/upload')}>
      <span className="home-sq">
        <FamIcon name="image" />
      </span>
      <span className="home-banner-txt">
        <b>{ready ? '추억 사진 먼저 올려 두기' : `추억 사진 ${PHOTOS_FOR_LINK}장 올리기`}</b>
        <span className="fam-mini">
          {ready
            ? '연결하자마자 사진 보며 이야기할 수 있어요'
            : `사진이 ${PHOTOS_FOR_LINK}장 있어야 ${hon} 폰을 연결할 수 있어요 · 지금 ${photos}장`}
        </span>
      </span>
      <FamIcon name="chevRight" />
    </button>
  )
  const sentDevice = link?.kind === 'ELDER_DEVICE' ? link : undefined
  return (
    <main className="fam-stack">
      <InstallCard />
      {!ready && upload}
      <section className="fam-card home-connect">
        <div className="home-connect-h">
          <span className="fam-av fam-tone-a" aria-hidden="true">
            <Sim face="hello" size={40} />
          </span>
          <div>
            <b>
              {room.elder_name} {hon} 폰을 연결해 주세요
            </b>
            <p className="fam-mini">연결하면 오늘의 한 장과 가족 소식이 {hon} 폰으로 가요</p>
          </div>
        </div>
        <ol className="home-steps3">
          <li>
            <b>연결 링크 보내기</b>
            <span className="fam-mini">카카오톡으로 {hon}께 보내요</span>
          </li>
          <li>
            <b>{hon} 폰에서 링크 열기</b>
            <span className="fam-mini">[시작하기] → 마이크 '허용' · 곁에 계시면 같이 눌러 드려요</span>
          </li>
          <li>
            <b>홈 화면에 추가</b>
            <span className="fam-mini">크롬 메뉴 ⋮ → 홈 화면에 추가 · 다음부터 아이콘 하나로 열려요</span>
          </li>
        </ol>
        {!ready ? (
          <p className="home-lock">
            <FamIcon name="lock" />
            추억 사진을 {PHOTOS_FOR_LINK}장 올리면 연결 링크를 보낼 수 있어요
          </p>
        ) : !room.is_owner ? (
          <p className="fam-mini">방장이 연결 링크를 보내면 연결돼요</p>
        ) : (
          <button type="button" className="fam-btn fam-btn--primary" onClick={() => share('ELDER_DEVICE')} disabled={!!busy}>
            {sentDevice ? '연결 링크 다시 보내기' : '연결 링크 보내기'}
          </button>
        )}
        {sentDevice && (
          <p className="fam-mini" role="status">
            {sentDevice.sent ? `링크를 보냈어요 · ${hon} 폰에서 열면 연결돼요 · 24시간` : `주소를 길게 눌러 복사해 보내 주세요`}
          </p>
        )}
        {sentDevice && !sentDevice.sent && <p className="home-link">{sentDevice.url}</p>}
        {note && <p className="fam-mini" role="status">{note}</p>}
      </section>
      {ready && upload}
      {room.is_owner && (
        <button type="button" className="fam-card home-banner plain" onClick={() => share('FAMILY')} disabled={!!busy}>
          <span className="home-sq">
            <FamIcon name="family" />
          </span>
          <span className="home-banner-txt">
            <b>다른 가족 초대하기</b>
            <span className="fam-mini">
              {link?.kind === 'FAMILY' && link.sent ? '초대 링크를 보냈어요 · 7일 동안 쓸 수 있어요' : '형제·손주와 함께 소식을 받아요'}
            </span>
          </span>
          <FamIcon name="chevRight" />
        </button>
      )}
      {link?.kind === 'FAMILY' && !link.sent && <p className="home-link home-link--out">{link.url}</p>}
    </main>
  )
}

function NoRoom({ me }: { me: UserOut }) {
  const nav = useNavigate()
  return (
    <main className="fam-stack">
      <section className="fam-card home-connect">
        <div className="home-connect-h">
          <span className="fam-av fam-tone-a" aria-hidden="true">
            <Sim face="hello" size={40} />
          </span>
          <b>하루한장을 시작해 볼까요?</b>
        </div>
        <p className="home-lead">어르신 한 분마다 가족방을 하나 만들어요. 가족에게 초대 링크를 받았다면 그 링크를 열어 주세요.</p>
        <button type="button" className="fam-btn fam-btn--primary" onClick={() => nav('/groups/new')}>
          가족방 만들기
        </button>
      </section>
      {/* 가족방이 없으면 바꾸기 판도 가족방 탭도 없다 — 로그아웃을 여기에 (11/24).
          계정이 둘이면 다른 계정으로 들어온 줄 모른다 — 지금 계정을 보인다 (11/25 실사용) */}
      <p className="fam-note">지금 계정 · {me.email ?? me.name}</p>
      <button type="button" className="fam-btn fam-btn--text" onClick={() => logout(nav)}>
        로그아웃
      </button>
    </main>
  )
}

const FEED_DAYS = 7 // 11/27 팀 회의: 홈 피드는 오늘 포함 최근 7일만 — 그보다 예전은 일기 달력(HOME_003)
const TOP_AFTER = 600 // 이만큼(px) 내리면 [맨 위로] 버튼이 나타난다
/** 피드 첫날 0시(한국 시간)의 시각 — 오늘이 11/27 이면 11/21 0시 */
function feedStart() {
  const ymd = new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' }) // 'YYYY-MM-DD'
  return new Date(`${ymd}T00:00:00+09:00`).getTime() - (FEED_DAYS - 1) * 86_400_000
}
type Entry = { at: string; d?: DiaryOut; m?: MemoryCardOut }

function RoomHome({ room, me, reloadRooms }: { room: RoomOut; me: UserOut; reloadRooms: () => void }) {
  const diaries = useFetch<DiaryListOut>(`/api/rooms/${room.room_id}/diaries`)
  const mood = useFetch<MoodWeekOut>(`/api/rooms/${room.room_id}/mood-week`)
  const weekly = useFetch<WeeklyOut>(`/api/rooms/${room.room_id}/weekly`) // 아직 없으면 404 → 띠·안부 한 줄 없음
  // 회상 카드 (11/27) — 못 받으면(서버 오류·옛 서버) 회상 카드 없이 일기만
  const memories = useFetch<MemoryListOut>(`/api/rooms/${room.room_id}/memories`)
  // 좋아요·댓글로 바뀐 일기·회상. 다시 읽은 목록이 오면 버린다(서버가 이미 반영)
  const [edits, setEdits] = useState<{ base?: DiaryListOut; byId: Record<number, DiaryOut> }>({ byId: {} })
  const [memEdits, setMemEdits] = useState<{ base?: MemoryListOut; byId: Record<string, MemoryCardOut> }>({ byId: {} })
  // 일기 목록 글쓴이 필터 (11/18 멘토링) — 이미 불러온 목록을 화면에서 거른다
  // MINE = 내가 쓴 오늘 소식만 (11/24 실사용: 내 일기만 모아 볼 곳이 없었다)
  // 처음엔 어르신 일기만 (11/25 멘토링 '가족 화면 첫 장에 할머니 일기 먼저' · 11/26 사용자)
  const [who, setWho] = useState<'ALL' | 'MINE' | DiaryOut['author_type']>('ELDER')
  // 스크롤은 틀의 .fam-body 가 한다 — [맨 위로]·칩 누르기가 그 칸을 움직인다
  const [main, setMain] = useState<HTMLElement | null>(null)
  const filter = useRef<HTMLDivElement>(null)
  const [showTop, setShowTop] = useState(false)

  // 설치형 앱은 다시 열어도 화면이 새로 뜨지 않는다 → 앱으로 돌아올 때마다 다시 읽는다
  const reloadDiaries = diaries.reload
  const reloadMood = mood.reload
  const reloadWeekly = weekly.reload
  const reloadMemories = memories.reload
  useEffect(() => {
    const onShow = () => {
      if (document.visibilityState !== 'visible') return
      reloadDiaries()
      reloadMood()
      reloadWeekly()
      reloadMemories()
    }
    document.addEventListener('visibilitychange', onShow)
    return () => document.removeEventListener('visibilitychange', onShow)
  }, [reloadDiaries, reloadMood, reloadWeekly, reloadMemories])

  useEffect(() => {
    const scroller = main?.closest('.fam-body')
    if (!scroller) return
    const onScroll = () => setShowTop(scroller.scrollTop > TOP_AFTER)
    scroller.addEventListener('scroll', onScroll, { passive: true })
    return () => scroller.removeEventListener('scroll', onScroll)
  }, [main])

  const base = diaries.data
  const byId = edits.base === base ? edits.byId : {}
  const update = (d: DiaryOut) => setEdits({ base, byId: { ...byId, [d.diary_id]: d } })
  const memBase = memories.data
  const memById = memEdits.base === memBase ? memEdits.byId : {}
  const updateMem = (m: MemoryCardOut) => setMemEdits({ base: memBase, byId: { ...memById, [m.session_id]: m } })
  const since = feedStart()
  const recent = (iso: string) => new Date(iso).getTime() >= since
  // ponytail: 첫 쪽(서버 50개)만 본다 — 일주일에 50개를 넘는 가족방이 생기면 before 로 이어 읽기
  const items = (base?.diaries ?? []).map((d) => byId[d.diary_id] ?? d).filter((d) => recent(d.posted_at))
  const mems = (memBase?.memories ?? []).map((m) => memById[m.session_id] ?? m).filter((m) => recent(m.ended_at))
  const shown = who === 'ALL' ? items : items.filter((d) => (who === 'MINE' ? d.is_mine : d.author_type === who))
  // 회상은 어르신 것 — '어르신'·'전체' 칩에서만
  const entries: Entry[] = [
    ...shown.map((d) => ({ at: d.posted_at, d })),
    ...(who === 'ELDER' || who === 'ALL' ? mems.map((m) => ({ at: m.ended_at, m })) : []),
  ].sort((a, b) => b.at.localeCompare(a.at))
  const hasOlder = (base?.diaries.length ?? 0) > items.length || !!base?.has_more
  const error = diaries.error ?? mood.error
  // 일기 상세의 앞뒤 넘기기도 지금 보이는(거른) 목록 순서를 따른다
  const diaryOrder = JSON.stringify(!error && mood.data ? shown.map((d) => d.diary_id) : [])

  useEffect(() => {
    try {
      sessionStorage.setItem('haru.fam.diary-order', diaryOrder)
    } catch {
      /* 저장을 막은 폰에서도 홈 목록은 그대로 보여 준다. */
    }
  }, [diaryOrder])

  if (error) return <p className="fam-error">{error.message}</p>
  if (!base || !mood.data) return null

  if (!room.device_connected && base.diaries.length === 0 && mood.data.talked_days === 0) {
    return <StartHome room={room} reloadRooms={reloadRooms} />
  }

  // 칩을 누르면 그 목록의 맨 위부터 (11/27 팀 회의 — 내려 둔 자리에서 그대로 바뀌어 헷갈렸다).
  // 칩 줄은 위에 붙어 다니므로 바로 앞 카드(요약 카드)의 아래 끝이 목록의 맨 위다. 이미 그 위에 있으면 그대로
  function pick(key: typeof who) {
    setWho(key)
    const scroller = main?.closest('.fam-body')
    const prev = filter.current?.previousElementSibling
    if (!scroller || !prev) return
    const top = prev.getBoundingClientRect().bottom - scroller.getBoundingClientRect().top + scroller.scrollTop
    if (scroller.scrollTop > top) scroller.scrollTo({ top })
  }

  // 날짜별로 묶는다 (최신 순)
  const groups: [string, Entry[]][] = []
  for (const e of entries) {
    const label = dayLabel(new Date(e.at))
    const last = groups[groups.length - 1]
    if (last && last[0] === label) last[1].push(e)
    else groups.push([label, [e]])
  }
  // 안부 한 줄(D67②) — 가장 최근 주간 이야기의 것만, 그 주를 아직 안 봤을 때
  const latestWeek = weekly.data && weekly.data.next_week_start === null ? weekly.data : null
  const notes = latestWeek && weeklySeen(room.room_id) !== latestWeek.week_start ? (latestWeek.notes?.lines ?? []) : []
  const banner = <WeeklyBanner room={room} data={latestWeek} />
  const anything = base.diaries.length > 0 || mems.length > 0
  return (
    <main className="fam-stack" ref={setMain}>
      <UrgentCard roomId={room.room_id} who={`${room.elder_name} ${room.elder_honorific}`} />
      <InstallCard />
      <SummaryCard room={room} week={mood.data} notes={notes} />
      {anything && (
        <div className="fam-seg home-filter" role="group" aria-label="누가 쓴 일기" ref={filter}>
          {(
            [
              ['ELDER', `${room.elder_name} ${room.elder_honorific}`],
              ['ALL', '전체'],
              ['FAMILY', '가족'],
              ['MINE', '내 일기'],
            ] as const
          ).map(([key, label]) => (
            <button type="button" key={key} className="fam-chip" onClick={() => pick(key)} aria-pressed={who === key}>
              {label}
            </button>
          ))}
        </div>
      )}
      {groups.map(([label, es], gi) => (
        <Fragment key={label}>
          <h3 className="home-day-h">{label}</h3>
          {es.map((e, i) => (
            <Fragment key={e.d ? `d${e.d.diary_id}` : `m${e.m!.session_id}`}>
              {e.d ? <Post d={e.d} room={room} me={me} onChange={update} /> : <MemoryPost m={e.m!} room={room} me={me} onChange={updateMem} />}
              {gi === 0 && i === 0 && banner}
            </Fragment>
          ))}
        </Fragment>
      ))}
      {groups.length === 0 && banner}
      {anything && entries.length === 0 && <p className="home-none">최근 {FEED_DAYS}일 동안 이 소식이 없어요</p>}
      {hasOlder && (
        <Link className="fam-btn home-older" to={`/calendar/${room.room_id}`}>
          <FamIcon name="calendar" />
          지난 일기는 달력에서 보기
        </Link>
      )}
      {!anything && <Empty room={room} />}
      {showTop && (
        <button
          type="button"
          className="home-top"
          aria-label="맨 위로"
          onClick={() => main?.closest('.fam-body')?.scrollTo({ top: 0, behavior: 'smooth' })}
        >
          <FamIcon name="chevDown" />
        </button>
      )}
    </main>
  )
}

export default function HOME_001() {
  const { me, room, reloadRooms } = useFamily()
  if (!room) return <NoRoom me={me} />
  // 어르신을 바꾸면 고친 일기를 처음부터 (key)
  return <RoomHome key={room.room_id} room={room} me={me} reloadRooms={reloadRooms} />
}
