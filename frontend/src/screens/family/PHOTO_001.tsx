/**
 * PHOTO_001 — 사진첩 탭 (11/23 새 화면, 사용자 결정. 시안 f-post·f-photos 를 합침 — 옛 가족방 탭 '올린 사진' 화면과
 * 추억 올리기 아래 사진첩(#279)을 이 탭으로 옮김). 위 막대·아래 탭 틀(FamilyFrame) 안, 지금 보는 분의 가족방.
 * 11/25 사용자: '기다려요·보여 드렸어요' 글자와 AI 분류 칩을 빼고 사진마다 어르신 이야기를 붙임 (D104).
 * 11/27 팀 회의: 시안 설계자료/목업_1127_사진첩/index.html(FamilyAlbum 배치)대로 —
 *   위: 연도(내리면 숨음) + 달 탭(왼쪽 네모 = 모든 달 한눈에) + 칩 전체·어르신·가족(?who=).
 *   한 번에 한 달: 큰 표지 사진(달 글자·사진 수·어르신 이야기 수, 첫 달이면 옛날 사진 동그라미) → 3열 모자이크(12장마다 큰 칸)
 *   → [다음 달 사진 보기]. 사진 칸을 옆으로 밀면 달이 넘어간다.
 *   사진 칸: 왼쪽 아래 올린 사람 동그라미(어르신은 파랑), 오른쪽 아래 말풍선 = 어르신이 이 사진으로 이야기하심.
 *   '보여 드릴 사진 N장 남았어요'는 2장 이하일 때만(3장 아래로 떨어졌을 때). 사진 댓글·별표는 넣지 않음(DB 없음).
 * 사진을 누르면 화면 가득 사진 보기: 위 [←]·날짜·[⋯](설명 고치기·이 사진 빼기) · 사진(자르지 않음, ‹ › 와 옆으로 밀기로
 * 같은 달 사진 넘기기) · 사진 속 사람 · 올린 사람과 한마디 · 어르신 이야기(주간 이야기 카드·바로잡아 주신 말) 또는
 * 이 사진을 쓴 일기(어르신 일기·오늘 소식 글과 어르신 답장, 목소리면 듣기). [이 사진 빼기]는 내가 올린 추억 사진이고
 * 아직 안 보여 드린 것만(서버 DELETE …/photos/{id}). [오늘 소식 보내기]·[추억 사진 올리기]는 아래 탭 가운데 [+].
 */
