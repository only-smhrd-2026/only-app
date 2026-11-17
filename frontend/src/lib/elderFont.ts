/**
 * 어르신 글자 크기 단계(L·XL·XXL — 가족이 22·24·28 중에 고름, D51)를 <html data-font> 에 걸고 폰에도 적어 둔다.
 * 단계는 어르신 홈을 읽을 때 서버 설정으로 정해진다 — 사진첩·일기 같은 하위 화면에서 새로고침해도 같은 크기로 보이게
 * 앱을 열 때 적어 둔 값을 먼저 건다(목소리 haru.elder.voice 와 같은 방법, lib/audio.ts).
 */
const KEY = 'haru.elder.font'

export function setElderFont(step: string) {
  document.documentElement.dataset.font = step
  try {
    localStorage.setItem(KEY, step)
  } catch {
    /* 저장소를 못 쓰는 폰(사생활 모드 등) — 이번 화면에만 건다 */
  }
}

/** 앱을 열 때 한 번(main.tsx). 적어 둔 단계가 없으면 elder.css 기본(24px) */
export function restoreElderFont() {
  try {
    const step = localStorage.getItem(KEY)
    if (step) document.documentElement.dataset.font = step
  } catch {
    /* 위와 같음 */
  }
}
