/**
 * WEEKLY_001 — 주간 이야기 (FR-FD-007, 목업 ⑤). 질문·답 카드와 안부 한 줄은 D62·D67을 따른다.
 * '달라진 점' 카드는 서버가 만든 문장(changes)을 그대로 보인다. 그 주 일기 목록은 여기 없다 — 가족 홈에서 본다 (11/18 멘토링).
 */
import { useEffect } from 'react'
import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom'
import { MOOD_LABEL, type WeeklyOut } from '../../api/types'
import ElderPhoto from '../../components/ElderPhoto'
import FamIcon from '../../components/FamIcon'
import MoodIcon from '../../components/MoodIcon'
import { useFetch } from '../../hooks/useFetch'
import { markWeeklySeen } from '../../lib/weeklySeen'
import './WEEKLY_001.css'

// 'YYYY-MM-DD' 뒤에 T00:00:00을 붙여 날짜가 하루 밀리지 않게 한다.
const day = (iso: string, opts: Intl.DateTimeFormatOptions) => new Date(iso + 'T00:00:00').toLocaleDateString('ko-KR', opts)

export default function WEEKLY_001() {
  const { roomId } = useParams()
  const [params, setParams] = useSearchParams()
  const weekStart = params.get('week_start')
  // 방·주가 바뀌면 이전 응답을 비운다. 늦은 응답이나 읽음 표시가 다른 주에 섞이지 않게 한다.
  return (
    <WeeklyWeek key={`${roomId}:${weekStart ?? 'latest'}`} roomId={Number(roomId)} weekStart={weekStart}
      onWeek={(week) => setParams({ week_start: week })} />
  )
}

