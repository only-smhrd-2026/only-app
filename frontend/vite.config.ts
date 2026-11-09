import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 개발: /api 는 FastAPI(8000)로 프록시 → 단일 오리진, CORS 없음 (D7).
// changeOrigin:false 라 Host 가 localhost:5173 으로 유지되어 서버가 만드는 초대 링크가 화면 주소로 나온다.
// 폰 테스트: adb reverse tcp:5173 tcp:5173 뒤 폰 Chrome 에서 http://localhost:5173 (README 「폰에서 테스트」).
export default defineConfig({
  plugins: [react()],
  server: {
    // 127.0.0.1 고정: Windows adb reverse 는 127.0.0.1 로만 붙는데 Vite 기본값은 [::1] 에만 열린다. LAN 에는 열지 않음.
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
})
