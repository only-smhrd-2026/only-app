/**
 * JOIN_001 — 가족방 참여 (FR-AD-005, 이슈 #24). 방장이 보낸 /join#<토큰> 으로 들어온다.
 * 토큰은 # 뒤에서 읽어 요청 본문으로만 보낸다 (D16 — 주소 ? 뒤·console·localStorage 에 남기지 않는다).
 * 로그인 안 했으면 로그인 뒤 링크를 다시 누르게 안내한다 (자동으로 돌아오기는 LOGIN_001 을 고쳐야 해서 아직 안 함).
 * 대표 사진·초대한 사람·구성원 수는 서버(InviteStatusOut)가 주지 않아 넣지 않는다.
 */
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { InviteStatusOut, RelationTag, RoomOut, UserOut } from '../../api/types'
import { useFetch } from '../../hooks/useFetch'
import { RelationChips } from './GROUP_001'
import './GROUP_001.css'

export default function JOIN_001() {
  const nav = useNavigate()
  const token = window.location.hash.slice(1)
  const [status, setStatus] = useState<InviteStatusOut>()
  const [statusError, setStatusError] = useState(token ? '' : '링크가 올바르지 않아요. 방장에게 다시 받아 주세요.')
  const [tries, setTries] = useState(0)
  const [canRetry, setCanRetry] = useState(false) // 연결이 끊겼을 때만 — 없는·끝난 링크(4xx)는 다시 해도 같다
  const me = useFetch<UserOut>('/api/auth/me')
  const [name, setName] = useState<string>() // 손대기 전에는 /api/auth/me 의 이름
  const [relation, setRelation] = useState<RelationTag>()
  const [nickname, setNickname] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [loggedOut, setLoggedOut] = useState(false)

  useEffect(() => {
    if (!token) return
    api<InviteStatusOut>('/api/invites/status', { body: { token } })
      .then(setStatus)
      .catch((e: ApiError) => {
        setStatusError(e.message)
        setCanRetry(e.status === 0 || e.status >= 500)
      })
  }, [token, tries])

  const myName = (name ?? me.data?.name ?? '').trim()
  const nick = nickname.trim()

  async function accept(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (busy || !relation || !myName) return
    setBusy(true)
    setError('')
    try {
      await api<RoomOut>('/api/invites/accept', {
        body: { token, name: myName, relation_tag: relation, nickname: nick || null },
      })
      nav('/', { replace: true }) // replace — 뒤로 가기로 초대 링크에 돌아오지 않게
    } catch (err) {
      const apiErr = err as ApiError
      if (apiErr.status === 401) setLoggedOut(true)
      else setError(apiErr.message)
      setBusy(false)
    }
  }

  const invite = status?.valid && status.kind === 'FAMILY' ? status : undefined

  return (
    <main className="page fam-skin">
      <h1>가족방 참여</h1>
      {statusError && <p className="error" role="alert">{statusError}</p>}
      {canRetry && (
        <button
          className="btn secondary"
          onClick={() => { setStatusError(''); setCanRetry(false); setTries((n) => n + 1) }}
        >
          다시 시도
        </button>
      )}
      {!status && !statusError && <p className="muted">불러오는 중…</p>}
      {status && !invite && <p>이 링크는 더 쓸 수 없어요. 방장에게 새 링크를 받아 주세요.</p>}
      {invite && (
        <>
          <section className="card">
            <p><strong>{invite.elder_name} 님 가족방에 초대받았어요</strong></p>
          </section>
          {loggedOut || me.error?.status === 401 ? (
            <section className="card">
              <p>먼저 로그인(처음이면 가입)한 뒤, 받은 초대 링크를 다시 눌러 주세요.</p>
              <Link className="btn" to="/login">로그인하러 가기</Link>
            </section>
          ) : me.error ? (
            <section className="card">
              <p className="error">{me.error.message}</p>
              <button className="btn" onClick={me.reload}>다시 시도</button>
            </section>
          ) : !me.data ? (
            <p className="muted">불러오는 중…</p>
          ) : (
            <form className="form card" onSubmit={accept}>
              <label>내 이름
                <input value={name ?? me.data.name} onChange={(e) => setName(e.target.value)} required maxLength={10} />
              </label>
              <RelationChips value={relation} onChange={setRelation} />
              <label>호칭 (선택)
                <input value={nickname} onChange={(e) => setNickname(e.target.value)} maxLength={12} placeholder="예: 큰딸" />
              </label>
              <p className="muted">어르신께는 '{nick ? `${nick} ${myName}` : myName}' 소식으로 읽어 드려요</p>
              {error && <p className="error" role="alert">{error}</p>}
              <button className="btn" disabled={busy || !relation || !myName}>
                {busy ? '들어가는 중…' : '가족방 들어가기'}
              </button>
            </form>
          )}
        </>
      )}
    </main>
  )
}
