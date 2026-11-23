/** LOGIN_001 — 가족 시작 화면과 이메일 로그인/가입, 카카오로 시작하기(처음 온 사람은 ?mode=kakao 에서 이름·약관만). */
import '../../components/FamilyFrame.css'
import './LOGIN_001.css'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { KakaoPendingOut, ProvidersOut, UserOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import Sim from '../../components/Sim'
import { useFetch } from '../../hooks/useFetch'
import { clearFamilyDiaryDraft } from '../../lib/familyDiaryDraft'
import { clearUploadDraft } from '../../lib/uploadDraft'

type LoginScreen = 'start' | 'login' | 'signup' | 'kakao'

// 카카오 로그인은 카카오 화면에 다녀오느라 화면 이동 state 가 사라진다 → 초대 링크(/join#…)를 이 탭에만 잠깐 두고,
// 로그인이 끝나면 지운다. 주소 ? 뒤·localStorage 에는 두지 않는다 (D16)
const KAKAO_NEXT = 'haru.fam.kakao-next'

function forgetKakaoNext() {
  try { sessionStorage.removeItem(KAKAO_NEXT) } catch { /* 저장이 막힌 브라우저 */ }
}

export default function LOGIN_001() {
  const nav = useNavigate()
  const loc = useLocation()
  // 초대 링크(JOIN_001)에서 왔으면 로그인·가입 뒤 그 링크로 돌아간다. '/join#' 로 시작할 때만 — 다른 주소로는 안 보낸다.
  // 처음 한 번만 읽는다 (단계를 바꾸면 주소가 바뀌며 state 가 비워진다)
  const [after] = useState(() => {
    let next = (loc.state as { next?: unknown } | null)?.next
    try { next ??= sessionStorage.getItem(KAKAO_NEXT) } catch { /* 저장이 막힌 브라우저 */ }
    return typeof next === 'string' && next.startsWith('/join#') ? next : '/'
  })
  // 단계는 주소에 둔다(?mode=login|signup|kakao). 폰 뒤로 가기가 앱을 닫지 않고 시작 화면으로 돌아온다.
  const [params, setParams] = useSearchParams()
  const mode = params.get('mode')
  const screen: LoginScreen = mode === 'login' || mode === 'signup' || mode === 'kakao' ? mode : 'start'
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
  // 카카오로 처음 온 사람(서버가 /login?mode=kakao 로 보낸다) — 이메일·비밀번호 없이 이름·약관만 받는다
  const kakao = screen === 'kakao'
  // 단계마다 주소 기록이 남아서, 로그인한 뒤 홈에서 뒤로 가기를 하면 여기로 온다 → 이미 로그인했으면 홈으로
  // (카카오로 로그인한 사람도 서버가 여기(/login)로 보낸다 → 홈·초대 화면으로)
  const me = useFetch<UserOut>('/api/auth/me')
  const providers = useFetch<ProvidersOut>('/api/auth/providers') // 서버에 카카오 키가 있을 때만 버튼이 켜진다
  const pending = useFetch<KakaoPendingOut>(kakao ? '/api/auth/kakao/signup' : null) // 이름 칸에 미리 넣을 닉네임
  const loading = me.loading || providers.loading || pending.loading

  // 단계가 바뀌면 이메일 칸으로 초점을 옮긴다(시작 화면이면 칸이 없어 그대로).
  useEffect(() => {
    emailRef.current?.focus()
  }, [screen, loading])

  useEffect(() => {
    if (me.data) forgetKakaoNext()
  }, [me.data])

  function changeScreen(next: LoginScreen) {
    setError(undefined)
    setKakaoNotice(false)
    setParams(next === 'start' ? {} : { mode: next })
  }

  function startKakao() {
    if (!providers.data?.kakao) return setKakaoNotice(true)
    if (after !== '/') {
      try { sessionStorage.setItem(KAKAO_NEXT, after) } catch { /* 저장이 막힌 브라우저 — 로그인 뒤 홈으로 간다 */ }
    }
    window.location.href = '/api/auth/kakao/start' // 서버가 카카오 화면으로 보낸다 (화면에는 카카오 키·SDK 가 없다)
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    const join = { name: String(f.get('name')), terms_agreed: f.get('terms') === 'on' }
    const body = kakao ? join : { email: String(f.get('email')), password: String(f.get('password')), ...(signup && join) }
    setBusy(true)
    setError(undefined)
    try {
      await api(kakao ? '/api/auth/kakao/signup' : signup ? '/api/auth/signup' : '/api/auth/login', { body })
      clearUploadDraft() // 같은 창에서 앞 계정이 고르다 만 사진을 지운다 (뒤로 가기로 거슬러 가면 보이고 보낼 수 있었다)
      clearFamilyDiaryDraft() // 쓰다 만 가족 일기 글도 같은 이유
      forgetKakaoNext()
      nav(after, { replace: true })
    } catch (err) {
      setError({ screen, text: (err as ApiError).message })
      setBusy(false)
    }
  }

  if (loading) return null
  if (me.data) return <Navigate to={after} replace />
  // 가입 대기 쿠키가 없거나 10분이 지났으면(4xx) 이름을 받아도 가입이 안 된다 → 시작 화면에서 카카오부터 다시
  if (kakao && pending.error && pending.error.status >= 400 && pending.error.status < 500) return <Navigate to="/login?kakao=fail" replace />
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
          <Sim face="hello" size={120} />
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
            <button className={`login-button login-button--kakao${providers.data?.kakao ? ' on' : ''}`} type="button" onClick={startKakao}>
              {providers.data?.kakao ? '카카오로 시작하기' : '카카오로 시작하기 · 준비 중'}
            </button>
            {kakaoNotice && <p className="login-notice" role="status">카카오 로그인은 준비 중이에요. 이메일로 시작해 주세요.</p>}
            {params.get('kakao') === 'fail' && (
              <p className="login-error" role="alert">카카오 로그인이 안 됐어요. 다시 해 보시거나 이메일로 시작해 주세요.</p>
            )}
            <p className="login-policy-note">
              개인정보 처리방침 동의는 가입할 때 확인해요.<br />
              <Link to="/policy">개인정보 처리방침 보기</Link>
            </p>
          </section>
        ) : (
          <section className="login-card login-email" aria-labelledby="login-form-title">
            <h2 id="login-form-title">{kakao ? '카카오로 가입' : signup ? '가족 가입' : '가족 로그인'}</h2>
            <form className="login-form" onSubmit={submit} aria-busy={busy}>
              {kakao ? (
                <p className="login-notice">카카오로 처음 오셨어요. 이름과 약관만 확인해 주세요</p>
              ) : (
                <>
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
                </>
              )}
              {(signup || kakao) && (
                <>
                  <label>이름<input name="name" required maxLength={30} autoComplete="name" defaultValue={kakao ? pending.data?.nickname : undefined} /></label>
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
                {busy ? '잠시만요' : signup || kakao ? '가입하기' : '로그인'}
              </button>
              {!kakao && (
                <button
                  type="button"
                  className="login-button login-button--secondary"
                  disabled={busy}
                  onClick={() => changeScreen(signup ? 'login' : 'signup')}
                >
                  {signup ? '이미 계정이 있어요' : '처음이에요 (가입)'}
                </button>
              )}
            </form>
            {!signup && !kakao && (
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