import { useEffect, useRef, useState, type ReactNode, type TouchEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { DiaryOut, PhotoListOut, PhotoOut, RoomOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import Sim from '../../components/Sim'
import VoicePlay from '../../components/VoicePlay'
import { useFamily } from '../../hooks/useFamily'
import { useFetch } from '../../hooks/useFetch'
import './steps.css'
import './PHOTO_001.css'

type Who = '' | 'ELDER' | 'FAMILY'
const FEW = 2 // 남은 사진이 이만큼 이하면 더 올려 달라는 한 줄 (11/27 회의 '3장 아래로 떨어졌을 때만')

/** 사진 목록 주소 — 전체면 who 없이, 다음 쪽은 before=앞 쪽 마지막 사진 번호 (routers/photos.py) */
function listUrl(roomId: number, who: Who, before?: number) {
  const q = new URLSearchParams()
  if (who) q.set('who', who)
  if (before) q.set('before', String(before))
  const s = q.toString()
  return `/api/rooms/${roomId}/photos${s ? `?${s}` : ''}`
}
/** 받침이 있으면 앞의 조사, 없으면 뒤의 조사 — 어르신 화면 ELDER_FAMILY_001 의 josa 와 같은 식 */
function josa(word: string, withFinal: string, without: string) {
  const code = word.charCodeAt(word.length - 1)
  return code >= 0xac00 && code <= 0xd7a3 && (code - 0xac00) % 28 !== 0 ? withFinal : without
}
// 오늘의 한 장에 안 나오는 사진 — AI 가 '이야기하기 어려운 사진'으로 본 것(services/picks.py). 기다려요라고 하면 거짓이라 따로
const isOff = (p: PhotoOut) => p.analyzed && p.usable === false
/** 어르신이 이 사진으로 이야기하셨다 — 대화·주간 이야기 카드·바로잡아 주신 말 중 하나라도 */
const talkedOf = (p: PhotoOut) => p.talked || p.quotes.length > 0 || !!p.elder_note
const md = (d: string) => `${Number(d.slice(5, 7))}월 ${Number(d.slice(8, 10))}일`
/** 'YYYY-MM-DD' → '11월 26일 목요일' (사진 보기 제목) */
function dayName(d: string) {
  const [y, m, day] = d.slice(0, 10).split('-').map(Number)
  return `${m}월 ${day}일 ${'일월화수목금토'[new Date(y, m - 1, day).getDay()]}요일`
}
/** 달 묶음 열쇠 — 찍은 날이면 'YYYY-MM', 연도만 고른 옛 사진은 'YYYY', 둘 다 모르면 '' */
const keyOf = (p: PhotoOut) => p.taken_at?.slice(0, 7) ?? (p.taken_year ? String(p.taken_year) : '')
const isOld = (k: string) => k.length === 4
const tabName = (k: string) => (!k ? '날짜 모름' : isOld(k) ? `${k}년쯤` : `${Number(k.slice(5))}월`)
/** 달로 묶는다 — 찍은 달(새 달 먼저) → 연도만 아는 옛 사진(새 해 먼저) → 날짜 모름. 묶음 안은 찍은 날 새것 먼저(같으면 서버 순서) */
function byMonth(photos: PhotoOut[]): [string, PhotoOut[]][] {
  const map = new Map<string, PhotoOut[]>()
  for (const p of photos) map.set(keyOf(p), [...(map.get(keyOf(p)) ?? []), p])
  const rank = (k: string) => (!k ? 2 : isOld(k) ? 1 : 0)
  return [...map]
    .map(([k, xs]): [string, PhotoOut[]] => [k, xs.sort((a, b) => (b.taken_at ?? '').localeCompare(a.taken_at ?? ''))])
    .sort(([a], [b]) => rank(a) - rank(b) || b.localeCompare(a))
}
/** '모든 사진' 묶음 이름 — 2026년 · 옛날 사진 · 날짜 모름 */
const groupName = (k: string) => (!k ? '날짜 모름' : isOld(k) ? '옛날 사진' : `${k.slice(0, 4)}년`)
const SOURCE: Record<PhotoOut['source'], string> = { FAMILY: '추억 사진', FAMILY_DIARY: '가족 일기', ELDER_CAMERA: '일기 사진' }

export default function PHOTO_001() {
  const { room } = useFamily()
  if (!room) {
    return (
      <main className="ph">
        <section className="fam-card ph-empty">
          <p>먼저 가족방을 만들어 주세요</p>
          <Link className="fam-btn fam-btn--primary" to="/groups/new">
            가족방 만들기
          </Link>
        </section>
      </main>
    )
  }
  // 위 막대에서 분을 바꾸면 처음부터(key) — 앞 방 사진·열린 판이 남지 않게
  return <Album key={room.room_id} room={room} />
}

// UPLOAD_002 와 같게 — 서버 UPLOAD_MAX_NOTE_CHARS(100), 1940년부터 올해까지
const MAX_NOTE = 100
const THIS_YEAR = new Date().getFullYear()
const YEARS = Array.from({ length: THIS_YEAR - 1939 }, (_, i) => THIS_YEAR - i)

type Page = { photos: PhotoOut[]; waiting: number; loading?: boolean } // loading = 칩을 바꿔 다시 받는 중
type Sheet = 'more' | 'edit' | 'del'

/** 옆으로 민 방향 — 왼쪽으로 밀면 1(다음), 오른쪽 -1, 위아래로 민 것·짧은 것은 0 (시안과 같은 기준) */
function useSwipe(onSwipe: (d: 1 | -1) => void) {
  const start = useRef<{ x: number; y: number } | null>(null)
  return {
    onTouchStart: (e: TouchEvent) => (start.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }),
    onTouchEnd: (e: TouchEvent) => {
      const s = start.current
      start.current = null
      if (!s) return
      const dx = e.changedTouches[0].clientX - s.x
      const dy = e.changedTouches[0].clientY - s.y
      if (Math.abs(dx) >= 50 && Math.abs(dx) >= Math.abs(dy) * 1.5) onSwipe(dx < 0 ? 1 : -1)
    },
  }
}

function Album({ room }: { room: RoomOut }) {
  const hon = room.elder_honorific
  // 보던 자리(누구 사진·달·보던 사진)를 이 화면의 방문 기록에 적어 둔다 — [일기 보기] 뒤 뒤로 오면 그 사진 그대로 (11/27)
  const nav = useNavigate()
  const loc = useLocation()
  const [saved] = useState<{ who: Who; mk?: string; viewId?: number } | undefined>(() => loc.state?.album)
  const [who, setWho] = useState<Who>(saved?.who ?? '')
  const [page, setPage] = useState<Page | null>(null)
  const [error, setError] = useState<ApiError | Error>()
  const [tick, setTick] = useState(0) // [다시 시도]
  const [mk, setMk] = useState<string | undefined>(saved?.mk) // 지금 보는 달 열쇠 — 없으면 맨 앞 달
  const [anim, setAnim] = useState('') // 달을 넘길 때 미끄러지는 방향
  const [all, setAll] = useState(false) // '모든 사진' 판
  const [mini, setMini] = useState(false) // 내리면 연도 줄을 숨긴다
  const [viewId, setViewId] = useState<number | undefined>(saved?.viewId) // 사진 보기
  const [sheet, setSheet] = useState<Sheet>()
  const [busy, setBusy] = useState(false)
  const [sheetError, setSheetError] = useState('')
  const [note, setNote] = useState('')
  // [설명 고치기] 판 (D98) — 올릴 때 묶음에 같은 글이 붙으니 한 장씩 여기서
  const [edit, setEdit] = useState<{ caption: string; people: string; year: string }>()
  const topRef = useRef<HTMLDivElement>(null)
  const albumTop = useRef(0) // 사진 보기에서 돌아올 때 앨범 스크롤 자리

  // 달 탭을 만들려면 모든 달을 알아야 해서 끝 쪽까지 이어 받는다 (한 쪽 PHOTO_LIST_LIMIT=100장, 받는 대로 그린다)
  // ponytail: 사진이 수천 장이 되면 달 목록 API(달·장수만)를 따로 두고 달마다 받기
  useEffect(() => {
    const stop = new AbortController()
    void (async () => {
      let photos: PhotoOut[] = []
      let before: number | undefined
      for (;;) {
        const out = await api<PhotoListOut>(listUrl(room.room_id, who, before), { signal: stop.signal })
        photos = [...photos, ...out.photos]
        setPage({ photos, waiting: out.waiting_count })
        setError(undefined)
        if (!out.has_more || !out.photos.length) return
        before = out.photos[out.photos.length - 1].photo_id
      }
    })().catch((e) => !stop.signal.aborted && setError(e))
    return () => stop.abort()
  }, [room.room_id, who, tick])

  useEffect(() => {
    nav(loc.pathname, { replace: true, state: { ...loc.state, album: { who, mk, viewId } } })
    // 보던 자리가 바뀔 때만 적는다 (loc 이 바뀌어 다시 도는 것은 막음)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [who, mk, viewId])

  useEffect(() => {
    if (!note) return
    const timer = window.setTimeout(() => setNote(''), 2600)
    return () => window.clearTimeout(timer)
  }, [note])

  // 틀의 스크롤 칸(.fam-body)을 내리면 연도 줄을 접는다 (시안 .top.mini)
  const scroller = () => topRef.current?.closest('.fam-body') ?? null
  useEffect(() => {
    const body = topRef.current?.closest('.fam-body')
    if (!body) return
    const onScroll = () => setMini(body.scrollTop > 30)
    body.addEventListener('scroll', onScroll, { passive: true })
    return () => body.removeEventListener('scroll', onScroll)
  }, [])

  // 고른 달 탭이 달 줄 가운데 오게
  const tabsRef = useRef<HTMLElement>(null)
  const months = page ? byMonth(page.photos) : []
  const ci = Math.max(0, months.findIndex(([k]) => k === mk))
  const cur = months[ci]
  const curKey = cur?.[0]
  useEffect(() => {
    const tabs = tabsRef.current
    const on = tabs?.querySelector<HTMLElement>('[aria-current="true"]')
    if (tabs && on) tabs.scrollLeft = on.offsetLeft - tabs.clientWidth / 2 + on.offsetWidth / 2
  }, [curKey, months.length])

  function pickWho(w: Who) {
    if (w === who) return
    setPage((p) => p && { ...p, photos: [], loading: true }) // 남은 사진 수는 그대로 두고 사진만 비운다
    setWho(w)
  }
  function goMonth(k: string) {
    const to = months.findIndex(([m]) => m === k)
    setAnim(to > ci ? 'in-l' : 'in-r')
    setMk(k)
    setAll(false)
    scroller()?.scrollTo(0, 0)
  }
  const stepMonth = (d: 1 | -1) => months[ci + d] && goMonth(months[ci + d][0])
  const albumSwipe = useSwipe(stepMonth)

  function openPhoto(id: number) {
    albumTop.current = scroller()?.scrollTop ?? 0
    setViewId(id)
  }
  function closePhoto() {
    setViewId(undefined)
    requestAnimationFrame(() => scroller()?.scrollTo(0, albumTop.current))
  }

  async function remove(p: PhotoOut) {
    if (busy) return
    setBusy(true)
    setSheetError('')
    try {
      await api<void>(`/api/rooms/${room.room_id}/photos/${p.photo_id}`, { method: 'DELETE' })
    } catch (e) {
      // 사진이 없음 = 이미 지워짐(두 번 누름·다른 가족이 먼저 지움) → 뺀 것으로 본다.
      // 같은 404 라도 ROOM_NOT_FOUND(가족방에서 내보내짐)는 안 지워진 것이라 오류로 보여 준다
      if (!(e instanceof ApiError && e.code === 'PHOTO_NOT_FOUND')) {
        setSheetError(e instanceof ApiError ? e.message : '빼지 못했어요. 다시 해 주세요')
        setBusy(false)
        return
      }
    }
    const counted = p.source === 'FAMILY' && !p.shown && !isOff(p) // 남은 사진 수에 들어 있던 사진
    setPage((pg) => pg && { ...pg, photos: pg.photos.filter((x) => x.photo_id !== p.photo_id), waiting: Math.max(0, pg.waiting - (counted ? 1 : 0)) })
    setSheet(undefined)
    closePhoto()
    setNote('사진을 뺐어요')
    setBusy(false)
  }

  async function saveNote(p: PhotoOut) {
    if (busy || !edit) return
    setBusy(true)
    setSheetError('')
    try {
      const body: Record<string, string | number | null> = { caption: edit.caption.trim() || null, people_note: edit.people.trim() || null }
      if (!p.taken_at) body.taken_year = edit.year ? Number(edit.year) : null // 찍은 날이 있는 사진은 언제쯤을 안 받는다
      const out = await api<PhotoOut>(`/api/rooms/${room.room_id}/photos/${p.photo_id}`, { method: 'PATCH', body })
      setPage((pg) => pg && { ...pg, photos: pg.photos.map((x) => (x.photo_id === out.photo_id ? out : x)) })
      setEdit(undefined)
      setSheet(undefined)
      setNote('설명을 고쳤어요')
    } catch (e) {
      setSheetError(e instanceof ApiError ? e.message : '고치지 못했어요. 다시 해 주세요')
    } finally {
      setBusy(false)
    }
  }

  const n = page?.waiting
  const view = viewId === undefined ? undefined : page?.photos.find((p) => p.photo_id === viewId)
  const closeSheet = () => !busy && (setSheet(undefined), setEdit(undefined), setSheetError(''))
  const canEdit = !!view && view.source === 'FAMILY' && (view.is_mine || room.is_owner) // 서버와 같은 규칙: 올린 사람·방장
  const canDel = !!view && view.source === 'FAMILY' && view.is_mine && !view.shown
  const chips: [Who, string][] = [['', '전체'], ['ELDER', hon], ['FAMILY', '가족']]

  const lowNotice = n !== undefined && n <= FEW && (
    <section className="ph-low">
      <p>{n === 0 ? `${hon}께 보여 드릴 새 사진이 없어요. 봤던 사진이 다시 나와요.` : `${hon}께 보여 드릴 사진이 ${n}장 남았어요.`}</p>
      <Link className="fam-btn fam-btn--primary fam-btn--sm" to="/upload">
        사진 올리기
      </Link>
    </section>
  )

  return (
    <main className="ph">
      <div ref={topRef} className={`ph-top${mini ? ' mini' : ''}`}>
        <div className="ph-year">{cur ? (!cur[0] ? '날짜 모름' : isOld(cur[0]) ? '옛날 사진' : cur[0].slice(0, 4)) : ''}</div>
        <div className="ph-months">
          <button type="button" className="ph-grid-btn" aria-label="모든 달 보기" onClick={() => setAll(true)} disabled={!months.length}>
            <FamIcon name="grid" />
          </button>
          <nav ref={tabsRef} className="ph-mtabs" aria-label="달">
            {months.map(([k]) => (
              <button key={k || 'none'} type="button" className="ph-mtab" aria-current={k === cur?.[0]} onClick={() => goMonth(k)}>
                {tabName(k)}
              </button>
            ))}
          </nav>
        </div>
        <div className="ph-chips" role="group" aria-label="누가 올린 사진">
          {chips.map(([w, label]) => (
            <button key={w || 'all'} type="button" className="st-chip" aria-pressed={who === w} onClick={() => pickWho(w)}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <div className="ph-pad">
          <p className="fam-error">{error.message}</p>
          <button type="button" className="fam-btn fam-btn--tonal" onClick={() => setTick((t) => t + 1)}>
            다시 시도
          </button>
        </div>
      ) : !page || page.loading ? (
        <p className="st-hint ph-pad" aria-busy="true">
          불러오는 중…
        </p>
      ) : !cur && !who ? (
        <div className="ph-pad">
          {lowNotice}
          <section className="fam-card ph-empty">
            <Sim face="hello" size={72} />
            <p>아직 올린 사진이 없어요</p>
            <p className="st-dim">옛 사진을 올리면 내일부터 {hon}께 하루 1장씩 보여 드려요</p>
            <Link className="fam-btn fam-btn--primary" to="/upload">
              첫 사진 올리기
            </Link>
          </section>
        </div>
      ) : !cur ? (
        <p className="st-hint ph-pad">이 칩에 해당하는 사진이 없어요</p>
      ) : (
        <MonthPage
          key={cur[0]}
          k={cur[0]}
          list={cur[1]}
          first={ci === 0}
          next={months[ci + 1]?.[0]}
          memo={ci === 0 && !!cur[0] && !isOld(cur[0]) ? page.photos.find((p) => !p.taken_at && p.taken_year && talkedOf(p)) : undefined}
          hon={hon}
          anim={anim}
          lowNotice={lowNotice}
          swipe={albumSwipe}
          onOpen={openPhoto}
          onMonth={goMonth}
        />
      )}

      {all && (
        <div className="ph-all" role="dialog" aria-modal="true" aria-label="모든 사진" onKeyDown={(e) => e.key === 'Escape' && setAll(false)}>
          <header className="ph-dbar">
            <span className="ph-ghost" />
            <div className="ph-dttl">
              <b>모든 사진</b>
            </div>
            <button type="button" className="ph-icon-btn" aria-label="닫기" onClick={() => setAll(false)} autoFocus>
              <FamIcon name="close" />
            </button>
          </header>
          <div className="ph-all-in">
            {[...new Set(months.map(([k]) => groupName(k)))].map((g) => (
              <section key={g}>
                <h3>{g}</h3>
                <div className="ph-allg">
                  {months
                    .filter(([k]) => groupName(k) === g)
                    .map(([k, xs]) => (
                      <button key={k || 'none'} type="button" className={`ph-mc${k === cur?.[0] ? ' on' : ''}`} onClick={() => goMonth(k)}>
                        <img className={isOld(k) ? 'ph-old' : undefined} src={xs[0].url} alt="" loading="lazy" />
                        <b>{tabName(k)}</b>
                        <small>{xs.length}장</small>
                      </button>
                    ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      )}

      {view && (
        <PhotoView
          key={view.photo_id}
          p={view}
          list={months.find(([k]) => k === keyOf(view))?.[1] ?? [view]}
          room={room}
          hasMore={view.source === 'FAMILY'}
          onBack={closePhoto}
          onGo={setViewId}
          onMore={() => (setSheetError(''), setSheet('more'))}
        />
      )}

      {view && sheet === 'more' && (
        <>
          <button type="button" className="fam-scrim" aria-label="닫기" onClick={closeSheet} />
          <div className="fam-sheet ph-sheet" role="dialog" aria-modal="true" aria-label="사진 메뉴" onKeyDown={(e) => e.key === 'Escape' && closeSheet()}>
            <span className="fam-grab" />
            {canEdit && (
              <button
                type="button"
                className="ph-opt"
                onClick={() => (setEdit({ caption: view.caption ?? '', people: view.people_note ?? '', year: view.taken_year ? String(view.taken_year) : '' }), setSheet('edit'))}
                autoFocus
              >
                <span className="ph-opt-ic">
                  <FamIcon name="pencil" />
                </span>
                <span>
                  설명 고치기
                  <small>
                    {hon}
                    {josa(hon, '과', '와')} 이야기할 때 AI가 참고해요
                  </small>
                </span>
              </button>
            )}
            {canDel ? (
              <button type="button" className="ph-opt danger" onClick={() => setSheet('del')}>
                <span className="ph-opt-ic">
                  <FamIcon name="close" />
                </span>
                <span>
                  이 사진 빼기
                  <small>아직 {hon}께 안 보여 드린 사진이에요</small>
                </span>
              </button>
            ) : (
              <p className="ph-mini">{view.shown ? `이미 보여 드린 사진은 ${hon} 사진첩에 남아서 뺄 수 없어요.` : '사진은 올린 사람만 뺄 수 있어요.'}</p>
            )}
            <button type="button" className="fam-btn fam-btn--tonal" onClick={closeSheet} autoFocus={!canEdit}>
              닫기
            </button>
          </div>
        </>
      )}

      {view && sheet === 'edit' && edit && (
        <>
          <button type="button" className="fam-scrim" aria-label="닫기" onClick={closeSheet} />
          <div
            className="fam-sheet ph-sheet"
            role="dialog"
            aria-modal="true"
            aria-label="설명 고치기"
            aria-busy={busy}
            onKeyDown={(e) => e.key === 'Escape' && closeSheet()}
          >
            <span className="fam-grab" />
            <h2>설명 고치기</h2>
            <p className="st-dim">이 사진 한 장에만 붙어요. {hon}
              {josa(hon, '과', '와')} 이야기할 때 AI가 참고해요</p>
            <label className="st-label" htmlFor="ph-caption">
              한마디
            </label>
            <textarea
              id="ph-caption"
              className="st-input"
              rows={2}
              value={edit.caption}
              maxLength={MAX_NOTE}
              disabled={busy}
              onChange={(e) => setEdit({ ...edit, caption: e.target.value })}
              autoFocus
            />
            <label className="st-label" htmlFor="ph-people">
              사진 속 사람
            </label>
            <input
              id="ph-people"
              className="st-input"
              value={edit.people}
              maxLength={MAX_NOTE}
              placeholder="예) 큰딸, 손주"
              disabled={busy}
              onChange={(e) => setEdit({ ...edit, people: e.target.value })}
            />
            {!view.taken_at && (
              <>
                <label className="st-label" htmlFor="ph-year">
                  언제쯤 사진인가요?
                </label>
                <select id="ph-year" className="st-input" value={edit.year} disabled={busy} onChange={(e) => setEdit({ ...edit, year: e.target.value })}>
                  <option value="">모르겠어요</option>
                  {YEARS.map((y) => (
                    <option key={y} value={y}>
                      {y}년쯤
                    </option>
                  ))}
                </select>
              </>
            )}
            {sheetError && (
              <p className="fam-error" role="alert">
                {sheetError}
              </p>
            )}
            <div className="ph-two">
              <button type="button" className="fam-btn fam-btn--tonal" disabled={busy} onClick={closeSheet}>
                취소
              </button>
              <button type="button" className="fam-btn fam-btn--primary" disabled={busy} onClick={() => saveNote(view)}>
                {busy ? '저장 중…' : '저장'}
              </button>
            </div>
          </div>
        </>
      )}

      {view && sheet === 'del' && (
        <>
          <button type="button" className="fam-scrim" aria-label="닫기" onClick={closeSheet} />
          <div
            className="fam-sheet ph-sheet"
            role="dialog"
            aria-modal="true"
            aria-label="사진을 뺄까요?"
            aria-busy={busy}
            onKeyDown={(e) => e.key === 'Escape' && closeSheet()}
          >
            <span className="fam-grab" />
            <h2>이 사진을 뺄까요?</h2>
            <p className="st-dim">{hon} 오늘의 한 장·사진첩에서도 사라져요</p>
            {sheetError && (
              <p className="fam-error" role="alert">
                {sheetError}
              </p>
            )}
            <div className="ph-two">
              <button type="button" className="fam-btn fam-btn--tonal" disabled={busy} onClick={closeSheet} autoFocus>
                취소
              </button>
              <button type="button" className="fam-btn ph-danger" disabled={busy} onClick={() => remove(view)}>
                {busy ? '빼는 중…' : '빼기'}
              </button>
            </div>
          </div>
        </>
      )}

      {note && (
        <p className="ph-snack" role="status">
          {note}
        </p>
      )}
    </main>
  )
}

/** 한 달 쪽 — 표지 사진 + 3열 모자이크 + [다음 달 사진 보기] (시안 albumHTML·cellHTML) */
function MonthPage(props: {
  k: string
  list: PhotoOut[]
  first: boolean
  next?: string
  memo?: PhotoOut
  hon: string
  anim: string
  lowNotice: ReactNode
  swipe: ReturnType<typeof useSwipe>
  onOpen: (id: number) => void
  onMonth: (k: string) => void
}) {
  const { k, list, first, next, memo, hon, anim, lowNotice, swipe, onOpen, onMonth } = props
  const [hero, ...rest] = list
  const talks = list.filter(talkedOf).length
  const old = isOld(k)
  return (
    <div className={`ph-page ${anim}`} {...swipe}>
      {first && lowNotice}
      <div className="ph-herowrap">
        <button type="button" className={`ph-hero${old ? ' ph-old' : ''}`} aria-label={`${tabName(k)} 표지 사진 열기`} onClick={() => onOpen(hero.photo_id)}>
          <img src={hero.url} alt="" />
          <span className="ph-ttl">
            <b>{!k ? '날짜 모름' : old ? `${k}년` : `${Number(k.slice(5))}월`}</b>
            <small>{!k ? '찍은 날을 모르는 사진' : old ? '연도만 아는 옛날 사진' : k.slice(0, 4)}</small>
          </span>
          <span className="ph-foot">
            사진 {list.length}장{talks ? ` · ${hon} 이야기 ${talks}번` : ''}
          </span>
          <PhotoUploaderAvatar photo={hero} />
        </button>
        {memo?.taken_year && (
          <button type="button" className="ph-memo" onClick={() => onOpen(memo.photo_id)}>
            <img className="ph-old" src={memo.url} alt="" />
            {THIS_YEAR - memo.taken_year}년 전 사진
          </button>
        )}
      </div>
      {rest.length > 0 && (
        <div className="ph-mosaic">
          <div className="ph-mgrid">
            {rest.map((p, j) => {
              const by = p.uploader_name ?? '가족'
              const big = j % 12 === 3 ? ' bl' : j % 12 === 9 ? ' br' : '' // 12장마다 큰 칸이 왼쪽·오른쪽 번갈아
              return (
                <button
                  key={p.photo_id}
                  type="button"
                  className={`ph-cell${big}${p.taken_year && !p.taken_at ? ' ph-old' : ''}`}
                  aria-label={`${by} 사진${talkedOf(p) ? ` · ${hon} 이야기` : ''} 열기`}
                  onClick={() => onOpen(p.photo_id)}
                >
                  <img src={p.url} alt="" loading="lazy" />
                  <PhotoUploaderAvatar photo={p} />
                  {talkedOf(p) && (
                    <span className="ph-talk" aria-hidden="true">
                      <FamIcon name="chat" />
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        </div>
      )}
      {next !== undefined ? (
        <button type="button" className="ph-next" onClick={() => onMonth(next)}>
          {tabName(next)} 사진 보기
          <FamIcon name="chevRight" />
        </button>
      ) : (
        <p className="ph-next">맨 처음 사진까지 다 봤어요</p>
      )}
    </div>
  )
}

function PhotoUploaderAvatar({ photo }: { photo: PhotoOut }) {
  return (
    <span className={`ph-who${photo.source === 'ELDER_CAMERA' ? ' by-elder' : ''}`} aria-hidden="true">
      {(photo.uploader_name ?? '가족')[0]}
      {photo.uploader_profile_url && (
        <img
          key={photo.uploader_profile_url}
          src={photo.uploader_profile_url}
          alt=""
          loading="lazy"
          onError={(event) => { event.currentTarget.hidden = true }}
        />
      )}
    </span>
  )
}

/** 사진 보기 (시안 detailHTML) — 화면 가득. 같은 달 사진을 ‹ › 와 옆으로 밀기로 넘긴다. 댓글·별표는 없다 */
function PhotoView(props: {
  p: PhotoOut
  list: PhotoOut[]
  room: RoomOut
  hasMore: boolean
  onBack: () => void
  onGo: (id: number) => void
  onMore: () => void
}) {
  const { p, list, room, hasMore, onBack, onGo, onMore } = props
  const i = list.findIndex((x) => x.photo_id === p.photo_id)
  const go = (d: 1 | -1) => list[i + d] && onGo(list[i + d].photo_id)
  const swipe = useSwipe(go)
  const people = (p.people_note ?? '').split(',').map((s) => s.trim()).filter(Boolean)
  return (
    <div className="ph-view" role="dialog" aria-modal="true" aria-label="사진 보기" onKeyDown={(e) => e.key === 'Escape' && onBack()}>
      <header className="ph-dbar">
        <button type="button" className="ph-icon-btn" aria-label="뒤로" onClick={onBack} autoFocus>
          <FamIcon name="arrowLeft" />
        </button>
        <div className="ph-dttl">
          <b>{p.taken_at ? dayName(p.taken_at) : p.taken_year ? `${p.taken_year}년쯤` : '날짜 모름'}</b>
          <small>
            <FamIcon name="lock" />
            가족방 {room.member_count}명 모두
          </small>
        </div>
        {hasMore ? (
          <button type="button" className="ph-icon-btn" aria-label="더 보기" onClick={onMore}>
            <FamIcon name="more" />
          </button>
        ) : (
          <span className="ph-ghost" />
        )}
      </header>
      <div className="ph-view-body">
        <div className={`ph-photo${p.taken_year && !p.taken_at ? ' ph-old' : ''}`} {...swipe}>
          <img src={p.url} alt={p.caption ?? '사진'} />
          {i > 0 && (
            <button type="button" className="ph-side l" aria-label="앞 사진" onClick={() => go(-1)}>
              <FamIcon name="chevLeft" />
            </button>
          )}
          {i < list.length - 1 && (
            <button type="button" className="ph-side r" aria-label="다음 사진" onClick={() => go(1)}>
              <FamIcon name="chevRight" />
            </button>
          )}
        </div>
        {people.length > 0 && (
          <div className="ph-ppl" aria-label="사진 속 사람">
            {people.map((s) => (
              <span key={s} className="ph-tag">
                {s}
              </span>
            ))}
          </div>
        )}
        <div className="ph-post">
          <div className="ph-hd">
            <b>{p.uploader_name ?? '가족'}</b>
            <small>{SOURCE[p.source]}</small>
          </div>
          {p.caption && <p>{p.caption}</p>}
        </div>
        <div className="ph-pad">
          <Story p={p} hon={room.elder_honorific} />
        </div>
      </div>
    </div>
  )
}

/**
 * 사진 보기 아래 (11/25) — 이 사진을 쓴 일기(어르신 일기·가족 오늘 소식)가 있으면 그 글과 어르신 답장(목소리는 눌러서 듣기),
 * 가족 추억 사진이면 어르신 이야기: 주간 이야기 카드(이미 걸러진 말) · 바로잡아 주신 말(FR-ME-009, 다음 대화는 이 말을 따른다).
 */
function Story({ p, hon }: { p: PhotoOut; hon: string }) {
  const diary = useFetch<DiaryOut>(p.diary_id ? `/api/diaries/${p.diary_id}` : null)
  const iga = josa(hon, '이', '가')
  if (p.diary_id) {
    const d = diary.data
    const reply = d?.reactions.find((r) => r.by === 'ELDER' && r.kind === 'REPLY')
    const liked = d?.reactions.some((r) => r.by === 'ELDER' && r.kind === 'LIKE')
    return (
      <section className="ph-story">
        <h3>{p.source === 'ELDER_CAMERA' ? `${hon} 일기` : `${p.uploader_name ?? '가족'}의 일기`}</h3>
        {d ? <p className="ph-quote">{d.body}</p> : <p className="ph-mini">{diary.error ? diary.error.message : '불러오는 중…'}</p>}
        {reply && (
          <p className="ph-said">
            {hon}
            {iga} 말로 답하셨어요 · ‘{reply.text}’
          </p>
        )}
        {reply?.audio_url && <VoicePlay url={reply.audio_url} sec={reply.audio_sec} label="목소리 듣기" />}
        {!reply && liked && (
          <p className="ph-said">
            {hon}
            {iga} 좋아요를 보내셨어요
          </p>
        )}
        <Link className="fam-text-btn" to={`/diaries/${p.diary_id}`}>
          일기 보기 ›
        </Link>
      </section>
    )
  }
  if (p.source !== 'FAMILY') return null
  return (
    <section className="ph-story">
      <h3>
        <FamIcon name="chat" />
        {hon} 이야기
      </h3>
      {p.quotes.map((q) => (
        <p key={q.day + q.question} className="ph-quote">
          {q.answer}
          <small>
            {md(q.day)} 회상 대화 · {q.question}
          </small>
        </p>
      ))}
      {p.elder_note && (
        <p className="ph-said">
          {hon}
          {iga} 바로잡아 주셨어요 · “{p.elder_note}” — 다음 이야기부터 이렇게 여쭤봐요
        </p>
      )}
      {p.talked && !p.quotes.length && <p className="ph-mini">이 사진으로 이야기하셨어요. 하신 말씀은 '주간 이야기'가 나오면 여기에도 붙어요.</p>}
      {!talkedOf(p) && <p className="ph-mini">아직 이 사진으로 이야기 나누지 않으셨어요.</p>}
    </section>
  )
}