function WeeklyWeek({ roomId, weekStart, onWeek }: { roomId: number; weekStart: string | null; onWeek: (week: string) => void }) {
  const path = '/api/rooms/' + roomId + '/weekly' + (weekStart ? '?week_start=' + encodeURIComponent(weekStart) : '')
  const { data, error, reload } = useFetch<WeeklyOut>(path)
  // 설치형 앱으로 돌아오면 지금 보고 있는 주간 이야기를 다시 읽는다
  useEffect(() => {
    const onShow = () => {
      if (document.visibilityState !== 'visible') return
      reload()
    }
    document.addEventListener('visibilitychange', onShow)
    return () => document.removeEventListener('visibilitychange', onShow)
  }, [reload])

  // 가장 최근 주를 봤을 때만 적는다. 지난 주로 덮어 쓰면 가족 홈의 도착 띠가 다시 뜬다 (D70).
  useEffect(() => {
    if (data && data.next_week_start === null) markWeeklySeen(roomId, data.week_start)
  }, [data, roomId])

  if (error?.status === 401) return <Navigate to="/login" replace />
  if (error?.code === 'WEEKLY_NOT_FOUND')
    return (
      <main className="fam-stack weekly-screen">
        <header className="weekly-heading"><h1>주간 이야기</h1></header>
        <div className="weekly-empty"><b>아직 주간 이야기가 없어요</b><p>첫 주간 이야기는 일요일 저녁에 와요.</p></div>
      </main>
    )
  if (error)
    return (
      <main className="fam-stack weekly-screen">
        <header className="weekly-heading"><h1>주간 이야기</h1></header>
        <section className="fam-card weekly-empty">
          <p role="alert">{error.message}</p>
          <button type="button" className="fam-btn fam-btn--tonal" onClick={reload}>다시 시도</button>
          <Link className="fam-text-btn" to="/">가족 홈으로</Link>
        </section>
      </main>
    )
  if (!data) return (
    <main className="fam-stack weekly-screen" aria-busy="true">
      <header className="weekly-heading"><h1>주간 이야기</h1></header>
      <p className="weekly-empty" role="status">불러오는 중…</p>
    </main>
  )

  const start = new Date(data.week_start + 'T00:00:00')
  const end = new Date(start)
  end.setDate(start.getDate() + 6)
  const fmt = (d: Date) => d.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' })
  const empty = data.memory_days === 0 && data.diary_days === 0
  const latest = data.next_week_start === null
  const period = latest ? '이번 주' : '그 주'
  const weekLabel = `${start.getMonth() + 1}월 ${['첫째', '둘째', '셋째', '넷째', '다섯째'][Math.floor((start.getDate() - 1) / 7)]} 주`
  // 달라진 점 — 살펴볼 줄은 색만이 아니라 '살펴보기' 낱말로도 알린다. 이야기가 없던 주에도 보인다(줄어든 것이 신호다).
  const changed = data.changes.length > 0 && (
    <section className="fam-card weekly-card">
      <h2 className="weekly-card-heading">{period} 달라진 점</h2>
      <ul className="weekly-changes">
        {data.changes.map((c) => (
          <li key={c.text} className={c.tone === 'watch' ? 'watch' : undefined}>
            {c.tone === 'watch' && <b>살펴보기</b>}
            {c.text}
          </li>
        ))}
      </ul>
    </section>
  )

  return (
    <main className="fam-stack weekly-screen">
      <header className="weekly-heading"><h1>주간 이야기</h1></header>
      <nav className="weekly-nav" aria-label="주간 이야기 기간">
        <button type="button" className="fam-icon-btn weekly-prev" aria-label="지난 주" disabled={data.prev_week_start === null}
          onClick={() => data.prev_week_start && onWeek(data.prev_week_start)}><FamIcon name="chevRight" /></button>
        <div aria-live="polite"><b>{weekLabel}</b><small>{fmt(start)} ~ {fmt(end)}</small></div>
        <button type="button" className="fam-icon-btn" aria-label="다음 주" disabled={data.next_week_start === null}
          onClick={() => data.next_week_start && onWeek(data.next_week_start)}><FamIcon name="chevRight" /></button>
      </nav>
      {/* 안부 한 줄 — 기운 없음·위급 대화가 있던 주. 대화 내용은 오지 않는다 (D62). */}
      {data.notes?.lines.map((line) => (
        <section key={line} className="fam-card weekly-note"><p>{line}</p></section>
      ))}
      {empty ? (
        <>
          <section className="fam-card weekly-empty"><p>이 주에는 이야기와 일기가 없었어요.</p></section>
          {changed}
        </>
      ) : (
        <>
          <section className="fam-card weekly-stat">
            <p><b>이야기한 날 {data.memory_days}일</b> · 일기 쓴 날 {data.diary_days}일</p>
          </section>
          {changed}
          <section className="fam-card weekly-card">
            <h2 className="weekly-card-heading">기분</h2>
            <div className="weekly-week">
              {data.mood_trend.map((d) => (
                <div className="weekly-day" key={d.date} role="img"
                  aria-label={`${day(d.date, { month: 'long', day: 'numeric', weekday: 'short' })}, ${d.mood ? MOOD_LABEL[d.mood] : '기록 없음'}`}>
                  <b>{day(d.date, { weekday: 'short' })}</b>
                  {d.mood ? <MoodIcon mood={d.mood} /> : <span className="weekly-no-mood" aria-hidden="true">–</span>}
                </div>
              ))}
            </div>
          </section>
          {/* 요약이 실패했거나 전할 답이 없던 주는 질문·답 카드를 그리지 않는다 (D62). */}
          {data.qa_list.length > 0 && (
            <section className="fam-card weekly-card">
              <h2 className="weekly-card-heading">{period} 이야기</h2>
              {data.qa_list.map((c) => (
                <article className="weekly-qa" key={c.session_id + ':' + c.source_turns.join(',')}>
                  {c.photo_url && <ElderPhoto className="weekly-thumb" src={c.photo_url} alt="이야기한 사진" />}
                  <div className="weekly-qa-text">
                    <small>{day(c.date, { month: 'long', day: 'numeric', weekday: 'short' })}</small>
                    <p className="weekly-q">Q {c.question}</p>
                    <p className="weekly-a">A {c.answer}</p>
                  </div>
                </article>
              ))}
            </section>
          )}
        </>
      )}
    </main>
  )
}
