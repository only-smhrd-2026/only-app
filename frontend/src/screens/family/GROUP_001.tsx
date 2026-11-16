/**
 * GROUP_001 — 새 가족방 만들기 (FR-AD-002, 목업 ⑥).
 * 기존 가족방 선택은 FamilyFrame이 맡고, 만든 뒤 새 방의 시작 홈으로 간다.
 */
import { useRef, useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { RelationTag, RoomOut, UserOut } from '../../api/types'
import { useFetch } from '../../hooks/useFetch'
import './GROUP_001.css'

const RELATIONS: [RelationTag, string][] = [
  ['CHILD', '자녀'],
  ['GRANDCHILD', '손주'],
  ['OTHER', '기타'],
]

/** 어르신과의 관계 칩 3개 — JOIN_001 도 같이 쓴다. value 가 없으면 아무것도 안 고른 상태 */
export function RelationChips({ value, onChange }: { value?: RelationTag; onChange: (v: RelationTag) => void }) {
  return (
    <fieldset className="chips">
      <legend>어르신과의 관계</legend>
      <div className="row">
        {RELATIONS.map(([tag, label]) => (
          <label key={tag} className="chip">
            <input type="radio" name="relation_tag" value={tag} checked={value === tag} onChange={() => onChange(tag)} />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

export default function GROUP_001() {
  const nav = useNavigate()
  const me = useFetch<UserOut>('/api/auth/me')
  const [name, setName] = useState('')
  const [honorific, setHonorific] = useState('할머니')
  const [custom, setCustom] = useState(false)
  const [relation, setRelation] = useState<RelationTag>()
  const [nickname, setNickname] = useState('')
  const [busy, setBusy] = useState(false)
  const sending = useRef(false)
  const [error, setError] = useState<string>()
  const elderName = name.trim()
  const elderHonorific = honorific.trim()
  const nameLength = [...elderName].length
  const valid = nameLength >= 1 && nameLength <= 10 && elderHonorific.length > 0
    && [...elderHonorific].length <= 20 && !!relation && [...nickname.trim()].length <= 12

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (sending.current || !valid) return
    sending.current = true // 같은 순간 두 번 제출해도 요청은 한 번만
    setBusy(true)
    setError(undefined)
    try {
      const created = await api<RoomOut>('/api/rooms', {
        method: 'POST',
        body: {
          elder_name: elderName,
          elder_honorific: elderHonorific,
          relation_tag: relation,
          nickname: nickname.trim() || null,
        },
      })
      try {
        // FamilyFrame.tsx의 ROOM_KEY와 같은 칸. 하위 화면에서 홈으로 가면 틀이 새로 읽는다.
        localStorage.setItem('haru.fam.room', String(created.room_id))
      } catch {
        // 저장이 차단돼도 생성 완료를 실패로 알려 같은 방을 다시 만들게 하지 않는다.
      }
      nav('/', { replace: true })
    } catch (err) {
      setError((err as ApiError).message)
      setBusy(false)
      sending.current = false
    }
  }

  if (me.error?.status === 401) return <Navigate to="/login" replace />
  if (me.error) {
    return (
      <main className="newroom-screen newroom-status">
        <h1>새 가족방</h1>
        <p className="newroom-error" role="alert">{me.error.message}</p>
        <button className="fam-btn fam-btn--primary" onClick={me.reload}>다시 시도</button>
      </main>
    )
  }
  if (!me.data) return <main className="newroom-screen newroom-status"><p role="status">불러오는 중…</p></main>

  return (
    <main className="newroom-screen">
      <header className="newroom-heading">
        <h1>어느 분의 가족방인가요?</h1>
        <p>어르신 한 분마다 가족방이 하나예요</p>
      </header>
      <form className="newroom-form" onSubmit={submit} aria-busy={busy}>
        <fieldset className="newroom-fields" disabled={busy}>
          <legend className="newroom-sr-only">새 가족방 정보</legend>
          <div className="newroom-field">
            <label htmlFor="newroom-name">어르신 이름</label>
            <input id="newroom-name" name="elder_name" value={name} onChange={(e) => setName(e.target.value)}
              placeholder="예: 영자" required aria-describedby="newroom-name-help" aria-invalid={nameLength > 10} />
            <p id="newroom-name-help" className={nameLength > 10 ? 'newroom-error' : 'newroom-fine'}
              aria-live="polite">{nameLength > 10 ? '어르신 이름은 10자까지 입력해 주세요.' : '어르신 이름을 1~10자로 입력해 주세요.'}</p>
          </div>
          <fieldset className="newroom-field newroom-choice">
            <legend>부르는 말</legend>
            <div className="newroom-chips">
              {['할머니', '할아버지', '어르신', '직접 쓰기'].map((label) => (
                <label className="newroom-chip" key={label}>
                  <input type="radio" name="honorific_choice" value={label}
                    checked={label === '직접 쓰기' ? custom : !custom && honorific === label}
                    onChange={() => { setCustom(label === '직접 쓰기'); setHonorific(label === '직접 쓰기' ? '' : label) }} />
                  {label}
                </label>
              ))}
            </div>
            {custom && <>
              <label className="newroom-sr-only" htmlFor="newroom-honorific">직접 쓴 부르는 말</label>
              <input id="newroom-honorific" name="elder_honorific" value={honorific}
                onChange={(e) => setHonorific(e.target.value)} maxLength={20} placeholder="예: 어머님 (20자까지)" required
                aria-describedby="newroom-honorific-help" />
              <p id="newroom-honorific-help" className="newroom-sr-only">부르는 말을 1~20자로 입력해 주세요.</p>
            </>}
            <p className="newroom-fine" aria-live="polite">심심이가 "{elderName || '영자'} {elderHonorific || '어르신'}"라고 불러요</p>
          </fieldset>
          <fieldset className="newroom-field newroom-choice">
            <legend>어르신과 나의 관계</legend>
            <div className="newroom-chips">
              {RELATIONS.map(([tag, label]) => (
                <label className="newroom-chip" key={tag}>
                  <input type="radio" name="relation_tag" value={tag} checked={relation === tag} required
                    onChange={() => setRelation(tag)} />
                  {label}
                </label>
              ))}
            </div>
            <label className="newroom-nickname-label" htmlFor="newroom-nickname">어르신이 나를 부르는 말 <small>(선택 · 12자까지)</small></label>
            <input id="newroom-nickname" name="nickname" value={nickname} onChange={(e) => setNickname(e.target.value)}
              maxLength={12} placeholder="예: 큰딸" aria-describedby="newroom-nickname-help" />
            <p id="newroom-nickname-help" className="newroom-sr-only">12자까지 입력할 수 있어요.</p>
          </fieldset>
        </fieldset>
        <div className="newroom-footer">
          {error && <p className="newroom-error" role="alert">{error}</p>}
          <button className="fam-btn fam-btn--primary fam-btn--block" disabled={busy || !valid}>
            {busy ? '만드는 중…' : '가족방 만들기'}
          </button>
        </div>
      </form>
    </main>
  )
}
