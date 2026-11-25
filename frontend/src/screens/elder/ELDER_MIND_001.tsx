/**
 * ELDER_MIND_001 — 내 마음 (11/23 시안 e-mind). 홈의 '내 마음' 칸에서 온다.
 * 위: 요즘 마음 카드(마지막 PHQ-8·9 결과의 얼굴·말, 누르면 읽어 줌) + 지난 마음 줄(PHQ 최근 5번).
 * 아래 '해 볼 것': 체크 5가지(PHQ-8 기본 — 할 차례면 노랑·'할 차례', PHQ-9 자세히, UCLA-3, GAD-7, SMCQ) + 기억력 놀이.
 * 점수는 보이지 않는다(NFR-DE-003). 지난 기록은 GET /api/elder/mood-history (최근 10개, 얼굴·말만). 목록이라 스크롤 허용.
 */
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { ElderHomeOut, MoodHistoryOut } from '../../api/types'
import { IC } from '../../components/ElderUi'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { say, stopSpeaking } from '../../lib/audio'
import { CHECKS, type CheckKind } from '../../lib/moodCheck'
import './ELDER_MIND_001.css'

type Item = MoodHistoryOut['items'][number]
const RANK = { USUAL: 0, DOWN: 1, HARD: 2 } as const
const isPhq = (i: Item) => i.kind === 'PHQ8' || i.kind === 'PHQ9'
const md = (d: string) => d.slice(5).split('-').map(Number) // '2026-11-23' → [11, 23]

export default function ELDER_MIND_001() {
  const nav = useNavigate()
  const loc = useLocation()
  const live = useLive()
  const [home, setHome] = useState<ElderHomeOut | undefined>((loc.state as ElderNavState | null)?.home)
  const [items, setItems] = useState<Item[]>()
  const speed = Number(home?.settings.tts_speed) || 0.9
  const due = !!home?.mood_due

  useEffect(() => {
    // 새로고침이면 홈 정보(할 차례·말 빠르기)를 다시 읽는다. 할 차례는 체크를 마치고 돌아오면 바뀌므로 늘 새로
    api<ElderHomeOut>('/api/elder/home').then((h) => live.current && setHome(h)).catch(() => {})
    api<MoodHistoryOut>('/api/elder/mood-history')
      .then((r) => live.current && setItems(r.items))
      .catch(() => live.current && setItems([]))
  }, [live])

  const phq = (items ?? []).filter(isPhq) // 새것 먼저
  const now = phq[0]
  const prev = phq[1]
  // 나빠졌다는 말은 하지 않는다 — 나아졌거나 비슷할 때만
  const compare = !now || !prev ? '' : RANK[now.level] < RANK[prev.level] ? '지난번보다 나아졌어요' : RANK[now.level] === RANK[prev.level] ? '지난번과 비슷해요' : ''
  const nowSay = now ? `요즘 마음은 ${now.title}. ${compare}`.trim() : ''

  useEffect(() => {
    if (!items) return
    void say(`내 마음이에요. ${due ? '기분 여쭤볼 차례예요. ' : ''}${nowSay ? `${nowSay} ` : ''}해 볼 것을 눌러 주세요.`, speed)
    return () => stopSpeaking()
    // 기록을 받은 뒤 한 번만 읽는다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items])

  const last = (k: CheckKind) => (k === 'PHQ9' ? now : items?.find((i) => i.kind === k)) // 기분은 예전 PHQ8 결과도
  const start = (kind: CheckKind) => nav('/elder/mood-check', { state: { home, kind } })
  const [results, setResults] = useState(false) // [지난 결과 보기] (11/25 실사용: 결과를 다시 볼 곳이 안 보였다)
  const nameOf = (i: Item) => (i.kind === 'MEMGAME' ? '기억력 놀이' : i.kind === 'PHQ8' ? CHECKS.PHQ9.name : CHECKS[i.kind].name)
  const lineOf = (i: Item) => `${md(i.check_date)[0]}월 ${md(i.check_date)[1]}일 ${nameOf(i)}, ${i.title}`

  function openResults() {
    setResults(true)
    void say(items?.length ? '지난 결과예요. 누르면 읽어 드려요.' : '아직 해 본 것이 없어요.', speed)
  }

  if (results)
    return (
      <main className="elder mind-page">
        <h1>지난 결과</h1>
        {items?.length ? (
          <ul className="mind-results">
            {items.map((i) => (
              <li key={`${i.check_date}${i.kind}`}>
                <button type="button" onClick={() => void say(lineOf(i), speed)}>
                  <span className="elder-face mind-rface" aria-hidden="true">{i.face}</span>
                  <span className="mind-tl">
                    <small>{md(i.check_date)[0]}월 {md(i.check_date)[1]}일 · {nameOf(i)}</small>
                    {i.title}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="elder-text">아직 해 본 것이 없어요.</p>
        )}
        <button type="button" className="elder-btn" onClick={() => { stopSpeaking(); setResults(false) }}>닫기</button>
      </main>
    )

  return (
    <main className="elder mind-page">
      <h1>내 마음</h1>
      {now && (
        <button type="button" className="mind-now" onClick={() => void say(nowSay, speed)}>
          <span className="elder-face mind-face" aria-hidden="true">{now.face}</span>
          <span>
            <small>요즘 마음 · {md(now.check_date)[0]}월 {md(now.check_date)[1]}일</small>
            <b>{now.title}</b>
            {compare && <small>{compare}</small>}
          </span>
        </button>
      )}
      {phq.length > 1 && (
        <div className="mind-hist" aria-label="지난 마음">
          {phq.slice(0, 5).reverse().map((i) => (
            <span key={`${i.check_date}${i.kind}`}>
              <i className="elder-face" aria-hidden="true">{i.face}</i>
              {md(i.check_date).join('/')}
            </span>
          ))}
        </div>
      )}
      {!!items?.length && (
        <button type="button" className="elder-btn elder-btn--secondary elder-btn--sm" onClick={openResults}>
          지난 결과 보기
        </button>
      )}
      <h2 className="elder-eyebrow">해 볼 것</h2>
      <div className="elder-col">
        {(Object.keys(CHECKS) as CheckKind[]).map((k) => {
          const c = CHECKS[k]
          const todo = k === 'PHQ9' && due
          const before = last(k)
          return (
            <button key={k} type="button" className={`elder-btn elder-btn--wide${todo ? '' : ' elder-btn--secondary'}`} onClick={() => start(k)}>
              <span className="elder-lead mind-emoji" aria-hidden="true">{c.emoji}</span>
              <span className="mind-tl">
                {c.name}
                <small>{c.info}{todo ? ' · 할 차례' : ''}</small>
                {before && <small>지난번 · {before.title}</small>}
              </span>
              <span className="elder-go">{IC.next}</span>
            </button>
          )
        })}
        <button type="button" className="elder-btn elder-btn--wide elder-btn--secondary" onClick={() => nav('/elder/mind/memory-game', { state: { home } })}>
          <span className="elder-lead mind-emoji" aria-hidden="true">🧩</span>
          <span className="mind-tl">
            기억력 놀이
            <small>낱말 세 개 · 2분</small>
          </span>
          <span className="elder-go">{IC.next}</span>
        </button>
      </div>
      <p className="elder-sub">병을 알아보는 검사가 아니에요.</p>
    </main>
  )
}
