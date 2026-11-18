/** LOGIN_001 — 가족 시작 화면과 이메일 로그인/가입. */
import '../../components/FamilyFrame.css'
import './LOGIN_001.css'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { UserOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import { useFetch } from '../../hooks/useFetch'
import { clearFamilyDiaryDraft } from '../../lib/familyDiaryDraft'
import { clearUploadDraft } from '../../lib/uploadDraft'

type LoginScreen = 'start' | 'login' | 'signup'

export default function LOGIN_001() {
  const nav = useNavigate()
  const loc = useLocation()
  // 초대 링크(JOIN_001)에서 왔으면 로그인·가입 뒤 그 링크로 돌아간다. '/join#' 로 시작할 때만 — 다른 주소로는 안 보낸다.
  // 처음 한 번만 읽는다 (단계를 바꾸면 주소가 바뀌며 state 가 비워진다)
  const [after] = useState(() => {
    const next = (loc.state as { next?: unknown } | null)?.next
    return typeof next === 'string' && next.startsWith('/join#') ? next : '/'
  })
  // 단계는 주소에 둔다(?mode=login|signup). 폰 뒤로 가기가 앱을 닫지 않고 시작 화면으로 돌아온다.
  const [params, setParams] = useSearchParams()
  const mode = params.get('mode')
  const screen: LoginScreen = mode === 'login' || mode === 'signup' ? mode : 'start'
  // 오류는 난 단계와 함께 둔다. 뒤로 가기로 단계가 바뀌면 안 보인다.
  const [error, setError] = useState<{ screen: LoginScreen; text: string }>()
  const [busy, setBusy] = useState(false)
  const [kakaoNotice, setKakaoNotice] = useState(false)
  const [passwordVisibility, setPasswordVisibility] = useState({ screen, shown: false })
  const showPassword = passwordVisibility.screen === screen && passwordVisibility.shown
  // 주소의 단계가 바뀌면(폰 뒤로 가기 포함) 이전 단계의 보기 상태를 버린다.
  if (passwordVisibility.screen !== screen) {
    setPasswordVisibility({ screen, shown: false })
  }
  const emailRef = useRef<HTMLInputElement>(null)
  const emailOpen = screen !== 'start'
  const signup = screen === 'signup'
  // 단계마다 주소 기록이 남아서, 로그인한 뒤 홈에서 뒤로 가기를 하면 여기로 온다 → 이미 로그인했으면 홈으로
  const me = useFetch<UserOut>('/api/auth/me')

  // 단계가 바뀌면 이메일 칸으로 초점을 옮긴다(시작 화면이면 칸이 없어 그대로).
  useEffect(() => {
    emailRef.current?.focus()
  }, [screen, me.loading])

  function changeScreen(next: LoginScreen) {
    setError(undefined)
    setKakaoNotice(false)
    setParams(next === 'start' ? {} : { mode: next })
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    const body = {
      email: String(f.get('email')),
      password: String(f.get('password')),
      ...(signup && { name: String(f.get('name')), terms_agreed: f.get('terms') === 'on' }),
    }
    setBusy(true)
    setError(undefined)
    try {
      await api(signup ? '/api/auth/signup' : '/api/auth/login', { body })
      clearUploadDraft() // 같은 창에서 앞 계정이 고르다 만 사진을 지운다 (뒤로 가기로 거슬러 가면 보이고 보낼 수 있었다)
      clearFamilyDiaryDraft() // 쓰다 만 가족 일기 글도 같은 이유
      nav(after, { replace: true })
    } catch (err) {
      setError({ screen, text: (err as ApiError).message })
      setBusy(false)
    }
  }

  if (me.loading) return null
  if (me.data) return <Navigate to={after} replace />
  return (
    <main className="fam login-screen">
      <div className={`login-shell${emailOpen ? ' login-shell--email' : ''}`}>
        {after !== '/' && (
          <div className="login-invite">
            <FamIcon name="family" />
            <span><b>가족방 초대를 받으셨어요</b><br />로그인하거나 가입한 뒤 초대를 확인해 주세요.</span>
          </div>
        )}
        <header className="login-brand">
          <svg className="login-logo" viewBox="0 0 40 40" aria-hidden="true">
            <g transform="rotate(-8 20 20)">
              <rect x="6" y="9" width="28" height="22" rx="5" fill="currentColor" />
              <circle cx="14.5" cy="16.5" r="3" fill="var(--surface)" />
              <path d="M9 27l8-7 5 4.5 4-3 5 5.5z" fill="var(--surface)" />
            </g>
          </svg>
          <h1>하루한장</h1>
          <p>가족 사진 한 장으로<br />매일 어르신께 말을 걸어요</p>
        </header>
        {!emailOpen ? (
          <section className="login-card login-start" aria-label="시작하기">
            <p className="login-intro">
              사진 한 장으로 이어지는<br /><b>우리 가족의 하루</b>
            </p>
            <button className="login-button" type="button" onClick={() => changeScreen('login')}>
              이메일로 시작하기
            </button>
            <button className="login-button login-button--kakao" type="button" onClick={() => setKakaoNotice(true)}>
              카카오로 시작하기 · 준비 중
            </button>
            {kakaoNotice && <p className="login-notice" role="status">카카오 로그인은 준비 중이에요. 이메일로 시작해 주세요.</p>}
            <p className="login-policy-note">
              개인정보 처리방침 동의는 가입할 때 확인해요.<br />
              <Link to="/policy">개인정보 처리방침 보기</Link>
            </p>
          </section>
        ) : (
          <section className="login-card login-email" aria-labelledby="login-form-title">
            <h2 id="login-form-title">{signup ? '가족 가입' : '가족 로그인'}</h2>
            <form className="login-form" onSubmit={submit} aria-busy={busy}>
              <label>이메일<input ref={emailRef} name="email" type="email" required autoComplete="email" /></label>
              <div className="login-password-field">
                <label htmlFor="login-password">비밀번호</label>
                <div className="login-password-control">
                  {/* 로그인↔가입을 바꾸면 이메일은 두고 비밀번호만 비운다(key 로 새로 만든다). */}
                  <input id="login-password" key={screen} name="password" type={showPassword ? 'text' : 'password'} required minLength={8} autoComplete={signup ? 'new-password' : 'current-password'} autoCapitalize="none" autoCorrect="off" spellCheck={false} />
                  <button
                    className="login-password-toggle"
                    type="button"
                    aria-controls="login-password"
                    aria-pressed={showPassword}
                    onClick={() => setPasswordVisibility({ screen, shown: !showPassword })}
                  >
                    {showPassword ? '숨기기' : '보기'}
                  </button>
                </div>
              </div>
              {signup && (
                <>
                  <label>이름<input name="name" required maxLength={30} autoComplete="name" /></label>
                  <div className="login-terms-row">
                    <label className="login-terms">
                      <input name="terms" type="checkbox" required />
                      <span>개인정보 처리방침에 동의해요</span>
                    </label>
                    <Link className="login-policy-link" to="/policy" aria-label="개인정보 처리방침 보기">보기</Link>
                  </div>
                </>
              )}
              {error?.screen === screen && <p className="login-error" role="alert">{error.text}</p>}
              <button className="login-button" disabled={busy}>
                {busy ? '잠시만요' : signup ? '가입하기' : '로그인'}
              </button>
              <button
                type="button"
                className="login-button login-button--secondary"
                disabled={busy}
                onClick={() => changeScreen(signup ? 'login' : 'signup')}
              >
                {signup ? '이미 계정이 있어요' : '처음이에요 (가입)'}
              </button>
            </form>
            {!signup && (
              <details className="login-password-help">
                <summary>비밀번호를 잊었어요</summary>
                <p>비밀번호는 찾을 수 없어요(메일을 보내지 않는 서비스예요). 새 이메일로 가입한 뒤 방장에게 초대 링크를 다시 받아 주세요.</p>
              </details>
            )}
            <button className="login-back" type="button" disabled={busy} onClick={() => changeScreen('start')}>
              처음 화면으로
            </button>
          </section>
        )}
      </div>
    </main>
  )
}
