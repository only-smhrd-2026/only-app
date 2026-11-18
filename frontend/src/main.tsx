import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
// 공통 CSS 를 먼저 — 화면 CSS(App 아래 화면들이 import)가 뒤에 와야 같은 세기의 규칙에서 화면 쪽이 이긴다
import './index.css'
import './elder.css'
import App from './App.tsx'
import ErrorBoundary from './ErrorBoundary.tsx'
import OfflineBar from './components/OfflineBar.tsx'
import { restoreElderFont } from './lib/elderFont'

restoreElderFont() // 어르신 하위 화면에서 새로고침해도 가족이 고른 글자 크기로 (lib/elderFont)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <ErrorBoundary>
        <OfflineBar />
        <App />
      </ErrorBoundary>
    </BrowserRouter>
  </StrictMode>,
)

// PWA: 홈 화면 설치용 서비스 워커 (public/sw.js). API 는 캐시하지 않는다.
import './lib/installPrompt'

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {})
}
