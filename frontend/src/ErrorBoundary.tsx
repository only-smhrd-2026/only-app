import { Component, type ReactNode } from 'react'
import './components/FamilyFrame.css'
import './ErrorScreen.css'

/** 화면 오류가 나도 홈으로 다시 나갈 수 있게 한다. 오류 내용은 보관하거나 화면에 표시하지 않는다. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  render() {
    if (!this.state.hasError) return this.props.children

    const elder = window.location.pathname.startsWith('/elder')
    return (
      <main className={`${elder ? 'elder' : 'fam'} screen-safety`}>
        <div className={`${elder ? '' : 'fam-card '}screen-safety__content`}>
          <h1 className={elder ? 'elder-text elder-text--lg' : 'screen-safety__title'}>잠시 문제가 생겼어요</h1>
          <button
            type="button"
            className={elder ? 'elder-btn' : 'fam-btn fam-btn--primary fam-btn--block'}
            onClick={() => window.location.assign(elder ? '/elder' : '/')}
          >
            다시 열기
          </button>
        </div>
      </main>
    )
  }
}
