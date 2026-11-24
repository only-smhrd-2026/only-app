/**
 * 가족 로그아웃 — 바꾸기 판(FamilyFrame)·가족방 탭(GROUP_002)·가족방 없는 홈(HOME_001)이 함께 쓴다 (11/24 실사용: 로그아웃을 못 찾음).
 */
import type { NavigateFunction } from 'react-router-dom'
import { api } from '../api/client'
import { clearFamilyDiaryDraft } from './familyDiaryDraft'
import { disablePush } from './push'
import { clearUploadDraft } from './uploadDraft'

export async function logout(nav: NavigateFunction) {
  await disablePush().catch(() => {}) // 이 브라우저로 가던 폰 알림을 끈다 — 로그인이 풀리기 전에(내 구독만 지울 수 있다)
  await api('/api/auth/logout', { method: 'POST' }).catch(() => {})
  clearUploadDraft() // 고르다 만 사진을 다음 사람에게 남기지 않는다
  clearFamilyDiaryDraft() // 쓰다 만 가족 일기 글도
  nav('/login', { replace: true })
}
