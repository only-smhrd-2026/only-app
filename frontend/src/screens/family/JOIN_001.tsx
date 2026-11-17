/**
 * JOIN_001 — 가족방 참여 (FR-AD-005, 이슈 #24). 방장이 보낸 /join#<토큰> 으로 들어온다.
 * 토큰은 # 뒤에서 읽어 요청 본문으로만 보낸다 (D16 — 주소 ? 뒤·console·localStorage 에 남기지 않는다).
 * 로그인 안 했으면 로그인 화면으로 보내고, 로그인·가입이 끝나면 LOGIN_001 이 이 링크로 다시 데려온다
 * (주소는 화면 이동 state 로만 넘긴다 — ? 뒤에 토큰을 두지 않는다).
 * 대표 사진·초대한 사람·구성원 수는 서버(InviteStatusOut)가 주지 않아 넣지 않는다.
 */
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { InviteStatusOut, RelationTag, RoomOut, UserOut } from '../../api/types'
import { useFetch } from '../../hooks/useFetch'
import '../../components/FamilyFrame.css'
import './JOIN_001.css'

const RELATIONS: [RelationTag, string][] = [
  ['CHILD', '자녀'],
  ['GRANDCHILD', '손주'],
  ['OTHER', '기타'],
]

/** ELDER_FAMILY_001과 같은 받침 검사 — '지민이', '민서가' */
function subjectParticle(word: string) {
  const code = word.charCodeAt(word.length - 1)
  return code >= 0xac00 && code <= 0xd7a3 && (code - 0xac00) % 28 !== 0 ? '이' : '가'
}

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
  // 어르신 가족 소식의 sender와 동일하게 호칭 다음에 이름을 붙인다.
  const sender = [nick, myName].filter(Boolean).join(' ') || '가족'

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
    <main className="fam join-page">
      <header className="join-heading">
        <h1>가족방에 들어가기</h1>
        <p>어르신께 내 소식을 어떻게 읽어 드릴지 정해요</p>
      </header>
      {statusError && <p className="join-error" role="alert">{statusError}</p>}
      {canRetry && (
        <button
          className="join-button join-button--secondary"
          onClick={() => { setStatusError(''); setCanRetry(false); setTries((n) => n + 1) }}
        >
          다시 시도
        </button>
      )}
      {!status && !statusError && <p className="join-muted" role="status">불러오는 중…</p>}
      {status && !invite && <p role="alert">이 링크는 더 쓸 수 없어요. 방장에게 새 링크를 받아 주세요.</p>}
      {invite && (
        <>
          <section className="join-room" aria-label="초대받은 가족방">
            <span className="join-avatar" aria-hidden="true">{invite.elder_name.slice(0, 1)}</span>
            <div>
              <strong>{invite.elder_name} 님 가족방</strong>
              <p>가족방에 초대받았어요</p>
            </div>
          </section>
          {loggedOut || me.error?.status === 401 ? (
            <section className="join-notice">
              <p>먼저 로그인(처음이면 가입)해 주세요. 끝나면 이 화면으로 돌아와요.</p>
              <Link className="join-button" to="/login" state={{ next: `/join#${token}` }}>로그인하러 가기</Link>
            </section>
          ) : me.error ? (
            <section className="join-notice">
              <p className="join-error" role="alert">{me.error.message}</p>
              <button className="join-button" onClick={me.reload}>다시 시도</button>
            </section>
          ) : !me.data ? (
            <p className="join-muted" role="status">불러오는 중…</p>
          ) : (
            <form className="join-form" onSubmit={accept} aria-busy={busy}>
              <fieldset className="join-fields" disabled={busy}>
                <label className="join-field">내 이름
                  <input autoComplete="name" value={name ?? me.data.name} onChange={(e) => setName(e.target.value)} required maxLength={10} />
                </label>
                <fieldset className="join-relations">
                  <legend>어르신과의 관계 <span className="join-required">필수</span></legend>
                  <div className="join-chips">
                    {RELATIONS.map(([tag, label]) => (
                      <label className="join-chip" key={tag}>
                        <input type="radio" name="relation_tag" value={tag} checked={relation === tag} onChange={() => setRelation(tag)} required />
                        <span>{label}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
                <label className="join-field">
                  <span>어르신이 나를 부르는 말 <small>선택</small></span>
                  <input value={nickname} onChange={(e) => setNickname(e.target.value)} maxLength={12} placeholder="예: 둘째 손주" aria-describedby="join-nickname-help" />
                  <small id="join-nickname-help">12자까지 쓸 수 있어요</small>
                </label>
                <section className="join-readout" aria-label="첫 문장 미리 보기">
                  <h2>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M4 9.5v5h3.2L12 18.5v-13L7.2 9.5zM15.5 9a4.2 4.2 0 0 1 0 6M18.3 6.3a8 8 0 0 1 0 11.4" />
                    </svg>
                    어르신께 이렇게 읽어 드려요
                  </h2>
                  <p aria-live="polite">“{sender}{subjectParticle(sender)} 사진 일기를 보냈어요. 읽어 드릴게요.”</p>
                </section>
              </fieldset>
              {error && <p className="join-error" role="alert">{error}</p>}
              <div className="join-actions">
                <button className="join-button" disabled={busy || !relation || !myName}>
                  {busy ? '들어가는 중…' : '가족방 들어가기'}
                </button>
              </div>
            </form>
          )}
        </>
      )}
    </main>
  )
}
