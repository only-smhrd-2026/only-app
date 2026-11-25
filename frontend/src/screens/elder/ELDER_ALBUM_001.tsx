/**
 * ELDER_ALBUM_001 — 사진첩 (11/23 시안 e-album, FR-ME-008). 이 화면만 스크롤한다(D51).
 * 위 달 탭 + 분류 칩 → 그 달 첫 사진을 크게, 나머지는 3열. 가족 사진 + 어르신 일기 사진·갤러리 사진(ELDER_CAMERA, D60 바꿈) — 일기 사진은 '일기' 표.
 * 맨 앞 칸 [+ 사진 올리기] = 폰 갤러리에서 한 장 골라 POST /api/elder/album (capture 없음 — 카메라는 일기 쓰기에만).
 * 사진을 누르면 먼저 화면 가득 크게 → [이 사진으로 이야기하기]를 눌러야 회상 대화를 연다.
 */
import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { AlbumOut, AlbumPhoto, PhotoGroup, SessionOut } from '../../api/types'
import ElderPhoto from '../../components/ElderPhoto'
import { ElderStop, IC } from '../../components/ElderUi'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import { speak, stopSpeaking } from '../../lib/audio'
import { readPaused } from '../../lib/pausedSession'
import { resizeImage } from '../../lib/resizeImage'
import './ELDER_ALBUM_001.css'

