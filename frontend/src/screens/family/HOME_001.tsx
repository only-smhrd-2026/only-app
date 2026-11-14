/**
 * HOME_001 — 가족 홈 (D70, 목업 설계자료/목업_1115_가족 ①②③). 공통 틀(FamilyFrame) 안에서 지금 보는 어르신 한 분의 소식:
 * 마음 카드(한 줄 + 누르면 펼침) → '이번 주 이야기가 도착했어요' 띠(새로 왔고 안 본 동안만) → 날짜별 일기 카드(큰 사진).
 * 아직 시작 전(일기도 대화도 없음)이면 '시작 3단계'. 실시간 반영은 없다 — 홈을 열 때·앱으로 돌아올 때 읽는다(D36).
 * 회상 대화 내용은 여기 없다(주간 이야기로만, R18).
 */
import { Fragment, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import {
  MOOD_LABEL,
  type DiaryListOut,
  type DiaryOut,
  type InviteCreatedOut,
  type MoodWeekOut,
  type Reaction,
  type RoomOut,
  type UserOut,
  type WeeklyOut,
} from '../../api/types'
import FamIcon from '../../components/FamIcon'
import { Avatar } from '../../components/FamilyFrame'
import MoodIcon from '../../components/MoodIcon'
import { useFamily } from '../../hooks/useFamily'
import { useFetch } from '../../hooks/useFetch'
import { weeklySeen } from '../../lib/weeklySeen'
import './HOME_001.css'

// 마음 체크 결과 (D56): 점수 없이 3단계 문장만. 많이 힘드신 단계는 상담을 권한다
const CHECK_TEXT = {
  USUAL: '평소와 비슷해요',
  DOWN: '조금 가라앉으신 편이에요',
  HARD: '많이 힘드신 것 같아요 · 전문 상담을 권해 드려요',
} as const
const REACTS = [
  ['HEART', '❤️', '하트'],
  ['SMILE', '😊', '웃음'],
  ['CLAP', '👏', '박수'],
] as const
const WEEK_NO = ['첫째', '둘째', '셋째', '넷째', '다섯째']
const EMPTY_ART = (
  <svg viewBox="0 0 120 90" aria-hidden="true">
    <rect x="16" y="16" width="62" height="50" rx="10" fill="#ece6fb" transform="rotate(-9 47 41)" />
    <rect x="40" y="20" width="62" height="50" rx="10" fill="#fff" stroke="#cbbdf0" strokeWidth="2" />
    <circle cx="58" cy="37" r="6" fill="#fde7ef" />
    <path d="M46 64l16-14 10 8 8-6 16 12z" fill="#e2f4e5" />
  </svg>
)

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

function hourLabel(hhmmss: string) {
  const h = Number(hhmmss.slice(0, 2))
  return h === 0 ? '밤 12시' : h < 12 ? `오전 ${h}시` : h === 12 ? '낮 12시' : `오후 ${h - 12}시`
}

/** 마음 카드 (D55 ④, 목업 ②) — 한 줄 요약 + 누르면 7일 칸·마음 체크 결과. 진단 말·점수는 쓰지 않는다(NFR-DE-003) */
function MoodCard({ week }: { week: MoodWeekOut }) {
  const [open, setOpen] = useState(false)
  const toggle = () => setOpen((o) => !o)
  const check = week.last_check
  const last = week.days.length - 1
  return (
    <section className={open ? 'fam-card home-mood open' : 'fam-card home-mood'}>
      <div className="home-mood-row">
        <button type="button" className="home-mood-main" onClick={toggle} aria-expanded={open}>
          <b>{week.talked_days ? `${week.talked_days}일 이야기하셨어요` : '이번 주는 아직 이야기를 안 하셨어요'}</b>
          <small>최근 7일{week.low_days ? ` · 기운 없는 날 ${week.low_days}일` : ''}</small>
        </button>
        {/* 번호 없이 전화 앱만 연다 — 어르신 번호는 저장하지 않는다(D57) */}
        <a className="home-round" href="tel:" aria-label="전화 걸기">
          <FamIcon name="phone" />
        </a>
        <button type="button" className="home-chev" onClick={toggle} aria-label={open ? '접기' : '펼치기'}>
          <FamIcon name="chevDown" />
        </button>
      </div>
      {open && (
        <div className="home-mood-more">
          <div className="home-week">
            {week.days.map((d, i) => (
              <div key={d.date} className={`home-day${d.low ? ' low' : ''}${i === last ? ' today' : ''}`}>
                <b>{i === last ? '오늘' : day(d.date).toLocaleDateString('ko-KR', { weekday: 'short' })}</b>
                <i className={d.talked ? 'on' : undefined} />
                {d.diary_mood ? <MoodIcon mood={d.diary_mood} /> : <s>–</s>}
              </div>
            ))}
          </div>
          <p className="home-legend">
            <span>
              <i />
              이야기한 날
            </span>
            <span>그림 = 일기 기분 날씨</span>
            <span>
              <em />
              기운 없는 말씀이 있던 날
            </span>
          </p>
          {check && (
            <p className="home-check">
              <FamIcon name="heart" />
              <span>
                <b>
                  {day(check.check_date).getMonth() + 1}/{day(check.check_date).getDate()} 마음 체크
                </b>{' '}
                · {CHECK_TEXT[check.level]}
              </span>
            </p>
          )}
          <a className="fam-btn fam-btn--primary fam-btn--block" href="tel:">
            <FamIcon name="phone" />
            전화 한 통 드리기
          </a>
          <p className="home-fine">
            진단이 아니에요. 대화와 일기에서 느껴진 분위기만 알려 드리고, 무슨 말씀을 하셨는지는 전하지 않아요.
          </p>
        </div>
      )}
    </section>
  )
}

/** '○월 ○째 주 이야기가 도착했어요' 띠 — 그 주를 주간 이야기 화면에서 열어 보기 전까지만 (목업 ②, lib/weeklySeen) */
function WeeklyBanner({ room }: { room: RoomOut }) {
  const nav = useNavigate()
  const { data } = useFetch<WeeklyOut>(`/api/rooms/${room.room_id}/weekly`) // 아직 없으면 404 → 띠 없음
  if (!data || weeklySeen(room.room_id) === data.week_start) return null
  const d = day(data.week_start)
  const cards = data.qa_list.length
  return (
    <button type="button" className="home-banner" onClick={() => nav(`/weekly/${room.room_id}`)}>
      <span className="home-banner-ic">
        <FamIcon name="calendar" />
      </span>
      <span className="home-banner-txt">
        <b>
          {d.getMonth() + 1}월 {WEEK_NO[Math.floor((d.getDate() - 1) / 7)]} 주 이야기가 도착했어요
        </b>
        <small>
          {cards ? `이야기 카드 ${cards}장 · ` : ''}이야기한 날 {data.memory_days}일
        </small>
      </span>
      <FamIcon name="chevRight" className="home-banner-chev" />
    </button>
  )
}

/** 일기 카드 (목업 ②) — 큰 사진(자르지 않음, 11/14 사용자) · 글 세 줄. 누르면 그 자리에서 펼치고 '봤어요'를 남긴다 */
function Post({ d, room, me, onChange }: { d: DiaryOut; room: RoomOut; me: UserOut; onChange: (d: DiaryOut) => void }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const elder = d.author_type === 'ELDER'
  const name = elder ? `${room.elder_name} ${room.elder_honorific}` : (d.author_name ?? '가족')
  const sub = elder ? `${clock(d.posted_at)} · 일기` : [d.author_nickname, clock(d.posted_at), '오늘 한 장'].filter(Boolean).join(' · ')
  const mine = d.reactions.find((r) => r.by === 'FAMILY' && r.user_id === me.user_id)?.kind
  const liked = d.reactions.some((r) => r.by === 'ELDER' && r.kind === 'LIKE')

  // '봤어요' 기록(D36 family_read_by) — 일기 상세 화면(HOME_002, 월요일 김승희)이 생기면 그 화면을 열 때로 옮긴다
  function toggle() {
    setOpen((o) => !o)
    if (d.read_by_me) return
    onChange({ ...d, read_by_me: true })
    api(`/api/diaries/${d.diary_id}/read`, { method: 'POST' }).catch(() => {})
  }

  // 가족 이모지 (D54·#145): on = '이 상태로 만들어 줘'. 다른 이모지를 누르면 바꿔 끼우고, 켜진 것을 누르면 끈다
  async function react(kind: Reaction['kind']) {
    setBusy(true)
    try {
      onChange(await api<DiaryOut>(`/api/diaries/${d.diary_id}/reaction`, { body: { kind, on: mine !== kind } }))
    } catch {
      /* 실패하면 그대로 둔다 — 다시 누르면 된다 */
    } finally {
      setBusy(false)
    }
  }

  const text = <span className={open ? undefined : 'home-clamp'}>{d.body}</span>
  return (
    <article className="fam-card home-post">
      <header className="home-post-h">
        <Avatar name={elder ? room.elder_name : name} />
        <div className="home-post-who">
          <b>
            {name}
            {!d.read_by_me && <i className="home-new">새 일기</i>}
          </b>
          <small>{sub}</small>
        </div>
        <span className="home-post-mood">
          <MoodIcon mood={d.mood} />
          {MOOD_LABEL[d.mood]}
        </span>
      </header>
      {d.illustration_url ? (
        <>
          <button type="button" className="home-post-photo" onClick={toggle} aria-label="일기 펼치기">
            <img src={d.illustration_url} alt={d.illustration_type === 'AI_DRAWING' ? '그림일기 그림' : '일기 사진'} loading="lazy" />
            {d.illustration_type === 'AI_DRAWING' && (
              <span className="home-tag">
                <FamIcon name="sparkle" />
                그림일기
              </span>
            )}
          </button>
          <button type="button" className="home-post-text" onClick={toggle} aria-expanded={open}>
            {text}
          </button>
        </>
      ) : (
        <button type="button" className="home-post-only" onClick={toggle} aria-expanded={open}>
          {text}
        </button>
      )}
      <footer className="home-post-f">
        {elder ? (
          <div className="home-reacts">
            {REACTS.map(([kind, emoji, label]) => {
              const n = d.reactions.filter((r) => r.by === 'FAMILY' && r.kind === kind).length
              const on = mine === kind
              return (
                <button
                  type="button"
                  key={kind}
                  className={on ? 'home-react on' : 'home-react'}
                  onClick={() => react(kind)}
                  disabled={busy}
                  aria-pressed={on}
                  aria-label={n ? `${label} ${n}개` : label}
                >
                  {emoji}
                  {n > 0 && <span>{n}</span>}
                </button>
              )
            })}
          </div>
        ) : d.read_by_elder ? (
          <p className="home-heard">
            <FamIcon name="check" />
            {room.elder_honorific}
            {iga(room.elder_honorific)} 들으셨어요{liked ? ' · 좋아요를 보내셨어요' : ''}
          </p>
        ) : (
          <p className="home-heard not">아직 안 들으셨어요</p>
        )}
      </footer>
    </article>
  )
}

function Empty({ room }: { room: RoomOut }) {
  return (
    <div className="home-empty">
      {EMPTY_ART}
      <b>아직 소식이 없어요</b>
      <p>
        {room.elder_honorific} 일기와 가족이 쓴 '오늘 한 장'이 여기에 모여요
      </p>
    </div>
  )
}

/** 처음 홈 '시작 3단계' (목업 ③, 11/14 사용자) — 사진 3장(기기 링크 조건과 같은 셈) → 어르신 폰 연결 → 첫 이야기 */
function StartHome({ room, reloadRooms }: { room: RoomOut; reloadRooms: () => void }) {
  const nav = useNavigate()
  const [link, setLink] = useState<InviteCreatedOut | null>(null)
  const [sent, setSent] = useState(false) // 공유 창에서 보냈거나 복사함 — 공유 창을 닫았으면 '만들었어요'
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const hon = room.elder_honorific
  const photos = room.photo_count

  // 사진 올리기 탭에서 돌아오면 사진 수가 바뀌어 있다 → 이 화면이 뜰 때마다 가족방을 다시 읽는다
  useEffect(() => {
    reloadRooms()
  }, [reloadRooms])

  async function sendLink() {
    setBusy(true)
    setNote(null)
    try {
      const created = await api<InviteCreatedOut>(`/api/rooms/${room.room_id}/invites`, { body: { kind: 'ELDER_DEVICE' } })
      setLink(created)
      if (navigator.share) {
        await navigator
          .share({ text: `${hon} 폰에서 이 링크를 열어 주세요 — 하루한장`, url: created.url })
          .then(() => setSent(true))
          .catch(() => {})
      } else if (navigator.clipboard) {
        await navigator.clipboard.writeText(created.url)
        setSent(true)
        setNote('링크를 복사했어요')
      }
    } catch (e) {
      setNote((e as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  const connected = room.device_connected
  const step2 = connected ? 'done' : photos < 3 ? 'lock' : 'now'
  return (
    <div className="fam-stack">
      <section className="fam-card home-start">
        <h2>하루한장을 시작해 볼까요?</h2>
        <p className="home-lead">
          {room.elder_name} {hon}와 첫 이야기를 나누기까지 3단계예요
        </p>
        <ol className="home-steps">
          <li className={photos >= 3 ? 'done' : 'now'}>
            <span className="home-num">{photos >= 3 ? <FamIcon name="check" /> : '1'}</span>
            <div>
              <b>추억 사진 3장 올리기</b>
              <small>{photos >= 3 ? `${photos}장을 올렸어요` : `${photos}/3장 · 사진만 고르면 돼요`}</small>
              {photos < 3 && (
                <span className="home-bar-p">
                  <i style={{ width: `${(photos / 3) * 100}%` }} />
                </span>
              )}
            </div>
            {photos < 3 && (
              <button type="button" className="fam-btn fam-btn--primary fam-btn--sm" onClick={() => nav('/upload')}>
                사진 올리기
              </button>
            )}
          </li>
          <li className={step2}>
            <span className="home-num">{connected ? <FamIcon name="check" /> : '2'}</span>
            <div>
              <b>{hon} 폰 연결하기</b>
              <small>
                {connected
                  ? '연결됐어요'
                  : photos < 3
                    ? '사진 3장을 올리면 열려요'
                    : !room.is_owner
                      ? '방장이 링크를 보내면 연결돼요'
                      : sent
                        ? `링크를 보냈어요 · ${hon} 폰에서 열면 연결돼요`
                        : link
                          ? `링크를 만들었어요 · 아래 주소를 ${hon} 폰에서 열면 돼요`
                          : `${hon} 폰에서 링크를 열면 돼요 · 24시간`}
              </small>
              {link && !connected && <span className="home-link">{link.url}</span>}
              {note && <small>{note}</small>}
            </div>
            {step2 === 'lock' && <FamIcon name="lock" className="home-lk" />}
            {step2 === 'now' && room.is_owner && (
              <button type="button" className="fam-btn fam-btn--primary fam-btn--sm" onClick={sendLink} disabled={busy}>
                {link ? '다시 보내기' : '링크 보내기'}
              </button>
            )}
          </li>
          <li className={connected ? 'now' : 'lock'}>
            <span className="home-num">3</span>
            <div>
              <b>첫 이야기 기다리기</b>
              <small>
                매일 {hourLabel(room.memory_time)}에 {hon}께 사진을 들고 찾아가요
              </small>
            </div>
          </li>
        </ol>
      </section>
      <Empty room={room} />
    </div>
  )
}

function NoRoom() {
  const nav = useNavigate()
  return (
    <div className="fam-stack">
      <section className="fam-card home-start">
        <h2>하루한장을 시작해 볼까요?</h2>
        <p className="home-lead">어르신 한 분마다 가족방을 하나 만들어요. 가족에게 초대 링크를 받았다면 그 링크를 열어 주세요.</p>
        <button type="button" className="fam-btn fam-btn--primary fam-btn--block" onClick={() => nav('/groups/new')}>
          가족방 만들기
        </button>
      </section>
    </div>
  )
}

function RoomHome({ room, me, reloadRooms }: { room: RoomOut; me: UserOut; reloadRooms: () => void }) {
  const diaries = useFetch<DiaryListOut>(`/api/rooms/${room.room_id}/diaries`)
  const mood = useFetch<MoodWeekOut>(`/api/rooms/${room.room_id}/mood-week`)
  // 펼침('봤어요')·이모지로 바뀐 일기. 다시 읽은 목록이 오면 버린다(서버가 이미 반영)
  const [edits, setEdits] = useState<{ base?: DiaryListOut; byId: Record<number, DiaryOut> }>({ byId: {} })

  // 설치형 앱은 다시 열어도 화면이 새로 뜨지 않는다 → 앱으로 돌아올 때마다 다시 읽는다
  const reloadDiaries = diaries.reload
  const reloadMood = mood.reload
  useEffect(() => {
    const onShow = () => {
      if (document.visibilityState !== 'visible') return
      reloadDiaries()
      reloadMood()
    }
    document.addEventListener('visibilitychange', onShow)
    return () => document.removeEventListener('visibilitychange', onShow)
  }, [reloadDiaries, reloadMood])

  const error = diaries.error ?? mood.error
  if (error) return <p className="fam-error">{error.message}</p>
  if (!diaries.data || !mood.data) return null

  const base = diaries.data
  const byId = edits.base === base ? edits.byId : {}
  const update = (d: DiaryOut) => setEdits({ base, byId: { ...byId, [d.diary_id]: d } })
  const items = base.diaries.map((d) => byId[d.diary_id] ?? d)
  if (items.length === 0 && mood.data.talked_days === 0) return <StartHome room={room} reloadRooms={reloadRooms} />

  // 날짜별로 묶는다 (목록은 최신 순)
  const groups: [string, DiaryOut[]][] = []
  for (const d of items) {
    const label = dayLabel(new Date(d.posted_at))
    const last = groups[groups.length - 1]
    if (last && last[0] === label) last[1].push(d)
    else groups.push([label, [d]])
  }
  return (
    <div className="fam-stack">
      <MoodCard week={mood.data} />
      <WeeklyBanner room={room} />
      {groups.map(([label, ds]) => (
        <Fragment key={label}>
          <h3 className="home-day-h">{label}</h3>
          {ds.map((d) => (
            <Post key={d.diary_id} d={d} room={room} me={me} onChange={update} />
          ))}
        </Fragment>
      ))}
      {items.length === 0 && <Empty room={room} />}
    </div>
  )
}

export default function HOME_001() {
  const { me, room, reloadRooms } = useFamily()
  if (!room) return <NoRoom />
  // 어르신을 바꾸면 펼침·고친 일기를 처음부터 (key)
  return <RoomHome key={room.room_id} room={room} me={me} reloadRooms={reloadRooms} />
}
