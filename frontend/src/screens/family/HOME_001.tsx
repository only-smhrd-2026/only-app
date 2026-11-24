/**
 * HOME_001 — 가족 홈 (D70, 11/23 시안 f-home '소식 먼저'). 공통 틀(FamilyFrame) 안에서 지금 보는 어르신 한 분의 소식:
 * 급한 알림 → 한 줄 요약 카드(누르면 7일 칸·돌봄 일지, 오른쪽 전화) → 글쓴이 필터 → 날짜별 일기 카드(첫 일기 바로 아래 주간 띠).
 * 폰 연결 전이고 아직 아무 소식이 없으면 '폰을 연결해 주세요' 3단계(링크 보내기 → 폰에서 열기 → 홈 화면에 추가).
 * 실시간 반영은 없다 — 홈을 열 때·앱으로 돌아올 때 읽는다(D36). 회상 대화 내용은 여기 없다(주간 이야기로만, R18).
 */
import { Fragment, useEffect, useState, useSyncExternalStore } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import {
  MOOD_LABEL,
  type DiaryListOut,
  type DiaryOut,
  type InviteCreatedOut,
  type InviteKind,
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
const REACTS = [
  ['HEART', '❤️', '하트'],
  ['SMILE', '😊', '웃음'],
  ['CLAP', '👏', '박수'],
] as const
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
 * 한 줄 요약 카드 (11/23 시안 — D67②·D85 를 접어 둠): '오늘 오전 9:24에 이야기하셨어요' + 7일 중 며칠 + 오른쪽 전화.
 * 누르면 7일 칸 · 안부 한 줄 · 마음 체크 · 돌봄 일지가 펼쳐진다. 진단 말·점수는 쓰지 않는다(NFR-DE-003)
 */
function SummaryCard({ room, week, notes }: { room: RoomOut; week: MoodWeekOut; notes: string[] }) {
  const [open, setOpen] = useState(false)
  const check = week.last_check
  const last = week.days.length - 1
  const who = `${room.elder_name} ${room.elder_honorific}`
  return (
    <section className="fam-card home-sum" aria-label={`${who} 요즘`}>
      <div className="home-sum-row">
        <button type="button" className="home-strip" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          <b>{week.last_talk_at ? `${talkLabel(week.last_talk_at)}에 이야기하셨어요` : '아직 이야기를 나누지 않으셨어요'}</b>
          <span className="fam-mini">
            최근 7일 중 {week.talked_days}일{week.low_days ? ` · 기운 없는 날 ${week.low_days}일` : ''}
          </span>
          <span className="home-more">
            7일·돌봄 일지 {open ? '접기' : '보기'}
            <FamIcon name="chevDown" />
          </span>
        </button>
        {/* 번호 없이 전화 앱만 연다 — 어르신 번호는 저장하지 않는다(D57) */}
        <a className="home-call" href="tel:" aria-label={`${who}께 전화 걸기`}>
          <FamIcon name="phone" />
        </a>
      </div>
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
          <ol className="home-week" aria-label="최근 7일">
            {week.days.map((d, i) => {
              const s = d.low ? 'low' : d.talked ? 'on' : 'off'
              return (
                <li key={d.date} className={i === last ? 'today' : undefined}>
                  <Dot s={s} />
                  <span>{i === last ? '오늘' : day(d.date).toLocaleDateString('ko-KR', { weekday: 'short' })}</span>
                  <span className="home-sr">{WORD[s]}</span>
                </li>
              )
            })}
          </ol>
          <p className="fam-mini home-legend">
            {(['on', 'low', 'off'] as const).map((s) => (
              <span key={s}>
                <Dot s={s} />
                {WORD[s]}
              </span>
            ))}
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
          {week.other_checks.map((o) => (
            <p key={o.kind} className="home-check">
              <span aria-hidden="true">{o.face}</span>
              <span>
                <b>
                  {day(o.check_date).getMonth() + 1}/{day(o.check_date).getDate()} {OTHER_NAME[o.kind]}
                </b>{' '}
                · {o.title}
              </span>
            </p>
          ))}
          <CareCard roomId={room.room_id} />
          {/* 마음 알림 안내 (D55 — 처리방침 확정 11/17) */}
          <p className="fam-mini">
            진단이 아니에요. 기운 없는 말씀이 잦거나 위급한 말씀을 하시면 가족 모두에게 전화 한 통 알림을 보내요 ·{' '}
            <Link to="/policy#mood">자세히 ›</Link>
          </p>
        </>
      )}
    </section>
  )
}

