import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import './OfflineBar.css'

export default function OfflineBar() {
  const [online, setOnline] = useState(() => navigator.onLine)
  const { pathname } = useLocation()

  useEffect(() => {
    const updateOnline = () => setOnline(navigator.onLine)
    window.addEventListener('online', updateOnline)
    window.addEventListener('offline', updateOnline)
    updateOnline()

    return () => {
      window.removeEventListener('online', updateOnline)
      window.removeEventListener('offline', updateOnline)
    }
  }, [])

  if (online) return null

  return (
    <div className={`offline-bar${pathname.startsWith('/elder') ? ' offline-bar--elder' : ''}`} role="status">
      인터넷이 끊겼어요. 연결되면 다시 해 주세요
    </div>
  )
}
