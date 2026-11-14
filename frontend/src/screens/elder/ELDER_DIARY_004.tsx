/**
 * ELDER_DIARY_004 — 지난 일기 (D60, FR-DI-004). 일기 쓰기 화면(ELDER_DIARY_001)의 [지난 일기]에서 온다.
 * 내가 올린 일기를 최신순으로 쭉 보여 준다 — 이 목록만 사진첩처럼 스크롤한다. 카드를 누르면 화면 가득 크게 보여 주고 읽어 준다.
 * 크게 본 화면은 [닫기]나 폰의 뒤로 키로 닫힌다(<dialog>). 글 상자를 누르면 다시 읽는다. 회상 질문은 없다.
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { MOOD_LABEL, type DiaryListOut, type DiaryOut } from '../../api/types'
import ElderPhoto from '../../components/ElderPhoto'
import MoodIcon from '../../components/MoodIcon'
import type { ElderNavState } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import { speak, stopSpeaking } from '../../lib/audio'
import './ELDER_DIARY_004.css'

const GUIDE = '지난 일기예요. 보고 싶은 일기를 눌러 주세요.'
const EMPTY = '아직 쓴 일기가 없어요.'
const day = (iso: string) => new Date(iso).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'long' })

export default function ELDER_DIARY_004() {
  const { home } = (useLocation().state ?? {}) as ElderNavState
  const speed = Number(home?.settings.tts_speed) || 0.9
  const { data, error, loading, reload } = useFetch<DiaryListOut>('/api/elder/diaries')
  const [open, setOpen] = useState<DiaryOut>()
  const view = useRef<HTMLDialogElement>(null)
  const count = data?.diaries.length

  // 안내는 소리로도. 떠나면 멈춘다
  useEffect(() => {
    if (count === undefined) return
    void speak(count ? GUIDE : EMPTY, speed)
    return () => stopSpeaking()
  }, [count, speed])

  const read = (d: DiaryOut) => void speak(`${day(d.posted_at)} 일기예요. ${d.body} 그날 기분은 ${MOOD_LABEL[d.mood]}.`, speed)

  function show(d: DiaryOut) {
    setOpen(d)
    view.current?.showModal()
    read(d)
  }

  return (
    <main className="elder elder-past">
      <h1 className="elder-text elder-text--lg">지난 일기</h1>
      {loading ? (
        <p className="elder-text" role="status">잠시만요…</p>
      ) : error ? (
        <>
          <p className="elder-text" role="alert">
            {error.code === 'DEVICE_REQUIRED' ? '가족이 보낸 연결 링크를 먼저 열어 주세요.' : error.message}
          </p>
          {error.code !== 'DEVICE_REQUIRED' && <button className="elder-btn" onClick={reload}>다시 보기</button>}
        </>
      ) : count === 0 ? (
        <p className="elder-text">{EMPTY}</p>
      ) : (
        <div className="elder-past-list">
          {data?.diaries.map((d) => (
            <button key={d.diary_id} type="button" className="elder-past-card" onClick={() => show(d)}>
              <span className="elder-past-thumb">
                {d.illustration_url ? <img src={d.illustration_url} alt="" loading="lazy" decoding="async" /> : <MoodIcon mood={d.mood} />}
              </span>
              <span>
                {day(d.posted_at)}
                <small><MoodIcon mood={d.mood} />{MOOD_LABEL[d.mood]}</small>
              </span>
            </button>
          ))}
        </div>
      )}
      <dialog
        ref={view}
        className="elder-past-view"
        aria-label="일기 크게 보기"
        onClose={(e) => {
          // 안에 든 사진 크게 보기(ElderPhoto 의 dialog)가 닫힐 때도 이 이벤트가 올라온다 — 이 창이 닫힐 때만 비운다
          if (e.target !== e.currentTarget) return
          stopSpeaking()
          setOpen(undefined)
        }}
      >
        {open && (
          <>
            <div className="elder-who"><span>{day(open.posted_at)}</span></div>
            {open.illustration_url && (
              <ElderPhoto src={open.illustration_url} alt={open.illustration_type === 'PHOTO' ? '일기 사진' : '그림일기 그림'} />
            )}
            <button type="button" className="elder-paper" onClick={() => read(open)}>
              <span>{open.body}</span>
              <svg className="elder-spk" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M4 9.5v5h3.2L12 18.5v-13L7.2 9.5z" />
                <path d="M15.5 9a4.2 4.2 0 0 1 0 6M18.3 6.3a8 8 0 0 1 0 11.4" />
              </svg>
            </button>
            <div className="elder-mood"><MoodIcon mood={open.mood} />그날 기분 · {MOOD_LABEL[open.mood]}</div>
            <button type="button" className="elder-btn elder-btn--secondary elder-bottom" onClick={() => view.current?.close()}>닫기</button>
          </>
        )}
      </dialog>
    </main>
  )
}