const WORD = { on: '이야기한 날', low: '기운 없는 날', off: '기록 없음' } as const
function Dot({ s }: { s: keyof typeof WORD }) {
  return (
    <span className={`home-dot ${s}`} aria-hidden="true">
      {s === 'on' && <FamIcon name="check" />}
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

/** 일기 카드 — 큰 사진(자르지 않음, 11/14 사용자) · 글 세 줄. 누르면 일기 상세로 간다 */
function Post({ d, room, me, onChange }: { d: DiaryOut; room: RoomOut; me: UserOut; onChange: (d: DiaryOut) => void }) {
  const [busy, setBusy] = useState(false)
  const elder = d.author_type === 'ELDER'
  const name = elder ? `${room.elder_name} ${room.elder_honorific}` : (d.author_name ?? '가족')
  const sub = elder ? `${clock(d.posted_at)} · 일기` : [d.author_nickname, clock(d.posted_at), '오늘 소식'].filter(Boolean).join(' · ')
  const mine = d.reactions.find((r) => r.by === 'FAMILY' && r.kind !== 'REPLY' && r.user_id === me.user_id)?.kind
  const liked = d.reactions.some((r) => r.by === 'ELDER' && r.kind === 'LIKE')
  const elderReply = d.reactions.some((r) => r.by === 'ELDER' && r.kind === 'REPLY')
  const to = `/diaries/${d.diary_id}`
  // 한마디(가족·어르신 답) — 카드에는 마지막 두 개만, 더 있으면 그 자리에서 펼친다 (11/24 실사용 두 번)
  const replies = d.reactions.filter((r) => r.kind === 'REPLY' && r.text)
  const [allReplies, setAllReplies] = useState(false)

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

  return (
    <article className="fam-card home-post">
      <Link className="home-post-link" to={to} state={{ familyDiaryOrder: true }}>
        <header className="home-post-h">
          <Avatar name={elder ? room.elder_name : name} />
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
          <>
            <div className="home-reacts">
              {REACTS.map(([kind, emoji, label]) => {
                const n = d.reactions.filter((r) => r.by === 'FAMILY' && r.kind === kind).length
                const on = mine === kind
                return (
                  <button
                    type="button"
                    key={kind}
                    className="home-react"
                    onClick={() => react(kind)}
                    disabled={busy}
                    aria-pressed={on}
                    aria-label={n ? `${label} ${n} 개` : label}
                  >
                    <span aria-hidden="true">{emoji}</span>
                    {n > 0 && <span>{n}</span>}
                  </button>
                )
              })}
            </div>
            <Link className="fam-text-btn home-say" to={to} state={{ familyDiaryOrder: true }}>
              한마디 남기기
            </Link>
          </>
        ) : d.read_by_elder ? (
          <p className="home-heard">
            <FamIcon name="check" />
            {room.elder_honorific}
            {iga(room.elder_honorific)} 들으셨어요
            {elderReply ? ' · 말로 답하셨어요' : liked ? ' · 좋아요를 보내셨어요' : ''}
          </p>
        ) : (
          <p className="fam-mini">아직 안 들으셨어요</p>
        )}
      </footer>
      {replies.length > 0 && (
        <ul className="home-replies">
          {(allReplies ? replies : replies.slice(-2)).map((r) => (
            <li key={`${r.by}${r.user_id ?? ''}`}>
              <b>{r.by === 'ELDER' ? `${room.elder_name} ${room.elder_honorific}` : (r.name ?? '가족')}</b>
              {r.text}
            </li>
          ))}
          {replies.length > 2 && (
            <li>
              <button type="button" className="home-replies-more" onClick={() => setAllReplies((v) => !v)} aria-expanded={allReplies}>
                {allReplies ? '한마디 접기' : `한마디 ${replies.length}개 모두 보기`}
              </button>
            </li>
          )}
        </ul>
      )}
    </article>
  )
}

