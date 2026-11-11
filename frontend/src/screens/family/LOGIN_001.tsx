/** LOGIN_001 — 가족 시작 화면과 이메일 로그인/가입. */
import './LOGIN_001.css'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import loginPreview from '../../assets/login-preview.svg'

type LoginScreen = 'start' | 'login' | 'signup'

export default function LOGIN_001() {
  const nav = useNavigate()
  const [screen, setScreen] = useState<LoginScreen>('start')
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)
  const emailOpen = screen !== 'start'
  const signup = screen === 'signup'

  function changeScreen(next: LoginScreen) {
    setError(undefined)
    setScreen(next)
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
      nav('/', { replace: true })
    } catch (err) {
      setError((err as ApiError).message)
      setBusy(false)
    }
  }

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
              <img src={loginPreview} alt="" />
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
            <form key={screen} className="login-form" onSubmit={submit} aria-busy={busy}>
              <label>이메일<input name="email" type="email" required autoComplete="email" /></label>
              <label>
                비밀번호
                <input name="password" type="password" required minLength={8} autoComplete={signup ? 'new-password' : 'current-password'} />
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
              {error && <p className="login-error" role="alert">{error}</p>}
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
