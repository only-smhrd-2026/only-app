/** ELDER_TODAY_001 — 홈 위에 뜨는 오늘의 한 장 시트. */
import type { ElderHomeOut } from '../../api/types'
import todayHandle from '../../assets/today-handle.svg'
import './ELDER_TODAY_001.css'

type Props = {
  home: ElderHomeOut
  busy: boolean
  error?: string
  preview: boolean
  onTalk: () => void
  onSkip: () => void
}

export default function ELDER_TODAY_001({ home, busy, error, preview, onTalk, onSkip }: Props) {
  const photo = home.today_pick
  if (!photo) return null

  return (
    <div className="elder-today-overlay">
      <section className="elder-today-sheet" role="dialog" aria-modal="true" aria-labelledby="elder-today-title">
        <img className="elder-today-handle" src={todayHandle} alt="" />
        <h1 id="elder-today-title">오늘의 한 장이 왔어요</h1>
        <div className="elder-today-photo-wrap">
          <img className="elder-today-photo" src={photo.photo_url} alt="가족이 올린 오늘의 사진" />
          <p className="elder-today-prompt">이 사진, 어떠세요?</p>
          <span className="elder-today-caption">{preview ? '첫째딸이 올린 사진' : '가족이 올린 사진'}</span>
        </div>
        {error && <p className="elder-text" role="alert">{error}</p>}
        <div className="elder-today-actions">
          <button className="elder-btn" onClick={onTalk} disabled={busy} autoFocus>
            {busy ? '잠시만요' : <>이야기<wbr />하기</>}
          </button>
          <button className="elder-btn elder-btn--secondary" onClick={onSkip} disabled={busy}>건너<wbr />뛰기</button>
        </div>
      </section>
    </div>
  )
}