function Empty({ room }: { room: RoomOut }) {
  return (
    <div className="home-empty">
      <Sim face="smile" size={96} />
      <b>아직 소식이 없어요</b>
      <p>{room.elder_honorific} 일기와 가족이 쓴 '오늘 소식'이 여기에 모여요</p>
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

function NoRoom() {
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
      {/* 가족방이 없으면 바꾸기 판도 가족방 탭도 없다 — 로그아웃을 여기에 (11/24) */}
      <button type="button" className="fam-btn fam-btn--text" onClick={() => logout(nav)}>
        로그아웃
      </button>
    </main>
  )
}

function RoomHome({ room, me, reloadRooms }: { room: RoomOut; me: UserOut; reloadRooms: () => void }) {
  const diaries = useFetch<DiaryListOut>(`/api/rooms/${room.room_id}/diaries`)
  const mood = useFetch<MoodWeekOut>(`/api/rooms/${room.room_id}/mood-week`)
  const weekly = useFetch<WeeklyOut>(`/api/rooms/${room.room_id}/weekly`) // 아직 없으면 404 → 띠·안부 한 줄 없음
  // 이모지로 바뀐 일기. 다시 읽은 목록이 오면 버린다(서버가 이미 반영)
  const [edits, setEdits] = useState<{ base?: DiaryListOut; byId: Record<number, DiaryOut> }>({ byId: {} })
  const [older, setOlder] = useState<{
    base: DiaryListOut
    diaries: DiaryOut[]
    hasMore: boolean
    busy: boolean
    error?: string
  }>()
  // 일기 목록 글쓴이 필터 (11/18 멘토링) — 이미 불러온 목록을 화면에서 거른다. 더 불러온 지난 일기도 같은 필터로 보인다
  // MINE = 내가 쓴 오늘 소식만 (11/24 실사용: 내 일기만 모아 볼 곳이 없었다)
  const [who, setWho] = useState<'ALL' | 'MINE' | DiaryOut['author_type']>('ALL')

  // 설치형 앱은 다시 열어도 화면이 새로 뜨지 않는다 → 앱으로 돌아올 때마다 다시 읽는다
  const reloadDiaries = diaries.reload
  const reloadMood = mood.reload
  const reloadWeekly = weekly.reload
  useEffect(() => {
    const onShow = () => {
      if (document.visibilityState !== 'visible') return
      setOlder(undefined)
      reloadDiaries()
      reloadMood()
      reloadWeekly()
    }
    document.addEventListener('visibilitychange', onShow)
    return () => document.removeEventListener('visibilitychange', onShow)
  }, [reloadDiaries, reloadMood, reloadWeekly])

  const base = diaries.data
  const byId = edits.base === base ? edits.byId : {}
  const update = (d: DiaryOut) => setEdits({ base, byId: { ...byId, [d.diary_id]: d } })
  const page = older?.base === base ? older : undefined
  const items = [...(base?.diaries ?? []), ...(page?.diaries ?? [])].map((d) => byId[d.diary_id] ?? d)
  const shown = who === 'ALL' ? items : items.filter((d) => (who === 'MINE' ? d.is_mine : d.author_type === who))
  const hasMore = page?.hasMore ?? base?.has_more ?? false
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

  async function loadMore() {
    if (!base || !hasMore || page?.busy || diaries.loading || items.length === 0) return
    const pending = { base, diaries: page?.diaries ?? [], hasMore, busy: true }
    setOlder(pending)
    try {
      const next = await api<DiaryListOut>(
        `/api/rooms/${room.room_id}/diaries?before=${items[items.length - 1].diary_id}`,
      )
      // 복귀로 목록을 초기화한 뒤 도착한 이전 요청은 버린다.
      setOlder((current) => current === pending
        ? { base, diaries: [...pending.diaries, ...next.diaries], hasMore: next.has_more, busy: false }
        : current)
    } catch (e) {
      setOlder((current) => current === pending
        ? { ...pending, busy: false, error: e instanceof Error ? e.message : '지난 일기를 불러오지 못했어요. 다시 눌러 주세요.' }
        : current)
    }
  }
  if (!room.device_connected && items.length === 0 && mood.data.talked_days === 0) {
    return <StartHome room={room} reloadRooms={reloadRooms} />
  }

  // 날짜별로 묶는다 (목록은 최신 순)
  const groups: [string, DiaryOut[]][] = []
  for (const d of shown) {
    const label = dayLabel(new Date(d.posted_at))
    const last = groups[groups.length - 1]
    if (last && last[0] === label) last[1].push(d)
    else groups.push([label, [d]])
  }
  // 안부 한 줄(D67②) — 가장 최근 주간 이야기의 것만, 그 주를 아직 안 봤을 때
  const latestWeek = weekly.data && weekly.data.next_week_start === null ? weekly.data : null
  const notes = latestWeek && weeklySeen(room.room_id) !== latestWeek.week_start ? (latestWeek.notes?.lines ?? []) : []
  const banner = <WeeklyBanner room={room} data={latestWeek} />
  return (
    <main className="fam-stack">
      <UrgentCard roomId={room.room_id} who={`${room.elder_name} ${room.elder_honorific}`} />
      <InstallCard />
      <SummaryCard room={room} week={mood.data} notes={notes} />
      {items.length > 0 && (
        <div className="fam-seg home-filter" role="group" aria-label="누가 쓴 일기">
          {(
            [
              ['ALL', '전체'],
              ['ELDER', `${room.elder_name} ${room.elder_honorific}`],
              ['FAMILY', '가족'],
              ['MINE', '내 일기'],
            ] as const
          ).map(([key, label]) => (
            <button type="button" key={key} className="fam-chip" onClick={() => setWho(key)} aria-pressed={who === key}>
              {label}
            </button>
          ))}
        </div>
      )}
      {groups.map(([label, ds], gi) => (
        <Fragment key={label}>
          <h3 className="home-day-h">{label}</h3>
          {ds.map((d, i) => (
            <Fragment key={d.diary_id}>
              <Post d={d} room={room} me={me} onChange={update} />
              {gi === 0 && i === 0 && banner}
            </Fragment>
          ))}
        </Fragment>
      ))}
      {groups.length === 0 && banner}
      {items.length > 0 && shown.length === 0 && <p className="home-none">아직 이 일기가 없어요</p>}
      {page?.error && <p className="fam-error" role="alert">{page.error}</p>}
      {hasMore && items.length > 0 && (
        <button
          type="button"
          className="fam-btn home-older"
          onClick={loadMore}
          disabled={page?.busy || diaries.loading}
          aria-busy={page?.busy ?? false}
        >
          {page?.busy ? '지난 일기 불러오는 중…' : '지난 일기 더 보기'}
        </button>
      )}
      {items.length === 0 && <Empty room={room} />}
    </main>
  )
}

export default function HOME_001() {
  const { me, room, reloadRooms } = useFamily()
  if (!room) return <NoRoom />
  // 어르신을 바꾸면 고친 일기를 처음부터 (key)
  return <RoomHome key={room.room_id} room={room} me={me} reloadRooms={reloadRooms} />
}
