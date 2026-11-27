/**
 * ELDER_ALBUM_001 — 사진첩 (11/23 시안 e-album, FR-ME-008). 이 화면만 스크롤한다(D51).
 * 11/25 사용자 — 가족 사진첩처럼 단순하게(D105): 칩 [전체] [내 사진] [가족 사진] + 달 제목 + 사진 2열.
 * 11/27 팀 회의 — 시안 `설계자료/목업_1127_사진첩/elder.html`(FamilyAlbum 배치)대로:
 *   위 [← 뒤로](ElderBackFrame) + 제목 → 연도 한 줄 + 달 탭(한 번에 한 달, 사진을 옆으로 밀어도 달이 넘어감) + 칩 →
 *   달마다 큰 표지 사진(달 글자·사진 수, 첫 달에는 'N년 전 사진' 동그라미) → 3열 모자이크(12장마다 큰 칸) →
 *   [다음 달 사진 보기]. [+ 사진 올리기]는 오른쪽 아래에 떠 있다.
 *   묶음은 그대로 올해는 달('2026-11' 꼴), 지난 해는 연도('2023' 꼴) (11/23 사용자).
 * 가족 사진 + 어르신 일기 사진·갤러리 사진(ELDER_CAMERA, D60 바꿈). 사진마다 왼쪽 아래 이름표 — 가족은 보낸 사람 별명('큰딸'),
 * 어르신 사진은 '내 사진'·'내 일기'. 이 사진으로 회상을 나누셨으면 오른쪽 위 작은 말풍선.
 * [+ 사진 올리기] = 폰 갤러리에서 한 장 골라 POST /api/elder/album (capture 없음 — 카메라는 일기 쓰기에만).
 * 사진을 누르면 사진 보기 한 화면(<dialog>): 위 [‹ 뒤로](폰 뒤로 키도) + 날짜, 사진(자르지 않음, 누르면 크게),
 * 같은 달 사진을 ‹ ›·옆으로 밀어 넘기기, "큰딸이 보낸 사진이에요"를 보여 주고 읽음, 이 사진으로 나눈 이야기(최근 2개, 누르면 읽음),
 * [이 사진으로 이야기하기]를 눌러야 회상 대화를 연다. 아래 [닫기]는 없다(11/27 팀 회의).
 */