const GUIDE = '사진첩이에요. 보고 싶은 달과 사진을 눌러 주세요.'
const EMPTY = '아직 사진이 없어요. 사진 올리기를 누르면 폰에 있는 사진을 올릴 수 있어요.'
// 시안 CATS — '일기'는 분류가 아니라 어르신 일기 사진(diary_id 있음). 기타(ETC)는 '전체'에서만 보인다
const CATS: [PhotoGroup | 'ALL' | 'DIARY', string][] = [
  ['ALL', '전체'], ['FAMILY', '가족'], ['TRAVEL', '여행'], ['FOOD', '음식'], ['NATURE', '풍경'], ['EVENT', '행사'], ['DIARY', '일기'],
]
// 달 줄 맨 앞 [전체] — 처음에 고른 칸 (11/25 실사용: 전체 사진을 먼저 보고 그다음 달로)
const ALL = 'ALL'
/** 사진이 들어갈 탭: 올해는 달('2026-11' 꼴), 지난 해는 연도('2023' 꼴) (11/23 사용자) */
function monthOf(taken: string | null, now: Date): string {
  const d = taken ? new Date(taken) : now
  return d.getFullYear() === now.getFullYear() ? `${d.getFullYear()}-${d.getMonth() + 1}` : `${d.getFullYear()}`
}
function monthName(key: string): string {
  if (key === ALL) return '전체'
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
  const [month, setMonth] = useState<string>()
  const [cat, setCat] = useState<(typeof CATS)[number][0]>('ALL')
  const [open, setOpen] = useState<AlbumPhoto>()
  const [busy, setBusy] = useState<'talk' | 'up'>()
  const [note, setNote] = useState<string>()
  const [limited, setLimited] = useState(false) // 오늘 사진첩 이야기를 다 했으면 [이야기하기]를 잠근다
  const view = useRef<HTMLDialogElement>(null)
  const pick = useRef<HTMLInputElement>(null)
  const sessionIds = useRef(new Map<number, string>()) // 응답을 못 받아 다시 눌러도 같은 대화 번호 → 서버가 하나만 만든다
  const [now] = useState(() => new Date())

  const photos = data ? [...added.filter((a) => !data.photos.some((p) => p.photo_id === a.photo_id)), ...data.photos] : []
  // 찍은 날이 없는 사진은 바로 앞(더 새) 사진의 달에 둔다 — 서버가 '찍은 날, 없으면 올린 날' 새것 먼저로 준다
  // ponytail: 올린 날을 몰라 앞 사진 달로 어림. AlbumPhoto 에 uploaded_at 이 오면 그것으로
  const keyed: [AlbumPhoto, string][] = []
  for (const p of photos) keyed.push([p, p.taken_at ? monthOf(p.taken_at, now) : (keyed.at(-1)?.[1] ?? monthOf(null, now))])
  const months = [...new Set(keyed.map(([, k]) => k))]
  const cur = month && months.includes(month) ? month : ALL
  const shown = keyed.filter(
    ([p, k]) => (cur === ALL || k === cur) && (cat === 'ALL' || (cat === 'DIARY' ? p.diary_id !== null : p.group === cat)),
  )
  const list = shown.map(([p]) => p)
  const [hero, ...rest] = list
  const curName = monthName(cur)
  const heroName = cur === ALL && shown[0] ? monthName(shown[0][1]) : curName // [전체]면 대표 사진의 달

  const message = loading ? undefined : error
    ? error.code === 'DEVICE_REQUIRED' ? '가족이 보낸 연결 링크를 먼저 열어 주세요.' : error.message
    : data ? (photos.length ? GUIDE : EMPTY) : undefined

  useEffect(() => {
    if (message) void speak(message, speed)
    return () => stopSpeaking() // 떠나면 안내 소리를 멈춘다 — 다음 화면 첫 질문과 겹치지 않게
  }, [message, speed])

  function tell(text: string) {
    setNote(text)
    void speak(text, speed)
  }

  function chooseMonth(k: string) {
    setMonth(k)
    void speak(`${monthName(k)} 사진이에요.`, speed)
  }

  function show(p: AlbumPhoto) {
    setOpen(p)
    setNote(undefined)
    view.current?.showModal()
    void speak('이 사진으로 이야기할까요?', speed)
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
      setMonth(ALL) // 올린 사진이 맨 앞에 보이게
      setCat('ALL')
      tell('사진첩에 올렸어요. 가족도 같이 봐요.')
    } catch (err) {
      if (live.current) tell(err instanceof ApiError ? err.message : '사진을 올리지 못했어요. 다시 해 주세요.')
    } finally {
      if (live.current) setBusy(undefined)
    }
  }

  const paused = open ? readPaused() : null

  return (
    <main className="elder alb">
      <h1>사진첩</h1>
      {loading ? (
        <p className="elder-text" role="status">잠시만요…</p>
      ) : error ? (
        <ElderStop text={message} onRetry={error.code !== 'DEVICE_REQUIRED' ? reload : undefined} />
      ) : data && (
        <>
          {months.length > 0 && (
            <div className="alb-months" role="tablist" aria-label="달">
              {[ALL, ...months].map((k) => (
                <button key={k} type="button" role="tab" aria-selected={k === cur} onClick={() => chooseMonth(k)}>{monthName(k)}</button>
              ))}
            </div>
          )}
          {photos.length > 0 && (
            <div className="alb-chips">
              {CATS.map(([c, label]) => (
                <button key={c} type="button" className={`elder-chip${cat === c ? ' elder-chip--on' : ''}`} aria-pressed={cat === c} onClick={() => setCat(c)}>{label}</button>
              ))}
            </div>
          )}
          {!photos.length && <p className="elder-sub">{EMPTY}</p>}
          {note && !open && <p className="elder-sent-ok" role="status">{note}</p>}
          {hero ? (
            <button type="button" className="alb-hero" onClick={() => show(hero)} aria-label={`${heroName} 대표 사진${hero.caption ? `, ${hero.caption}` : ''}`}>
              <img src={hero.url} alt="" decoding="async" />
              <span><b>{heroName}</b>{hero.caption}</span>
              {hero.diary_id !== null && <i className="alb-tag">일기</i>}
            </button>
          ) : photos.length > 0 && (
            <div className="elder-center alb-none">
              <b>{cur === ALL ? '이런 사진이 없어요' : `${curName}에는 이런 사진이 없어요`}</b>
              <button type="button" className="elder-btn elder-btn--secondary elder-btn--sm" onClick={() => setCat('ALL')}>전체 보기</button>
            </div>
          )}
          <div className="alb-grid">
            <button type="button" className="alb-up" onClick={() => pick.current?.click()} disabled={!!busy}>
              {IC.plus}<span>{busy === 'up' ? '올리는 중…' : '사진 올리기'}</span>
            </button>
            {rest.map((p, i) => (
              <button key={p.photo_id} type="button" onClick={() => show(p)} aria-label={`${curName} 사진 ${i + 2}${p.diary_id !== null ? ', 일기 사진' : ''}`}>
                <img src={p.url} alt="" loading="lazy" decoding="async" />
                {p.diary_id !== null && <i className="alb-tag">일기</i>}
              </button>
            ))}
          </div>
          {/* capture 없음 = 폰 사진첩(갤러리)에서 고르기 */}
          <input type="file" accept="image/*" hidden ref={pick} onChange={(e) => void upload(e)} />
        </>
      )}
      <dialog
        ref={view}
        className="elder-cover"
        aria-label="사진 크게 보기"
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
            <h1 className="elder-sr">사진 크게 보기</h1>
            <ElderPhoto src={open.url} alt={open.diary_id !== null ? '일기 사진' : '사진첩 사진'} />
            {paused && <p className="elder-sub alb-center">아까 하던 이야기는 홈에서 이어서 할 수 있어요.</p>}
            {note && <p className="elder-text" role="alert">{note}</p>}
            <button type="button" className="elder-btn" onClick={() => void talk(open)} disabled={!!busy || limited}>
              <span className="elder-dot">{IC.chat}</span>{busy === 'talk' ? '잠시만요…' : '이 사진으로 이야기하기'}
            </button>
            <button type="button" className="elder-btn elder-btn--secondary" onClick={() => view.current?.close()}>닫기</button>
          </>
        )}
      </dialog>
    </main>
  )
}
