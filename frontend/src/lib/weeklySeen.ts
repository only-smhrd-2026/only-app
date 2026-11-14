/**
 * 가족 홈 '이번 주 이야기가 도착했어요' 띠 (D70): 가족방마다 마지막으로 본 주(week_start)를 폰에 적어 둔다.
 * 주간 이야기 화면(WEEKLY_001)을 열면 적고, 새 주가 오면 띠가 다시 뜬다. 못 적는 폰은 띠가 다시 뜰 뿐이다.
 */
const key = (roomId: number) => `haru.weekly.seen.${roomId}`

export function weeklySeen(roomId: number): string | null {
  try {
    return localStorage.getItem(key(roomId))
  } catch {
    return null
  }
}

export function markWeeklySeen(roomId: number, weekStart: string) {
  try {
    localStorage.setItem(key(roomId), weekStart)
  } catch {
    /* 저장을 막아 둔 폰 — 띠가 한 번 더 뜰 뿐 */
  }
}
