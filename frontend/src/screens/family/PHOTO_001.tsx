/**
 * PHOTO_001 — 사진첩 탭 (11/23 새 화면, 사용자 결정. 시안 f-post·f-photos 를 합침 — 옛 가족방 탭 '올린 사진' 화면과
 * 추억 올리기 아래 사진첩(#279)을 이 탭으로 옮김). 위 막대·아래 탭 틀(FamilyFrame) 안, 지금 보는 분의 가족방.
 * 맨 위 '오늘의 한 장 남은 사진 N장'([오늘 소식 보내기]·[추억 사진 올리기]는 아래 탭 가운데 [+] 로 옮김, 11/23 사용자)
 * → 분류 칩(서버가 AI 분류를 묶은 PhotoGroup) → 달별 묶음 3열. 어르신이 찍은 이야기 사진(ELDER_CAMERA)도 섞여 나온다.
 * 사진을 누르면 아래 판: 크게(자르지 않음) · 올린 사람 · 찍은 날 · 보여 드렸어요/기다려요 · 어르신이 바로잡아 주신 말 ·
 * [이 사진 빼기](내가 올렸고 아직 안 보여 드린 사진만, 서버 DELETE …/photos/{id}). 'AI 가 본 것'·활동 고치기는 없다(D73 바꿈).
 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { PhotoGroup, PhotoListOut, PhotoOut, RoomOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import { useFamily } from '../../hooks/useFamily'
import './steps.css'
import './PHOTO_001.css'

const GROUPS: [PhotoGroup | '', string][] = [
  ['', '전체'],
  ['FAMILY', '가족'],
  ['TRAVEL', '여행'],
  ['FOOD', '음식'],
  ['NATURE', '풍경'],
  ['EVENT', '행사'],
  ['ETC', '기타'],
]
const FEW = 3 // 남은 사진이 이만큼 이하면 더 올려 달라는 한 줄 (시안 f-post)

/** 사진 목록 주소 — 전체면 group 없이, 더 보기는 before=앞 쪽 마지막 사진 번호 (routers/photos.py) */
function listUrl(roomId: number, group: PhotoGroup | '', before?: number) {
  const q = new URLSearchParams()
  if (group) q.set('group', group)
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
/** 사진 칸 아래 이름표 — 어르신 사진·오늘 소식 사진은 오늘의 한 장과 상관없어 출처만 */
function tagOf(p: PhotoOut, hon: string): [string, string] {
  if (p.source === 'ELDER_CAMERA') return [`${hon} 사진`, ' elder']
  if (p.source === 'FAMILY_DIARY') return ['오늘 소식', '']
  if (p.shown) return ['보여 드렸어요', ' done']
  if (isOff(p)) return ['안 나와요', '']
  return ['기다려요', '']
}
/** 'YYYY-MM-DD' → '2019년 1월 3일' */
function dayName(d: string) {
  const [y, m, day] = d.split('-').map(Number)
  return `${y}년 ${m}월 ${day}일`
}
/** 찍은 달로 묶는다(새 달 먼저). 찍은 날을 모르는 사진은 맨 끝 '날짜 모름' — 서버 순서(올린 순)는 묶음 안에서 그대로 */
function byMonth(photos: PhotoOut[]) {
  const map = new Map<string, PhotoOut[]>()
  for (const p of photos) {
    const k = p.taken_at?.slice(0, 7) ?? (p.taken_year ? String(p.taken_year) : '') // 연도만 고른 사진은 'YYYY'
    map.set(k, [...(map.get(k) ?? []), p])
  }
  return [...map].sort(([a], [b]) => (a === '' ? 1 : b === '' ? -1 : b.localeCompare(a)))
}
const monthName = (k: string) =>
  !k ? '날짜 모름' : k.length === 4 ? `${k}년쯤` : `${Number(k.slice(0, 4))}년 ${Number(k.slice(5))}월`

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
const YEARS = Array.from({ length: new Date().getFullYear() - 1939 }, (_, i) => new Date().getFullYear() - i)

type Page = { photos: PhotoOut[]; hasMore: boolean; waiting: number; loading?: boolean } // loading = 칩을 바꿔 다시 받는 중

function Album({ room }: { room: RoomOut }) {
  const hon = room.elder_honorific
  const [group, setGroup] = useState<PhotoGroup | ''>('')
  const [page, setPage] = useState<Page | null>(null)
  const [error, setError] = useState<ApiError | Error>()
  const [tick, setTick] = useState(0) // [다시 시도]
  const [more, setMore] = useState(false) // 더 보기 불러오는 중
  const [open, setOpen] = useState<{ id: number; del: boolean }>()
  const [busy, setBusy] = useState(false)
  const [sheetError, setSheetError] = useState('')
  const [note, setNote] = useState('')
  // [설명 고치기] 판 (D98) — 올릴 때 묶음에 같은 글이 붙으니 한 장씩 여기서
  const [edit, setEdit] = useState<{ caption: string; people: string; year: string }>()
  // 칩을 바꾸는 사이 늦게 온 '더 보기' 답을 버리려고 — 첫 쪽을 새로 부를 때마다 바뀐다
  const gen = useRef(0)

  useEffect(() => {
    const stop = new AbortController()
    const mine = ++gen.current
    api<PhotoListOut>(listUrl(room.room_id, group), { signal: stop.signal })
      .then((out) => {
        setPage({ photos: out.photos, hasMore: out.has_more, waiting: out.waiting_count })
        setError(undefined)
      })
      .catch((e) => !stop.signal.aborted && gen.current === mine && setError(e))
    return () => stop.abort()
  }, [room.room_id, group, tick])

  useEffect(() => {
    if (!note) return
    const timer = window.setTimeout(() => setNote(''), 2600)
    return () => window.clearTimeout(timer)
  }, [note])

  function pickGroup(g: PhotoGroup | '') {
    if (g === group) return
    setPage((p) => p && { ...p, photos: [], hasMore: false, loading: true }) // 남은 사진 수는 그대로 두고 사진만 비운다
    setGroup(g)
  }

  async function loadMore() {
    const last = page?.photos.at(-1)
    if (!last || more) return
    const mine = gen.current
    setMore(true)
    try {
      const out = await api<PhotoListOut>(listUrl(room.room_id, group, last.photo_id))
      if (gen.current !== mine) return
      setPage((p) => p && { photos: [...p.photos, ...out.photos], hasMore: out.has_more, waiting: out.waiting_count })
    } catch (e) {
      if (gen.current === mine) setNote(e instanceof ApiError ? e.message : '사진을 더 불러오지 못했어요')
    } finally {
      setMore(false)
    }
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
    setOpen(undefined)
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
      setNote('설명을 고쳤어요')
    } catch (e) {
      setSheetError(e instanceof ApiError ? e.message : '고치지 못했어요. 다시 해 주세요')
    } finally {
      setBusy(false)
    }
  }

  const n = page?.waiting
  const cur = open && page?.photos.find((p) => p.photo_id === open.id)
  const close = () => !busy && (setOpen(undefined), setEdit(undefined), setSheetError(''))
  const canEdit = cur && cur.source === 'FAMILY' && (cur.is_mine || room.is_owner) // 서버와 같은 규칙: 올린 사람·방장

  return (
    <main className="ph">
      <section className="fam-card ph-pool">
        <div className="ph-row">
          <h2>오늘의 한 장 남은 사진</h2>
          <b className="ph-big">{n === undefined ? '…' : `${n}장`}</b>
        </div>
        {n !== undefined && n <= FEW && (
          <p className="st-dim">
            {n === 0 ? '이제 봤던 사진이 다시 나와요.' : `${n}일 뒤부터는 봤던 사진이 다시 나와요.`} {hon}
            {josa(hon, '이', '가')} 좋아하실 옛 사진을 더 올려 주세요.
          </p>
        )}
      </section>

      <div className="ph-seg" role="group" aria-label="사진 묶음">
        {GROUPS.map(([g, label]) => (
          <button key={label} type="button" className="st-chip" aria-pressed={group === g} onClick={() => pickGroup(g)}>
            {label}
          </button>
        ))}
      </div>

      {error ? (
        <>
          <p className="fam-error">{error.message}</p>
          <button type="button" className="fam-btn fam-btn--tonal" onClick={() => setTick((t) => t + 1)}>
            다시 시도
          </button>
        </>
      ) : !page || page.loading ? (
        <p className="st-hint" aria-busy="true">
          불러오는 중…
        </p>
      ) : page.photos.length === 0 && !group ? (
        <section className="fam-card ph-empty">
          <p>아직 올린 사진이 없어요</p>
          <p className="st-dim">옛 사진을 올리면 내일부터 {hon}께 하루 1장씩 보여 드려요</p>
          <Link className="fam-btn fam-btn--primary" to="/upload">
            첫 사진 올리기
          </Link>
        </section>
      ) : page.photos.length === 0 ? (
        <p className="st-hint">이 묶음에는 아직 사진이 없어요</p>
      ) : (
        <>
          {byMonth(page.photos).map(([k, list]) => (
            <section key={k} className="ph-month" aria-label={monthName(k)}>
              <h3>
                {monthName(k)} · {list.length}장
              </h3>
              <ul className="st-grid">
                {list.map((p) => {
                  const [label, cls] = tagOf(p, hon)
                  return (
                    <li key={p.photo_id}>
                      <button
                        type="button"
                        className="st-thumb"
                        aria-label={`${label}${p.elder_note ? ' · 바로잡음' : ''} 사진 열기`}
                        onClick={() => (setSheetError(''), setOpen({ id: p.photo_id, del: false }))}
                      >
                        <img src={p.url} alt="" loading="lazy" />
                        <span className={`ph-cap${cls}`}>{label}</span>
                        {p.elder_note && (
                          <span className="ph-fix" aria-hidden="true">
                            바로잡음
                          </span>
                        )}
                      </button>
                    </li>
                  )
                })}
              </ul>
            </section>
          ))}
          {page.hasMore && (
            <button type="button" className="fam-btn fam-btn--tonal" disabled={more} onClick={loadMore}>
              {more ? '불러오는 중…' : '사진 더 보기'}
            </button>
          )}
        </>
      )}

      {cur && !open?.del && !edit && (
        <>
          <button type="button" className="fam-scrim" aria-label="닫기" onClick={close} />
          <div className="fam-sheet ph-sheet" role="dialog" aria-modal="true" aria-label="사진 자세히" onKeyDown={(e) => e.key === 'Escape' && close()}>
            <span className="fam-grab" />
            <div className="ph-pic">
              <img src={cur.url} alt="고른 사진" />
            </div>
            <div className="ph-row">
              <span className="ph-grow">
                <b>{cur.uploader_name ?? '가족'}</b>
                {cur.taken_at ? <small>{dayName(cur.taken_at)} 찍음</small> : cur.taken_year && <small>{cur.taken_year}년쯤 찍음</small>}
              </span>
              {cur.source === 'FAMILY' && (
                <span className={cur.shown ? 'ph-tag ok' : 'ph-tag'}>
                  {cur.shown ? `${hon}께 보여 드렸어요` : isOff(cur) ? '오늘의 한 장에는 안 나와요' : '기다려요'}
                </span>
              )}
            </div>
            {cur.caption && (
              <p>
                <small className="ph-mini">한마디</small>
                <br />
                {cur.caption}
              </p>
            )}
            {cur.people_note && (
              <p>
                <small className="ph-mini">사진 속 사람</small>
                <br />
                {cur.people_note}
              </p>
            )}
            {canEdit && (
              <button
                type="button"
                className="fam-btn fam-btn--tonal"
                onClick={() => (setSheetError(''), setEdit({ caption: cur.caption ?? '', people: cur.people_note ?? '', year: cur.taken_year ? String(cur.taken_year) : '' }))}
              >
                설명 고치기
              </button>
            )}
            {/* 어르신이 대화에서 바로잡아 주신 말 (FR-ME-009) — 다음 대화는 이 말을 따른다 */}
            {cur.elder_note && (
              <p className="st-note ph-fixnote">
                <FamIcon name="check" />
                <span>
                  <b>
                    {hon}
                    {josa(hon, '이', '가')} 바로잡아 주신 말
                  </b>{' '}
                  <span className="ph-tag">바로잡음</span>
                  <br />“{cur.elder_note}” — 다음 이야기부터 이렇게 여쭤봐요
                </span>
              </p>
            )}
            {cur.is_mine && !cur.shown ? (
              <button type="button" className="fam-btn ph-danger" onClick={() => setOpen({ id: cur.photo_id, del: true })}>
                이 사진 빼기
              </button>
            ) : (
              cur.source === 'FAMILY' &&
              cur.shown && <p className="ph-mini">이미 보여 드린 사진은 {hon} 사진첩에 남아요.</p>
            )}
            <button type="button" className="fam-btn fam-btn--tonal" onClick={close} autoFocus>
              닫기
            </button>
          </div>
        </>
      )}

      {cur && edit && (
        <>
          <button type="button" className="fam-scrim" aria-label="닫기" onClick={() => !busy && setEdit(undefined)} />
          <div
            className="fam-sheet ph-sheet"
            role="dialog"
            aria-modal="true"
            aria-label="설명 고치기"
            aria-busy={busy}
            onKeyDown={(e) => e.key === 'Escape' && !busy && setEdit(undefined)}
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
            {!cur.taken_at && (
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
              <button type="button" className="fam-btn fam-btn--tonal" disabled={busy} onClick={() => (setSheetError(''), setEdit(undefined))}>
                취소
              </button>
              <button type="button" className="fam-btn fam-btn--primary" disabled={busy} onClick={() => saveNote(cur)}>
                {busy ? '저장 중…' : '저장'}
              </button>
            </div>
          </div>
        </>
      )}

      {cur && open?.del && (
        <>
          <button type="button" className="fam-scrim" aria-label="닫기" onClick={() => !busy && setOpen({ id: cur.photo_id, del: false })} />
          <div
            className="fam-sheet ph-sheet"
            role="dialog"
            aria-modal="true"
            aria-label="사진을 뺄까요?"
            aria-busy={busy}
            onKeyDown={(e) => e.key === 'Escape' && !busy && setOpen({ id: cur.photo_id, del: false })}
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
              <button
                type="button"
                className="fam-btn fam-btn--tonal"
                disabled={busy}
                onClick={() => (setSheetError(''), setOpen({ id: cur.photo_id, del: false }))}
                autoFocus
              >
                취소
              </button>
              <button type="button" className="fam-btn ph-danger" disabled={busy} onClick={() => remove(cur)}>
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
