/** LOGIN_001 — 가족 시작 화면과 이메일 로그인/가입. */
import './LOGIN_001.css'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { UserOut } from '../../api/types'
import loginPreview from '../../assets/login-preview.svg'
import { useFetch } from '../../hooks/useFetch'
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
      nav(after, { replace: true })
    } catch (err) {
      setError({ screen, text: (err as ApiError).message })
      setBusy(false)
    }
  }

  if (me.loading) return null
  if (me.data) return <Navigate to={after} replace />
  return (
    <main className="login-screen">
      <div className={`login-shell${emailOpen ? ' login-shell--email' : ''}`}>
        <header className="login-brand">
          <h1>하루한장</h1>
          <p>가족 사진으로 매일 이야기 나눠요</p>
        </header>
        {!emailOpen ? (
          <>
            <div className="login-preview">
              <img src={loginPreview} alt="" width={312} height={203} />
            </div>
            <p className="login-intro">
              <span>가족과 함께 추억을 나눠요<br />사진 한 장으로 매일 이야기해요</span>
            </p>
            <button className="login-button login-start" type="button" onClick={() => changeScreen('login')}>
              이메일로 시작하기
            </button>
            <p className="login-policy-note">
              개인정보 처리방침 동의는<br />가입 화면에서 확인해 주세요
            </p>
          </>
        ) : (
          <section className="login-email" aria-labelledby="login-form-title">
            <h2 id="login-form-title">{signup ? '가족 가입' : '가족 로그인'}</h2>
            <form className="login-form" onSubmit={submit} aria-busy={busy}>
              <label>이메일<input ref={emailRef} name="email" type="email" required autoComplete="email" /></label>
              <label>
                비밀번호
                {/* 로그인↔가입을 바꾸면 이메일은 두고 비밀번호만 비운다(key 로 새로 만든다). */}
                <input key={screen} name="password" type="password" required minLength={8} autoComplete={signup ? 'new-password' : 'current-password'} />
              </label>
              {signup && (
                <>
                  <label>이름<input name="name" required maxLength={30} autoComplete="name" /></label>
                  <label className="login-terms">
                    <input name="terms" type="checkbox" required />
                    <span>개인정보 처리방침에 동의해요</span>
                  </label>
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
            <button className="login-back" type="button" disabled={busy} onClick={() => changeScreen('start')}>
              처음 화면으로
            </button>
          </section>
        )}
      </div>
    </main>
  )
}
