import { Link } from 'react-router-dom'

/** 아직 안 만든 화면. 화면 ID 와 제목만 보여 준다 (배관 확인용). */
export default function NotYet({ id, title }: { id: string; title: string }) {
  return (
    <main className="page">
      <h1>{title}</h1>
      <p className="muted">
        화면 ID <b>{id}</b> — 준비 중이에요. 화면설계서를 보고 <code>frontend/src/screens/</code> 에 같은 이름의 파일을 만들어
        <code>App.tsx</code> 표의 Screen 칸에 넣으면 여기에 나와요.
      </p>
      <p>
        <Link to="/">가족 홈</Link> · <Link to="/elder">어르신 홈</Link>
      </p>
    </main>
  )
}
