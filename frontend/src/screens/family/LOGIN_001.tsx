/** LOGIN_001 — 가족 로그인/가입 (이메일). 디자인 없음 (김승희 교체). 카카오는 2순위. */
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'

export default function LOGIN_001() {
  const nav = useNavigate()
  const [signup, setSignup] = useState(false)
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)

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
    <main className="page">
      <h1>{signup ? '가족 가입' : '가족 로그인'}</h1>
      <form className="form card" onSubmit={submit}>
        <label>이메일<input name="email" type="email" required autoComplete="email" /></label>
        <label>비밀번호<input name="password" type="password" required minLength={8} autoComplete="current-password" /></label>
        {signup && (
          <>
            <label>이름<input name="name" required maxLength={30} /></label>
            <label className="row"><input name="terms" type="checkbox" required /> 개인정보 처리방침에 동의해요</label>
          </>
        )}
        {error && <p className="error">{error}</p>}
        <button className="btn" disabled={busy}>{signup ? '가입하기' : '로그인'}</button>
        <button type="button" className="btn secondary" onClick={() => setSignup(!signup)}>
          {signup ? '이미 계정이 있어요' : '처음이에요 (가입)'}
        </button>
      </form>
      <p className="muted">테스트 계정: test@haru.local / test1234 (README 참고)</p>
    </main>
  )
}
