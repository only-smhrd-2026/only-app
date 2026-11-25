/**
 * ELDER_ALBUM_001 — 사진첩 (11/23 시안 e-album, FR-ME-008). 이 화면만 스크롤한다(D51).
 * 11/25 사용자 — 가족 사진첩처럼 단순하게(D105): 위 달 탭·큰 대표 사진·AI 분류 칩을 빼고
 * 칩 [전체] [내 사진] [가족 사진] → [+ 사진 올리기] → 달 제목('11월', 지난 해는 '2025년') + 사진 2열(새 사진 위).
 * 가족 사진 + 어르신 일기 사진·갤러리 사진(ELDER_CAMERA, D60 바꿈). 사진마다 왼쪽 아래 이름표 — 가족은 보낸 사람 별명('큰딸'),
 * 어르신 사진은 '내 사진'·'내 일기'. [+ 사진 올리기] = 폰 갤러리에서 한 장 골라 POST /api/elder/album (capture 없음 — 카메라는 일기 쓰기에만).
 * 사진을 누르면 먼저 화면 가득 크게("큰딸이 보낸 사진이에요"를 보여 주고 읽음) → [이 사진으로 이야기하기]를 눌러야 회상 대화를 연다.
 */
import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { AlbumOut, AlbumPhoto, SessionOut } from '../../api/types'
import ElderPhoto from '../../components/ElderPhoto'
import { ElderStop, IC } from '../../components/ElderUi'
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
const isMine = (p: AlbumPhoto) => p.source === 'ELDER_CAMERA'
/** 사진 칸 이름표 — 가족은 별명만('큰딸 (김하루)' → '큰딸'), 어르신 사진은 '내 사진'·'내 일기' */
const tagOf = (p: AlbumPhoto) => (isMine(p) ? (p.diary_id !== null ? '내 일기' : '내 사진') : (p.uploader_name ?? '가족').replace(/ \(.+\)$/, ''))
const iga = (w: string) => ((w.charCodeAt(w.length - 1) - 0xac00) % 28 ? '이' : '가')
/** 크게 볼 때 보여 주고 읽는 한 줄 */
const fromLine = (p: AlbumPhoto) =>
  isMine(p) ? (p.diary_id !== null ? '내 일기 사진이에요.' : '내가 올린 사진이에요.') : `${tagOf(p)}${iga(tagOf(p))} 보낸 사진이에요.`
/** 사진이 들어갈 묶음: 올해는 달('2026-11' 꼴), 지난 해는 연도('2023' 꼴) (11/23 사용자) */
function monthOf(taken: string | null, now: Date): string {
  const d = taken ? new Date(taken) : now
  return d.getFullYear() === now.getFullYear() ? `${d.getFullYear()}-${d.getMonth() + 1}` : `${d.getFullYear()}`
}
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
  // 칩으로 거른 뒤 달(지난 해는 연도)마다 묶는다 — 새 묶음 먼저(서버 순서)
  const groups: [string, AlbumPhoto[]][] = []
  for (const [p, k] of keyed) {
    if (who !== 'ALL' && (who === 'MINE') !== isMine(p)) continue
    const g = groups.find(([key]) => key === k)
    if (g) g[1].push(p)
    else groups.push([k, [p]])
  }

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

  function choose(w: Who, label: string) {
    setWho(w)
    void speak(w === 'ALL' ? '전체 사진이에요.' : `${label}이에요.`, speed)
  }

  function show(p: AlbumPhoto) {
    setOpen(p)
    setNote(undefined)
    view.current?.showModal()
    void speak(`${fromLine(p)} 이 사진으로 이야기할까요?`, speed)
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
          {photos.length > 0 && (
            <div className="alb-chips">
              {WHO.map(([w, label]) => (
                <button key={w} type="button" className={`elder-chip${who === w ? ' elder-chip--on' : ''}`} aria-pressed={who === w} onClick={() => choose(w, label)}>{label}</button>
              ))}
            </div>
          )}
          <button type="button" className="alb-up" onClick={() => pick.current?.click()} disabled={!!busy}>
            {IC.plus}<span>{busy === 'up' ? '올리는 중…' : '사진 올리기'}</span>
          </button>
          {!photos.length && <p className="elder-sub">{EMPTY}</p>}
          {note && !open && <p className="elder-sent-ok" role="status">{note}</p>}
          {photos.length > 0 && !groups.length && <p className="elder-sub alb-center">{who === 'MINE' ? '아직 내 사진이 없어요.' : '아직 가족 사진이 없어요.'}</p>}
          {groups.map(([k, list]) => (
            <section key={k} className="alb-month" aria-label={monthName(k)}>
              <h2>{monthName(k)}</h2>
              <div className="alb-grid">
                {list.map((p) => (
                  <button key={p.photo_id} type="button" onClick={() => show(p)} aria-label={`${tagOf(p)} 사진`}>
                    <img src={p.url} alt="" loading="lazy" decoding="async" />
                    <i className={`alb-name${isMine(p) ? ' alb-name--me' : ''}`}>{tagOf(p)}</i>
                  </button>
                ))}
              </div>
            </section>
          ))}
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
            <p className="elder-sub alb-center alb-from">{fromLine(open)}</p>
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
