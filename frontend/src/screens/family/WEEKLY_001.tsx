/**
 * WEEKLY_001 — 주간 이야기 (FR-FD-007). 집계 숫자(이야기한 날·일기 쓴 날·기분 날씨 7칸)와
 * 주간 요약 AI 의 질문·답 카드(최대 4장, D62)·안부 한 줄. 점수처럼 보이게 쓰지 않는다(NFR-DE-003).
 */
import { Link, Navigate, useParams } from 'react-router-dom'
import type { WeeklyOut } from '../../api/types'
import ElderPhoto from '../../components/ElderPhoto'
import MoodIcon from '../../components/MoodIcon'
import { useFetch } from '../../hooks/useFetch'
import './WEEKLY_001.css'

// 'YYYY-MM-DD' 뒤에 T00:00:00 을 붙여야 날짜가 하루 밀리지 않는다
const day = (iso: string, opts: Intl.DateTimeFormatOptions) => new Date(iso + 'T00:00:00').toLocaleDateString('ko-KR', opts)

export default function WEEKLY_001() {
  const { roomId } = useParams()
  const { data, error, reload } = useFetch<WeeklyOut>('/api/rooms/' + roomId + '/weekly')

  if (error?.status === 401) return <Navigate to="/login" replace />
  if (error?.code === 'WEEKLY_NOT_FOUND')
    return (
      <main className="page fam-skin">
        <h1>주간 이야기</h1>
        <p>아직 주간 이야기가 없어요.</p>
        <p className="muted">첫 주간 이야기는 일요일 저녁에 와요.</p>
        <Link className="btn" to="/">가족 홈으로</Link>
      </main>
    )
  if (error)
    return (
      <main className="page fam-skin">
        <h1>주간 이야기</h1>
        <p className="error">{error.message}</p>
        <button className="btn" onClick={reload}>다시 시도</button>{' '}
        <Link className="btn secondary" to="/">가족 홈으로</Link>
      </main>
    )
  if (!data) return <main className="page fam-skin"><p className="muted">불러오는 중…</p></main>

  const start = new Date(data.week_start + 'T00:00:00')
  const end = new Date(start)
  end.setDate(start.getDate() + 6)
  const fmt = (d: Date) => d.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' })
  const empty = data.memory_days === 0 && data.diary_days === 0 // 기록이 없으면 안내 문구만 (FR-FD-007)

  return (
    <main className="page fam-skin">
      <h1>주간 이야기</h1>
      <p className="muted">{fmt(start)} ~ {fmt(end)}</p>
      {/* 안부 한 줄 — 기운 없음·위급 대화가 있던 주. 대화 내용은 오지 않는다 (D62) */}
      {data.notes?.lines.map((line) => (
        <section key={line} className="card weekly-note"><p>{line}</p></section>
      ))}
      {empty ? (
        <section className="card"><p>이 주에는 이야기와 일기가 없었어요.</p></section>
      ) : (
        <>
          <section className="card weekly-card">
            <p><b>이야기한 날 {data.memory_days}일</b> · 일기 쓴 날 {data.diary_days}일</p>
          </section>
          <section className="card weekly-card">
            <h2>기분 날씨</h2>
            <div className="weekly-week">
              {data.mood_trend.map((d) => (
                <div className="weekly-day" key={d.date}>
                  <b>{day(d.date, { weekday: 'short' })}</b>
                  {d.mood ? <MoodIcon mood={d.mood} /> : <s />}
                </div>
              ))}
            </div>
          </section>
          {/* 질문·답 카드 — 요약이 실패했거나 전할 답이 없던 주는 [] 라 그리지 않는다 (D62) */}
          {data.qa_list.length > 0 && (
            <section className="card weekly-card">
              <h2>이번 주 이야기</h2>
              {data.qa_list.map((c) => (
                <article className="weekly-qa" key={c.session_id + ':' + c.source_turns.join(',')}>
                  {c.photo_url && <ElderPhoto className="weekly-thumb" src={c.photo_url} alt="이야기한 사진" />}
                  <div className="weekly-qa-text">
                    <small className="muted">{day(c.date, { month: 'long', day: 'numeric', weekday: 'short' })}</small>
                    <p className="weekly-q">Q {c.question}</p>
                    <p className="weekly-a">A {c.answer}</p>
                  </div>
                </article>
              ))}
            </section>
          )}
        </>
      )}
      <Link className="btn secondary" to="/">가족 홈으로</Link>
    </main>
  )
}
