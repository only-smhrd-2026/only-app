import { useLocation } from 'react-router-dom'
import '../components/FamilyFrame.css'
import '../ErrorScreen.css'

/** 등록되지 않은 주소에서는 사용자에게 홈으로 돌아가는 길만 보여 준다. */
export default function NotFound() {
  const elder = useLocation().pathname.startsWith('/elder')
  return (
    <main className={`${elder ? 'elder' : 'fam'} screen-safety`}>
      <div className={`${elder ? '' : 'fam-card '}screen-safety__content`}>
        <h1 className={elder ? 'elder-text elder-text--lg' : 'screen-safety__title'}>없는 화면이에요</h1>
        <button
          type="button"
          className={elder ? 'elder-btn' : 'fam-btn fam-btn--primary fam-btn--block'}
          onClick={() => window.location.assign(elder ? '/elder' : '/')}
        >
          처음으로
        </button>
      </div>
    </main>
  )
}
