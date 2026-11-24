/**
 * ELDER_DIARY_004 — 지난 일기 (D60, FR-DI-004). 일기 쓰기 화면(ELDER_DIARY_001)의 [지난 일기]에서 온다.
 * 내가 올린 일기를 최신순으로 쭉 보여 준다(11/23 시안 e-diary-past) — 이 목록만 사진첩처럼 스크롤한다. 줄을 누르면 화면 가득 크게 보여 주고 읽어 준다.
 * 크게 본 화면은 [닫기]나 폰의 뒤로 키로 닫힌다(<dialog>). 글 상자를 누르면 다시 읽는다. 회상 질문은 없다.
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { MOOD_LABEL, type DiaryListOut, type DiaryOut } from '../../api/types'
import ElderPhoto from '../../components/ElderPhoto'
import { ElderStop } from '../../components/ElderUi'
import MoodIcon from '../../components/MoodIcon'
import type { ElderNavState } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import { speak, stopSpeaking } from '../../lib/audio'
import { DiaryPaper } from './ELDER_DIARY_003'
import './ELDER_DIARY_004.css'

const GUIDE = '지난 일기예요. 보고 싶은 일기를 눌러 주세요.'
const EMPTY = '아직 쓴 일기가 없어요.'
const KIND_WORD: Record<string, string> = { HEART: '하트', SMILE: '웃음', CLAP: '박수' }
/** 가족이 이 일기에 보낸 것 — '큰딸 · 하트', '손주 · ‘보고 싶어요’' (11/24 실사용: 가족 소식에서 한 번 듣고 나면 다시 볼 곳이 없었다) */
const familyLines = (d: DiaryOut) =>
  d.reactions
    .filter((r) => r.by === 'FAMILY' && (r.kind === 'REPLY' ? r.text : KIND_WORD[r.kind]))
    .map((r) => `${r.name ?? '가족'} · ${r.kind === 'REPLY' ? `‘${r.text}’` : KIND_WORD[r.kind]}`)
const day = (iso: string) => new Date(iso).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'long' })
const EMOJI: Record<string, string> = { HEART: '❤️', SMILE: '😊', CLAP: '👏' } // 가족 홈(HOME_001 REACTS)과 같은 그림

/** 가족이 보낸 마음 — 이모지는 그림 줄로 모으고, 한마디는 말풍선으로 따로 (11/24 실사용: '딸 · 하트' 글자만 보여 구분이 안 됐다) */
function FamilyMarks({ d }: { d: DiaryOut }) {
  const fam = d.reactions.filter((r) => r.by === 'FAMILY')
  const marks = fam.filter((r) => EMOJI[r.kind])
  const replies = fam.filter((r) => r.kind === 'REPLY' && r.text)
  return (
    <div className="elder-past-fam" aria-label="가족이 보낸 마음">
      {marks.length > 0 && (
        <p className="elder-past-marks">
          {marks.map((r) => (
            <span key={`${r.user_id}${r.kind}`}>
              <i aria-hidden="true">{EMOJI[r.kind]}</i>
              {r.name ?? '가족'}
            </span>
          ))}
        </p>
      )}
      {replies.map((r) => (
        <p key={r.user_id ?? r.at} className="elder-past-reply">
          <b>{r.name ?? '가족'}</b>
          {r.text}
        </p>
      ))}
    </div>
  )
}

export default function ELDER_DIARY_004() {
  const { home } = (useLocation().state ?? {}) as ElderNavState
  const speed = Number(home?.settings.tts_speed) || 0.9
  const { data, error, loading, reload } = useFetch<DiaryListOut>('/api/elder/diaries')
  const [open, setOpen] = useState<DiaryOut>()
  const view = useRef<HTMLDialogElement>(null)
  const count = data?.diaries.length
  const errorMessage = error?.code === 'DEVICE_REQUIRED' ? '가족이 보낸 연결 링크를 먼저 열어 주세요.' : error?.message

  // 안내는 소리로도. 떠나면 멈춘다
  useEffect(() => {
    const message = errorMessage ?? (count === undefined ? undefined : count ? GUIDE : EMPTY)
    if (!message) return
    void speak(message, speed)
    return () => stopSpeaking()
  }, [count, errorMessage, speed])

  const read = (d: DiaryOut) => {
    const lines = familyLines(d)
    const fam = lines.length ? ` 가족이 보낸 마음이에요. ${lines.map((l) => l.replace(' · ', ', ')).join('. ')}.` : ''
    void speak(`${day(d.posted_at)} 일기예요. ${d.body} 그날 기분은 ${MOOD_LABEL[d.mood]}.${fam}`, speed)
  }

  function show(d: DiaryOut) {
    setOpen(d)
    view.current?.showModal()
    read(d)
  }

  return (
    <main className="elder elder-past">
      <h1>지난 일기</h1>
      {loading ? (
        <p className="elder-text" role="status">잠시만요…</p>
      ) : error ? (
        <ElderStop text={errorMessage} onRetry={error.code !== 'DEVICE_REQUIRED' ? reload : undefined} />
      ) : count === 0 ? (
        <p className="elder-sub">{EMPTY}</p>
      ) : (
        <>
          <p className="elder-sub">보고 싶은 일기를 눌러 주세요.</p>
          <div className="elder-col elder-past-list">
            {data?.diaries.map((d) => (
              <button key={d.diary_id} type="button" className="elder-btn elder-btn--secondary elder-past-item" onClick={() => show(d)}>
                {d.illustration_url
                  ? <img src={d.illustration_url} alt="" loading="lazy" decoding="async" />
                  : <span className="elder-past-noimg"><MoodIcon mood={d.mood} /></span>}
                <span>
                  {day(d.posted_at)}
                  <small><MoodIcon mood={d.mood} /> {MOOD_LABEL[d.mood]}</small>
                </span>
              </button>
            ))}
          </div>
        </>
      )}
      <dialog
        ref={view}
        className="elder-cover elder-past-view"
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
            <h1>{day(open.posted_at)}</h1>
            {open.illustration_url ? (
              <ElderPhoto src={open.illustration_url} alt={open.illustration_type === 'PHOTO' ? '일기 사진' : '그림일기 그림'} />
            ) : (
              <div className="elder-photo-box elder-photo-box--grow elder-mood-pic"><MoodIcon mood={open.mood} /></div>
            )}
            <DiaryPaper key={open.diary_id} body={open.body} onRead={() => read(open)} />
            <p className="elder-moodline"><MoodIcon mood={open.mood} />그날 기분 · {MOOD_LABEL[open.mood]}</p>
            {familyLines(open).length > 0 && <FamilyMarks d={open} />}
            <button type="button" className="elder-btn elder-btn--secondary" onClick={() => view.current?.close()}>닫기</button>
          </>
        )}
      </dialog>
    </main>
  )
}