import { useEffect, useRef, useState, type ChangeEvent, type TouchEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { AlbumOut, AlbumPhoto, SessionOut } from '../../api/types'
import ElderPhoto from '../../components/ElderPhoto'
import { ElderStop, IC, openCover } from '../../components/ElderUi'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import { speak, stopSpeaking } from '../../lib/audio'
import { readPaused } from '../../lib/pausedSession'
import { resizeImage } from '../../lib/resizeImage'
import './ELDER_ALBUM_001.css'

const GUIDE = '사진첩이에요. 보고 싶은 사진을 눌러 주세요.'
const EMPTY = '아직 사진이 없어요. 사진 올리기를 누르면 폰에 있는 사진을 올릴 수 있어요.'
type Who = 'ALL' | 'MINE' | 'FAMILY'
const WHO: [Who, string][] = [['ALL', '전체'], ['MINE', '내 사진'], ['FAMILY', '가족 사진']]
const SWIPE_PX = 50 // 이만큼 옆으로 밀면 달·사진을 넘긴다 (시안과 같은 값)
const TALKS_SHOWN = 2 // 사진 보기에 보여 드리는 지난 이야기 수
const isMine = (p: AlbumPhoto) => p.source === 'ELDER_CAMERA'
/** 사진 칸 이름표 — 가족은 별명만('큰딸 (김하루)' → '큰딸'), 어르신 사진은 '내 사진'·'내 일기' */
const tagOf = (p: AlbumPhoto) => (isMine(p) ? (p.diary_id !== null ? '내 일기' : '내 사진') : (p.uploader_name ?? '가족').replace(/ \(.+\)$/, ''))
const iga = (w: string) => ((w.charCodeAt(w.length - 1) - 0xac00) % 28 ? '이' : '가')
/** 크게 볼 때 보여 주고 읽는 한 줄 */
const fromLine = (p: AlbumPhoto) =>
  isMine(p) ? (p.diary_id !== null ? '내 일기 사진이에요.' : '내가 올린 사진이에요.') : `${tagOf(p)}${iga(tagOf(p))} 보낸 사진이에요.`
/** 이 사진으로 나눈 회상 요약(새것 먼저) — 서버가 아직 안 주면 빈 목록 */
const talksOf = (p: AlbumPhoto) => p.talks ?? []
/** '11월 26일' */
const dayName = (iso: string) => {
  const d = new Date(iso)
  return `${d.getMonth() + 1}월 ${d.getDate()}일`
}
/** 사진이 들어갈 묶음: 올해는 달('2026-11' 꼴), 지난 해는 연도('2023' 꼴) (11/23 사용자) */
function monthOf(taken: string | null, now: Date): string {
  const d = taken ? new Date(taken) : now
  return d.getFullYear() === now.getFullYear() ? `${d.getFullYear()}-${d.getMonth() + 1}` : `${d.getFullYear()}`
}
const isYear = (key: string) => !key.includes('-')
function monthName(key: string): string {
  const [y, m] = key.split('-')
  return m ? `${m}월` : `${y}년`
}

export default function ELDER_ALBUM_001() {
  const nav = useNavigate()
  const { home } = (useLocation().state ?? {}) as ElderNavState
  const speed = Number(home?.settings.tts_speed) || 0.9
  const { data, error, loading, reload } = useFetch<AlbumOut>('/api/elder/album')
  const live = useLive()
  const [added, setAdded] = useState<AlbumPhoto[]>([]) // 이 화면에서 올린 사진 — 목록을 다시 받지 않고 앞에 붙인다
  const [who, setWho] = useState<Who>('ALL')
  const [mk, setMk] = useState<string>() // 보고 있는 달(묶음) — 없거나 칩으로 사라지면 첫 달
  const [open, setOpen] = useState<AlbumPhoto>()
  const [busy, setBusy] = useState<'talk' | 'up'>()
  const [note, setNote] = useState<string>()
  const [limited, setLimited] = useState(false) // 오늘 사진첩 이야기를 다 했으면 [이야기하기]를 잠근다
  const view = useRef<HTMLDialogElement>(null)
  const pick = useRef<HTMLInputElement>(null)
  const tabs = useRef<HTMLElement>(null)
  const swipeAt = useRef<{ x: number; y: number } | null>(null)
  const sessionIds = useRef(new Map<number, string>()) // 응답을 못 받아 다시 눌러도 같은 대화 번호 → 서버가 하나만 만든다
  const [now] = useState(() => new Date())

  const photos = data ? [...added.filter((a) => !data.photos.some((p) => p.photo_id === a.photo_id)), ...data.photos] : []
  // 찍은 날이 없는 사진은 바로 앞(더 새) 사진의 달에 둔다 — 서버가 '찍은 날, 없으면 올린 날' 새것 먼저로 준다
  // ponytail: 올린 날을 몰라 앞 사진 달로 어림. AlbumPhoto 에 uploaded_at 이 오면 그것으로
  const keyed: [AlbumPhoto, string][] = []
  for (const p of photos) keyed.push([p, p.taken_at ? monthOf(p.taken_at, now) : (keyed.at(-1)?.[1] ?? monthOf(null, now))])
  // 칩으로 거른 뒤 달(지난 해는 연도)마다 묶는다 — 새 묶음 먼저(서버 순서)
  const groups: [string, AlbumPhoto[]][] = []
  for (const [p, k] of keyed) {
    if (who !== 'ALL' && (who === 'MINE') !== isMine(p)) continue
    const g = groups.find(([key]) => key === k)
    if (g) g[1].push(p)
    else groups.push([k, [p]])
  }
  const at = Math.max(0, groups.findIndex(([k]) => k === mk))
  const cur = groups[at]
  const nextGroup = groups[at + 1]
  // 첫 달 표지의 'N년 전 사진' 동그라미 — 가장 옛 묶음이 지난 해면 그 첫 사진으로 바로 가기 (시안 memo)
  const oldest = groups.at(-1)
  const memo = at === 0 && cur && !isYear(cur[0]) && oldest && isYear(oldest[0]) ? oldest : undefined

  const message = loading ? undefined : error
    ? error.code === 'DEVICE_REQUIRED' ? '가족이 보낸 연결 링크를 먼저 열어 주세요.' : error.message
    : data ? (photos.length ? GUIDE : EMPTY) : undefined

  useEffect(() => {
    if (message) void speak(message, speed)
    return () => stopSpeaking() // 떠나면 안내 소리를 멈춘다 — 다음 화면 첫 질문과 겹치지 않게
  }, [message, speed])

  // 고른 달 탭이 보이게 가운데로 민다
  const curKey = cur?.[0]
  useEffect(() => {
    const on = tabs.current?.querySelector<HTMLElement>('[aria-current="true"]')
    if (on && tabs.current) tabs.current.scrollLeft = on.offsetLeft - tabs.current.clientWidth / 2 + on.offsetWidth / 2
  }, [curKey])

  function tell(text: string) {
    setNote(text)
    void speak(text, speed)
  }

  function choose(w: Who, label: string) {
    setWho(w)
    void speak(w === 'ALL' ? '전체 사진이에요.' : `${label}이에요.`, speed)
  }

  function goMonth(key: string) {
    setMk(key)
    window.scrollTo({ top: 0 })
    void speak(`${monthName(key)} 사진이에요.`, speed)
  }

  function stepMonth(d: number) {
    const n = groups[at + d]
    if (n) goMonth(n[0])
  }

  function show(p: AlbumPhoto) {
    setOpen(p)
    setNote(undefined)
    openCover(view.current)
    const talked = talksOf(p).length ? ' 이 사진으로 이야기 나누신 적이 있어요.' : ''
    void speak(`${fromLine(p)}${talked} 이 사진으로 이야기할까요?`, speed)
  }

  /** 사진 보기에서 같은 달의 앞·뒤 사진으로 */
  const openList = open ? (groups.find(([, list]) => list.includes(open))?.[1] ?? [open]) : []
  const openAt = open ? openList.indexOf(open) : -1
  function step(d: number) {
    const n = openList[openAt + d]
    if (!n) return
    setOpen(n)
    setNote(undefined)
    void speak(fromLine(n), speed)
  }

  /** 옆으로 밀기 — 사진첩이면 달 넘기기, 사진 보기면 사진 넘기기 (시안) */
  const onTouchStart = (e: TouchEvent) => {
    const t = e.touches[0]
    swipeAt.current = (e.target as Element).closest('.alb-tabs, .alb-chips') ? null : { x: t.clientX, y: t.clientY }
  }
  const onTouchEnd = (move: (d: number) => void) => (e: TouchEvent) => {
    const s = swipeAt.current
    swipeAt.current = null
    if (!s) return
    const dx = e.changedTouches[0].clientX - s.x
    const dy = e.changedTouches[0].clientY - s.y
    if (Math.abs(dx) < SWIPE_PX || Math.abs(dx) < Math.abs(dy) * 1.5) return
    move(dx < 0 ? 1 : -1)
  }

  async function talk(p: AlbumPhoto) {
    if (busy) return
    setBusy('talk')
    setNote(undefined)
    try {
      const sessionId = sessionIds.current.get(p.photo_id) ?? crypto.randomUUID()
      sessionIds.current.set(p.photo_id, sessionId)
      const session = await api<SessionOut>('/api/elder/sessions', {
        body: { session_id: sessionId, kind: 'ALBUM', photo_id: p.photo_id },
      })
      if (!live.current) return // 기다리는 중 뒤로 가기로 떠났으면 다시 끌고 가지 않는다
      nav(`/elder/memory/${sessionId}`, { state: { session, photoUrl: p.url, home } })
    } catch (e) {
      if (!live.current) return
      if (e instanceof ApiError && e.code === 'ALBUM_LIMIT') setLimited(true)
      tell(e instanceof ApiError ? e.message : '대화를 시작하지 못했어요. 다시 눌러 주세요.')
    } finally {
      if (live.current) setBusy(undefined)
    }
  }

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file || busy || !live.current) return
    setBusy('up')
    setNote(undefined)
    try {
      let photo = file
      try {
        photo = await resizeImage(file, 1280) // 일기 사진과 같은 크기로
      } catch {
        // 줄이지 못하는 형식이면 원본으로 — 서버가 형식을 검사한다
      }
      const form = new FormData()
      form.append('file', photo)
      form.append('request_id', crypto.randomUUID())
      const saved = await api<AlbumPhoto>('/api/elder/album', { form })
      if (!live.current) return
      setAdded((a) => [saved, ...a])
      setWho('ALL') // 올린 사진이 맨 앞에 보이게
      setMk(undefined)
      window.scrollTo({ top: 0 })
      tell('사진첩에 올렸어요. 가족도 같이 봐요.')
    } catch (err) {
      if (live.current) tell(err instanceof ApiError ? err.message : '사진을 올리지 못했어요. 다시 해 주세요.')
    } finally {
      if (live.current) setBusy(undefined)
    }
  }

  const paused = open ? readPaused() : null
  const cell = (p: AlbumPhoto, j: number) => {
    const big = j % 12 === 3 ? ' alb-cell--bl' : j % 12 === 9 ? ' alb-cell--br' : '' // 12장마다 왼쪽·오른쪽 큰 칸 (시안)
    const talked = talksOf(p).length > 0
    return (
      <button key={p.photo_id} type="button" className={`alb-cell${big}`} onClick={() => show(p)} aria-label={`${tagOf(p)} 사진${talked ? ' · 이야기 나눈 사진' : ''}`}>
        <img src={p.url} alt="" loading="lazy" decoding="async" />
        <i className={`alb-name${isMine(p) ? ' alb-name--me' : ''}`}>{tagOf(p)}</i>
        {talked && <span className="alb-talked" aria-hidden="true">{IC.chat}</span>}
      </button>
    )
  }

  return (
    <main className="elder alb" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd(stepMonth)}>
      <h1>사진첩</h1>
      {loading ? (
        <p className="elder-text" role="status">잠시만요…</p>
      ) : error ? (
        <ElderStop text={message} onRetry={error.code !== 'DEVICE_REQUIRED' ? reload : undefined} />
      ) : data && (
        <>
          {photos.length > 0 && (
            <div className="alb-top">
              {cur && <p className="alb-year">{isYear(cur[0]) ? '지난 해 사진' : `${cur[0].split('-')[0]}년`}</p>}
              {groups.length > 0 && (
                <nav className="alb-tabs" ref={tabs} aria-label="달">
                  {groups.map(([k]) => (
                    <button key={k} type="button" className="alb-tab" aria-current={k === curKey} onClick={() => goMonth(k)}>{monthName(k)}</button>
                  ))}
                </nav>
              )}
              <div className="alb-chips" role="group" aria-label="누구 사진">
                {WHO.map(([w, label]) => (
                  <button key={w} type="button" className={`elder-chip${who === w ? ' elder-chip--on' : ''}`} aria-pressed={who === w} onClick={() => choose(w, label)}>{label}</button>
                ))}
              </div>
            </div>
          )}
          {!photos.length && <p className="elder-sub">{EMPTY}</p>}
          {note && !open && <p className="elder-sent-ok" role="status">{note}</p>}
          {photos.length > 0 && !cur && <p className="elder-sub alb-center">{who === 'MINE' ? '아직 내 사진이 없어요.' : '아직 가족 사진이 없어요.'}</p>}
          {cur && (
            <section key={cur[0]} className="alb-page" aria-label={monthName(cur[0])}>
              <div className="alb-herowrap">
                <button type="button" className="alb-hero" onClick={() => show(cur[1][0])} aria-label={`${tagOf(cur[1][0])} 사진`}>
                  <img src={cur[1][0].url} alt="" decoding="async" />
                  <span className="alb-hero-ttl" aria-hidden="true">
                    <b>{monthName(cur[0])}</b>
                    <small>{isYear(cur[0]) ? '지난 해' : `${cur[0].split('-')[0]}년`}</small>
                  </span>
                  <span className="alb-hero-foot" aria-hidden="true">사진 {cur[1].length}장</span>
                </button>
                {memo && (
                  <button type="button" className="alb-memo" onClick={() => show(memo[1][0])}>
                    <img src={memo[1][0].url} alt="" />
                    {now.getFullYear() - Number(memo[0])}년 전 사진
                  </button>
                )}
              </div>
              {cur[1].length > 1 && <div className="alb-mosaic">{cur[1].slice(1).map(cell)}</div>}
              {nextGroup ? (
                <button type="button" className="elder-btn elder-btn--secondary alb-next" onClick={() => stepMonth(1)}>
                  {monthName(nextGroup[0])} 사진 보기{IC.next}
                </button>
              ) : (
                <p className="elder-sub alb-center alb-end">맨 처음 사진까지 다 봤어요</p>
              )}
            </section>
          )}
          {data && (
            <button type="button" className="alb-add" onClick={() => pick.current?.click()} disabled={!!busy}>
              {IC.plus}<span>{busy === 'up' ? '올리는 중…' : '사진 올리기'}</span>
            </button>
          )}
          {/* capture 없음 = 폰 사진첩(갤러리)에서 고르기 */}
          <input type="file" accept="image/*" hidden ref={pick} onChange={(e) => void upload(e)} />
        </>
      )}
      <dialog
        ref={view}
        tabIndex={-1}
        className="elder-cover alb-view"
        aria-label="사진 보기"
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd(step)}
        onClose={(e) => {
          // 안의 사진 크게 보기(ElderPhoto 의 dialog)가 닫힐 때도 올라온다 — 이 창이 닫힐 때만 비운다
          if (e.target !== e.currentTarget) return
          stopSpeaking()
          setOpen(undefined)
          setNote(undefined)
        }}
      >
        {open && (
          <>
            <div className="alb-vhead">
              <button type="button" className="elder-btn elder-btn--secondary elder-btn--sm" onClick={() => view.current?.close()} aria-label="뒤로">
                {IC.back}
                <span aria-hidden="true">뒤로</span>
              </button>
              <h1 className="alb-vttl">{open.taken_at ? dayName(open.taken_at) : '사진'}</h1>
            </div>
            <div className="alb-pbox">
              <ElderPhoto src={open.url} alt={open.diary_id !== null ? '일기 사진' : '사진첩 사진'} />
              {openAt > 0 && (
                <button type="button" className="alb-side alb-side--l" onClick={() => step(-1)} aria-label="앞 사진">{IC.back}</button>
              )}
              {openAt < openList.length - 1 && (
                <button type="button" className="alb-side alb-side--r" onClick={() => step(1)} aria-label="다음 사진">{IC.next}</button>
              )}
              {openList.length > 1 && <span className="alb-count" aria-hidden="true">{openAt + 1} / {openList.length}</span>}
            </div>
            <p className="elder-sub alb-center alb-from">{fromLine(open)}</p>
            {open.caption && <p className="elder-sub alb-center alb-cap">“{open.caption}”</p>}
            {talksOf(open).slice(0, TALKS_SHOWN).map((t) => (
              <button
                key={t.at}
                type="button"
                className="alb-talk"
                onClick={() => void speak(`${dayName(t.at)}에 나눈 이야기예요. ${t.summary}`, speed)}
              >
                <b>{IC.chat}{dayName(t.at)} 이야기</b>
                <span>{t.summary}</span>
              </button>
            ))}
            {paused && <p className="elder-sub alb-center">아까 하던 이야기는 홈에서 이어서 할 수 있어요.</p>}
            {note && <p className="elder-text" role="alert">{note}</p>}
            <button type="button" className="elder-btn" onClick={() => void talk(open)} disabled={!!busy || limited}>
              <span className="elder-dot">{IC.chat}</span>{busy === 'talk' ? '잠시만요…' : '이 사진으로 이야기하기'}
            </button>
          </>
        )}
      </dialog>
    </main>
  )
}
