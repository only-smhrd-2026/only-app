/**
 * ELDER_FAMILY_001 — 가족 소식 (11/23 시안 e-news, FR-FD-003·004, D53·D63).
 * ① 받은 반응: 가족이 내 일기에 보낸 하트·웃음·박수·한마디를 '누가 · 어느 일기에'로 보여 주고 읽는다 → [다음 소식]에서 들음 표시.
 * ② 안 들은 가족 일기를 한 장씩: 보낸 사람 · 사진(없으면 꼬마심심이) · 글 → [하트](다시 눌러도 취소 안 됨, D64) · [말로 답하기].
 *    말로 답하기: 녹음 → /api/stt → AI 가 한 줄로(reply-draft) → '이렇게 보낼까요?' → [보내기] (답장의 답장은 없다).
 * ③ 새 소식이 없으면 [지난 소식 다시 듣기] — 들은 가족 일기 최근 5개를 같은 방식으로, 읽음 표시는 바꾸지 않는다 (11/19).
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { DiaryOut, ElderReplyDraftOut, FamilyNewsOut, Heart, SttOut } from '../../api/types'
import ElderPhoto from '../../components/ElderPhoto'
import { Bars, Bub, Dots, ElderStop, IC } from '../../components/ElderUi'
import Sim from '../../components/Sim'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import { cue, micBlockedTip, playVoice, speak, startRecording, stopSpeaking, type Recorder } from '../../lib/audio'
import './ELDER_FAMILY_001.css'

const KIND_WORD = { HEART: '하트', SMILE: '웃음', CLAP: '박수' } as const
const NO_NEWS = '오늘은 새 소식이 없어요.'
const AGAIN_GUIDE = '지난 소식 다시 듣기를 누르면 다시 읽어 드려요.'
const REPLY_ASK = '하실 말씀을 해 주세요.'
const REPLY_MS = 60_000 // 답장 녹음 상한 — 대화 녹음과 같게
const BARS = [30, 55, 80, 45, 95, 60, 35, 75, 50, 85, 40, 65, 30, 55] // 목소리 재생 줄의 꾸밈 막대(높이 %) — 실제 파형 아님

/** 받침이 있으면 앞의 조사, 없으면 뒤의 조사 — '큰딸이'·'손주가', '웃음을'·'하트를' */
function josa(word: string, withFinal: string, without: string) {
  const code = word.charCodeAt(word.length - 1)
  return code >= 0xac00 && code <= 0xd7a3 && (code - 0xac00) % 28 !== 0 ? withFinal : without
}
const day = (iso: string) => new Date(iso).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' })

type Who = { who: string; words: string[]; reply?: string }
type DiaryReacts = { diary_id: number; body: string; at: string; thumb: string | null; whos: Who[] }

/** 받은 반응 → 일기마다 한 카드, 카드 안은 한 사람 한 줄(이모지는 모아서, 한마디는 따로) */
function groupHearts(hearts: Heart[]): DiaryReacts[] {
  const cards: DiaryReacts[] = []
  for (const h of hearts) {
    let card = cards.find((c) => c.diary_id === h.diary_id)
    if (!card) cards.push((card = { diary_id: h.diary_id, body: h.diary_body, at: h.diary_posted_at, thumb: h.diary_thumb_url, whos: [] }))
    const who = h.name || '가족'
    if (h.kind === 'REPLY') {
      if (h.text) card.whos.push({ who, words: [], reply: h.text })
      continue
    }
    const row = card.whos.find((w) => w.who === who && !w.reply) ?? (card.whos.push({ who, words: [] }), card.whos.at(-1)!)
    if (!row.words.includes(KIND_WORD[h.kind])) row.words.push(KIND_WORD[h.kind])
  }
  return cards
}

/** '하트와 웃음을' */
const wordsText = (words: string[]) => words.map((w, i) => w + (i < words.length - 1 ? josa(w, '과', '와') : josa(w, '을', '를'))).join(' ')

/** 읽어 줄 한 줄 — "큰딸이 11월 3일 일기에 하트를 보냈어요." · "손주가 11월 3일 일기에 ‘보고 싶어요’래요." */
function reactLine(card: DiaryReacts, w: Who) {
  const subject = `${w.who}${josa(w.who, '이', '가')} ${day(card.at)} 일기에`
  if (!w.reply) return `${subject} ${wordsText(w.words)} 보냈어요.`
  const tail = w.reply.replace(/[^가-힣]+$/, '') // 받침은 글 끝의 느낌표·이모지를 건너뛰고 마지막 한글로 본다
  return `${subject} ‘${w.reply}’${josa(tail, '이래요', '래요')}.`
}

/** 긴 가족 일기도 글자 크기를 유지하며 한 화면 안에서 쪽을 넘겨 읽는다 */
function FamilyPaper({ body, saying, onRead }: { body: string; saying: boolean; onRead: () => void }) {
  const text = useRef<HTMLSpanElement>(null)
  const [page, setPage] = useState(0)
  const [count, setCount] = useState(1)

  useEffect(() => {
    const element = text.current
    if (!element) return
    const measure = () => {
      if (!element.clientWidth) return
      const pages = Math.max(1, Math.round(element.scrollWidth / element.clientWidth))
      setCount(pages)
      setPage((current) => Math.min(current, pages - 1))
    }
    const size = new ResizeObserver(measure)
    size.observe(element)
    const font = new MutationObserver(measure)
    font.observe(document.documentElement, { attributes: true, attributeFilter: ['data-font'] })
    void document.fonts.ready.then(measure)
    return () => {
      size.disconnect()
      font.disconnect()
    }
  }, [body])

  return (
    <div className="family-reading">
      <button type="button" className={`elder-paper family-paper${saying ? ' elder-saying' : ''}`} onClick={onRead}>
        <span className="family-paper-window">
          <span ref={text} className="family-paper-pages" style={{ transform: `translateX(-${page * 100}%)` }}>{body}</span>
        </span>
        <span className="elder-spk-dot" aria-hidden="true">{IC.spk}</span>
      </button>
      {count > 1 && (
        <div className="family-pages" aria-label="가족 소식 글 넘기기">
          <button type="button" className="elder-chip" disabled={page === 0} onClick={() => setPage((current) => current - 1)}>이전 글</button>
          <span role="status" aria-label={`전체 ${count}쪽 중 ${page + 1}쪽`}>{page + 1} / {count}</span>
          <button type="button" className="elder-chip" disabled={page === count - 1} onClick={() => setPage((current) => current + 1)}>다음 글</button>
        </div>
      )}
    </div>
  )
}

type ReplyStep = 'ready' | 'listen' | 'think' | 'check' | 'fail'

/** [말로 답하기] 판: 안내를 읽은 뒤 녹음 → [다 말했어요] → STT → 한 줄 초안 → [보내기]/[다시 말할게요] · 아래 [안 보낼래요] */
function ReplySheet({ diary, to, speed, onSent, onClose }: { diary: DiaryOut; to: string; speed: number; onSent: (text: string) => void; onClose: () => void }) {
  const live = useLive()
  const [step, setStep] = useState<ReplyStep>('ready')
  const [heard, setHeard] = useState('')
  const [line, setLine] = useState('')
  const [note, setNote] = useState('')
  const [sending, setSending] = useState(false)
  const rec = useRef<Recorder | undefined>(undefined)
  const run = useRef(0) // [다시 말할게요]·닫기 뒤에 끝난 옛 녹음·요청은 버린다

  function fail(text: string) {
    setNote(text)
    setStep('fail')
    void speak(text, speed)
  }

  async function listen() {
    const my = ++run.current
    stopSpeaking()
    setStep('ready')
    setNote('')
    await speak(REPLY_ASK, speed) // 안내가 녹음에 섞이지 않게 다 읽은 뒤 녹음
    if (!live.current || my !== run.current) return
    try {
      rec.current = await startRecording(REPLY_MS)
    } catch (e) {
      // 아이폰 [취소] 뒤면 앱을 다시 열어야 다시 묻는다 (11/24 실사용)
      const tip = micBlockedTip(e) || ' 가족에게 마이크 허락을 부탁해 주세요.'
      if (live.current && my === run.current) fail(`마이크를 쓸 수 없어요.${tip}`)
      return
    }
    if (!live.current || my !== run.current) return void rec.current.stop()
    cue()
    setStep('listen')
  }

  async function done() {
    const my = run.current
    const r = rec.current
    rec.current = undefined
    if (!r) return
    setStep('think')
    setHeard('')
    try {
      const form = new FormData()
      form.append('audio', await r.stop(), 'speech.webm')
      const { transcript } = await api<SttOut>('/api/stt', { form })
      if (!live.current || my !== run.current) return
      if (!transcript.trim()) return fail('잘 못 들었어요. 다시 말해 주세요.')
      setHeard(transcript)
      const { text } = await api<ElderReplyDraftOut>(`/api/elder/diaries/${diary.diary_id}/reply-draft`, { body: { transcript } })
      if (!live.current || my !== run.current) return
      setLine(text)
      setStep('check')
      void speak(`이렇게 보낼까요? ${text}`, speed)
    } catch (e) {
      if (live.current && my === run.current) fail(e instanceof ApiError ? e.message : '잘 못 들었어요. 다시 말해 주세요.')
    }
  }

  async function send() {
    if (sending) return
    setSending(true)
    try {
      await api<DiaryOut>(`/api/elder/diaries/${diary.diary_id}/reply`, { body: { text: line } })
      if (live.current) onSent(line)
    } catch (e) {
      if (live.current) fail(e instanceof ApiError ? e.message : '보내지 못했어요. 다시 해 주세요.')
    } finally {
      if (live.current) setSending(false)
    }
  }

  // 열리면 바로 듣기 시작, 닫히면 녹음을 끈다
  useEffect(() => {
    const runs = run
    const recorder = rec // 녹음기 칸(돔 아님) — 닫힐 때 그때 든 녹음기를 끈다
    void listen()
    return () => {
      runs.current++
      void recorder.current?.stop()
      stopSpeaking()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 열릴 때 한 번
  }, [])

  return (
    <>
      <div className="elder-scrim" />
      <section className="elder-sheet" role="dialog" aria-modal="true" aria-labelledby="reply-title">
        <h1 id="reply-title">{step === 'check' ? '이렇게 보낼까요?' : `${to}에게 답장`}</h1>
        {(step === 'ready' || step === 'listen') && (
          <>
            <div className="elder-greet">
              <Sim face="curious" size={84} className="elder-sim" />
              <p className="elder-sub">하실 말씀을 해 주세요.<br />한 줄로 정리해 드릴게요.</p>
            </div>
            <button type="button" className={`elder-btn${step === 'listen' ? ' elder-btn--rec' : ''}`} onClick={() => void done()} disabled={step !== 'listen'}>
              <span className="elder-dot">{step === 'listen' ? IC.stop : IC.mic}</span>
              {step === 'listen' ? <>다 말했어요<Bars /></> : <>잠시만요<Dots /></>}
            </button>
          </>
        )}
        {step === 'think' && (
          <div className="elder-greet" role="status">
            <Sim face="ask" size={84} className="elder-sim" />
            <p className="elder-sub">{heard && <>“{heard}”<br /></>}한 줄로 정리하는 중<Dots /></p>
          </div>
        )}
        {step === 'check' && (
          <>
            <Bub text={line} speed={speed} className="elder-bub--long" />
            <div className="elder-row reply-two">
              <button type="button" className="elder-btn" onClick={() => void send()} disabled={sending}>{sending ? '보내는 중…' : '보내기'}</button>
              <button type="button" className="elder-btn elder-btn--secondary" onClick={() => void listen()} disabled={sending}>다시 말할게요</button>
            </div>
          </>
        )}
        {step === 'fail' && (
          <>
            <div className="elder-greet" role="alert">
              <Sim face="ask" size={84} className="elder-sim" />
              <p className="elder-sub">{note}</p>
            </div>
            <button type="button" className="elder-btn" onClick={() => void listen()}><span className="elder-dot">{IC.mic}</span>다시 말할게요</button>
          </>
        )}
        <button type="button" className="elder-btn elder-btn--secondary elder-btn--sm reply-no" onClick={onClose} disabled={sending}>안 보낼래요</button>
      </section>
    </>
  )
}

export default function ELDER_FAMILY_001() {
  const nav = useNavigate()
  const { home } = (useLocation().state ?? {}) as ElderNavState
  const speed = Number(home?.settings.tts_speed) || 0.9
  const { data, error, loading, reload } = useFetch<FamilyNewsOut>('/api/elder/family-news')
  // 새 소식이 없을 때만 지난 소식(들은 가족 일기 최근 5개)을 받아 둔다 — 있으면 [지난 소식 다시 듣기]를 보인다
  const empty = !!data && !data.diaries.length && !data.hearts.length
  const past = useFetch<FamilyNewsOut>(empty ? '/api/elder/family-news?again=1' : null)
  const [again, setAgain] = useState(false)
  const live = useLive()
  const liking = useRef(false) // 하트 보내는 중
  const [index, setIndex] = useState(0)
  const [heartsHeard, setHeartsHeard] = useState(false)
  const [liked, setLiked] = useState<Record<number, boolean>>({}) // 이 화면에서 보낸 하트 — 받은 목록은 다시 읽지 않는다
  const [replied, setReplied] = useState<Record<number, string>>({}) // 이 화면에서 보낸 답장
  const [replying, setReplying] = useState(false)
  const [busy, setBusy] = useState(false)
  const [readError, setReadError] = useState<string>()
  const [saying, setSaying] = useState(false)
  const reading = useRef(false)
  const sayingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const hearts = !heartsHeard && data?.hearts.length ? data.hearts : undefined
  // 가족 목소리 답장(D99)은 한 장씩 먼저 틀어 드리고, 이모지·글 한마디는 그 뒤 모아 둔 한 장에 (11/24 사용자 그림)
  const [heartPage, setHeartPage] = useState(0)
  const [playing, setPlaying] = useState(false)
  const voices = hearts?.filter((h) => h.audio_url) ?? []
  const cards = hearts ? groupHearts(hearts.filter((h) => !h.audio_url)) : []
  const heartPages = voices.length + (cards.length ? 1 : 0)
  const voice = hearts ? voices[heartPage] : undefined // 없으면 모아 둔 장
  const heartsTitle = `가족이 ${home?.elder_honorific ? `${home.elder_honorific} ` : ''}일기를 읽었어요`
  const heartsText = cards.flatMap((c) => c.whos.map((w) => reactLine(c, w))).join(' ')
  // 지난 소식을 받는 동안은 '새 소식이 없어요'를 읽지 않는다 — 받은 뒤 문장이 바뀌면 두 번 읽게 된다
  const waiting = loading || (empty && !past.data && !past.error)
  const canAgain = !!past.data?.diaries.length
  const news = again ? past.data : data
  const diary = hearts ? undefined : news?.diaries[index]
  const last = !!news && index === news.diaries.length - 1
  const nick = diary?.author_nickname || diary?.author_name || '가족'
  const sender = [diary?.author_nickname, diary?.author_name].filter(Boolean).join(' ') || '가족'
  const isLiked = diary ? (liked[diary.diary_id] ?? diary.reactions.some((r) => r.by === 'ELDER' && r.kind === 'LIKE')) : false
  const reply = diary ? (replied[diary.diary_id] ?? diary.reactions.find((r) => r.by === 'ELDER' && r.kind === 'REPLY')?.text) : undefined
  // 사진이 없는 가족 일기는 '사진 일기'라고 읽지 않는다 (D64)
  const message = waiting ? undefined : error
    ? error.code === 'DEVICE_REQUIRED' ? '가족이 보낸 연결 링크를 먼저 열어 주세요.' : error.message
    : hearts ? (voice ? undefined : `${heartsTitle}. ${heartsText}`) // 목소리 장은 아래 따로 읽고 튼다
      : diary ? `${sender}${josa(sender, '이', '가')} ${diary.illustration_url ? '사진 일기' : '일기'}를 보냈어요. 읽어 드릴게요. ${diary.body}`
        : !data ? undefined
          : canAgain ? `${NO_NEWS} ${AGAIN_GUIDE}` : NO_NEWS

  useEffect(() => {
    if (message) void speak(message, speed)
    return () => stopSpeaking()
  }, [message, diary?.diary_id, speed])

  useEffect(() => () => clearTimeout(sayingTimer.current), [])

  /** 가족 목소리를 처음부터 튼다. 다시 누르면 멈춘다 */
  const playSeq = useRef(0) // 마지막으로 시작한 재생만 '다 들음'을 표시한다
  const manual = useRef(false) // 이 장에서 재생 줄을 눌렀다 — 안내가 끊겨 끝나도 저절로 다시 틀지 않는다
  async function playFamily(url: string) {
    const my = ++playSeq.current
    setPlaying(true)
    await playVoice(url)
    if (live.current && my === playSeq.current) setPlaying(false)
  }
  function toggleFamily(url: string) {
    manual.current = true
    if (!playing) return void playFamily(url)
    playSeq.current++
    stopSpeaking()
    setPlaying(false)
  }

  // 목소리 장: "큰딸이 11월 24일 일기에 목소리로 답장을 보냈어요." 를 읽고 바로 그 목소리를 틀어 드린다 (D99)
  const voiceKey = voice?.at
  useEffect(() => {
    if (!voice?.audio_url) return
    let here = true
    manual.current = false
    const who = voice.name || '가족'
    const url = voice.audio_url
    void speak(`${who}${josa(who, '이', '가')} ${day(voice.diary_posted_at)} 일기에 목소리로 답장을 보냈어요.`, speed).then((heard) => {
      // 자동 재생이 막혔으면(heard false) 재생 줄을 누르면 된다. 안내 중에 눌렀으면 이미 튼다
      if (here && heard && !manual.current) void playFamily(url)
    })
    return () => {
      here = false
      stopSpeaking()
      setPlaying(false)
    }
    // 장이 바뀔 때만 (voice 는 받은 목록의 같은 칸)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceKey])

  function replay(text: string) {
    void speak(text, speed)
    setSaying(true)
    clearTimeout(sayingTimer.current)
    sayingTimer.current = setTimeout(() => setSaying(false), 1_400)
  }

  function fail(e: unknown) {
    const text = e instanceof ApiError ? e.message : '연결이 잠깐 끊겼어요. 다시 해 주세요.'
    setReadError(text)
    void speak(text, speed)
  }

  /** 서버에 적은 뒤에만 다음 장으로 넘어간다. 두 번 눌러도 한 번만 보낸다 */
  async function send(path: string, body: unknown, next: () => void) {
    if (reading.current) return
    reading.current = true
    setBusy(true)
    setReadError(undefined)
    try {
      await api(path, body === undefined ? { method: 'POST' } : { body })
      if (!live.current) return
      clearTimeout(sayingTimer.current)
      setSaying(false)
      next()
    } catch (e) {
      if (live.current) fail(e)
    } finally {
      reading.current = false
      if (live.current) setBusy(false)
    }
  }

  function heardHearts() {
    if (!hearts) return
    if (heartPage < heartPages - 1) return setHeartPage((p) => p + 1) // 받은 반응의 다음 장 — 들음 표시는 마지막 장에서
    // 읽어 드린 마지막 반응까지만 '들음' — 그사이에 온 것은 다음에 읽어 드린다 (D63)
    void send('/api/elder/hearts/heard', { until: hearts[hearts.length - 1].at }, () => {
      if (data!.diaries.length) setHeartsHeard(true)
      else nav('/elder', { replace: true })
    })
  }

  function markRead() {
    if (!diary) return
    const next = () => {
      // 목록을 다시 읽으면 읽은 일기가 빠져 번호가 밀린다. 받은 목록에서 번호만 바꾼다.
      if (last) nav('/elder', { replace: true })
      else setIndex((value) => value + 1)
    }
    if (again) {
      // 다시 듣기는 읽음 표시를 바꾸지 않는다 — 서버에 적지 않고 넘긴다
      clearTimeout(sayingTimer.current)
      setSaying(false)
      next()
    } else void send(`/api/elder/diaries/${diary.diary_id}/read`, undefined, next)
  }

  /** 하트 — 다시 눌러도 지워지지 않는다 (D64). 먼저 보낸 것으로 보이고, 실패하면 되돌린다 */
  async function like() {
    if (!diary || isLiked || liking.current) return
    liking.current = true // 한 화면 그림 안에 두 번 눌러도 한 번만 보낸다
    const id = diary.diary_id
    setReadError(undefined)
    setLiked((map) => ({ ...map, [id]: true }))
    void speak('하트를 보냈어요.', speed)
    try {
      await api(`/api/elder/diaries/${id}/like`, { body: { on: true } })
    } catch (e) {
      if (!live.current) return
      setLiked((map) => ({ ...map, [id]: false }))
      fail(e)
    } finally {
      liking.current = false
    }
  }

  const heartFill = <span className="family-hf">{IC.heartFill}</span>
  let body: ReactNode = null
  if (waiting) body = <p className="elder-text" role="status">잠시만요…</p>
  else if (error)
    body = <ElderStop text={message} onRetry={error.code !== 'DEVICE_REQUIRED' ? reload : undefined} />
  else if (voice?.audio_url) {
    // 가족 목소리 답장 한 장 (D99, 11/24 사용자 그림): 보낸 사람 · 재생 줄(누르면 다시 듣기/멈춤) · 받아 적은 자막
    const who = voice.name || '가족'
    const url = voice.audio_url
    body = (
      <>
        <h1 className="elder-sr">가족 목소리 답장</h1>
        <div className="family-sender">
          <span className="elder-av family-av" aria-hidden="true">{who[0]}</span>
          <span><b>{who}</b><small>{day(voice.diary_posted_at)} 일기에 답장을 보냈어요</small></span>
          {voices.length > 1 && <span className="family-page">{heartPage + 1} / {voices.length}</span>}
        </div>
        <div className="elder-grow family-voice-wrap">
          <button
            type="button"
            className={`family-voice${playing ? ' on' : ''}`}
            onClick={() => toggleFamily(url)}
            aria-label={playing ? '목소리 멈추기' : `${who} 목소리 듣기`}
          >
            <span className="family-voice-dot" aria-hidden="true">{playing ? IC.stop : <span className="family-voice-tri" />}</span>
            <span className="family-voice-bars" aria-hidden="true">
              {BARS.map((h, i) => <i key={i} style={{ height: `${h}%` }} />)}
            </span>
            {voice.audio_sec ? <b>{voice.audio_sec}초</b> : null}
          </button>
          {voice.text && <p className="elder-paper family-voice-cap">{voice.text}</p>}
        </div>
        {readError && <p className="elder-text" role="alert">{readError}</p>}
        <div className="elder-dock">
          <button type="button" className="elder-btn" disabled={busy} onClick={heardHearts}>
            <span className="elder-dot">{IC.next}</span>
            {busy ? '잠시만요…' : heartPage < heartPages - 1 || data!.diaries.length ? '다음 소식' : '홈으로'}
          </button>
        </div>
      </>
    )
  } else if (hearts)
    body = (
      <>
        <h1>{heartsTitle}</h1>
        <div className="family-reacts">
          {cards.map((c) => (
            // 누르면 그 일기를 크게 — 가족이 보낸 것 전부와 일기를 다시 본다 (11/25 실사용: 눌러 보고 싶게 생겼다)
            <button key={c.diary_id} type="button" className="family-react" onClick={() => nav('/elder/diaries', { state: { home, openId: c.diary_id } })}>
              <span className="family-rdiary">
                {c.thumb && <img src={c.thumb} alt="" />}
                <span><small>{day(c.at)} 쓴 일기</small><span className="family-rbody">{c.body}</span></span>
              </span>
              {c.whos.map((w) => (
                <span key={w.who + (w.reply ?? '')} className="family-rwho">
                  <span className="elder-av" aria-hidden="true">{w.who[0]}</span>
                  <span><b>{w.who}</b> {w.reply ? <q>{w.reply}</q> : <>{heartFill}{wordsText(w.words)} 보냈어요</>}</span>
                </span>
              ))}
              <span className="family-rgo">눌러서 일기 보기{IC.next}</span>
            </button>
          ))}
        </div>
        {readError && <p className="elder-text" role="alert">{readError}</p>}
        <div className="elder-dock">
          <button type="button" className="elder-btn" disabled={busy} onClick={heardHearts}>
            <span className="elder-dot">{IC.next}</span>{busy ? '잠시만요…' : data!.diaries.length ? '다음 소식' : '홈으로'}
          </button>
        </div>
      </>
    )
  else if (diary)
    body = (
      <>
        <h1 className="elder-sr">가족 소식</h1>
        <div className="family-sender">
          <span className="elder-av family-av" aria-hidden="true">{(diary.author_name || nick)[0]}</span>
          <span><b>{nick}</b>{diary.author_nickname && diary.author_name && <small>{diary.author_name}</small>}</span>
          <span className="family-page">{index + 1} / {news!.diaries.length}</span>
        </div>
        {diary.illustration_url
          ? <ElderPhoto src={diary.illustration_url} alt="가족이 보낸 사진" />
          : <Sim face="smile" size={168} className="elder-sim elder-simflex" />}
        <FamilyPaper key={diary.diary_id} body={diary.body} saying={saying} onRead={() => replay(diary.body)} />
        {reply && <p className="elder-sent-ok">{IC.chat}답장: {reply}</p>}
        {readError && <p className="elder-text" role="alert">{readError}</p>}
        <div className="elder-dock">
          <div className="elder-row">
            {isLiked
              ? <p className="elder-sent-ok family-grow">{heartFill}보냈어요</p>
              : <button type="button" className="elder-btn elder-btn--secondary" onClick={() => void like()}>{heartFill}하트</button>}
            {!reply && (
              <button type="button" className="elder-btn family-talk" onClick={() => setReplying(true)} disabled={busy}>
                <span className="elder-dot">{IC.mic}</span>말로 답하기
              </button>
            )}
          </div>
          <button type="button" className={`elder-btn${reply || isLiked ? '' : ' elder-btn--secondary'}`} disabled={busy} onClick={markRead}>
            {busy ? '잠시만요…' : last ? '홈으로' : '다음 소식'}
          </button>
        </div>
        {replying && (
          <ReplySheet
            diary={diary}
            to={nick}
            speed={speed}
            onClose={() => setReplying(false)}
            onSent={(text) => {
              setReplied((map) => ({ ...map, [diary.diary_id]: text }))
              setReplying(false)
              void speak(`${nick}에게 답장을 보냈어요.`, speed)
            }}
          />
        )}
      </>
    )
  else if (data)
    body = (
      <>
        <div className="elder-grow elder-center">
          <div className="elder-halo"><Sim face="hello" size={150} className="elder-sim" /></div>
          <h1>{NO_NEWS}</h1>
          {canAgain && <p className="elder-sub">{AGAIN_GUIDE}</p>}
        </div>
        {canAgain && <button type="button" className="elder-btn elder-btn--secondary" onClick={() => setAgain(true)}>지난 소식 다시 듣기</button>}
        <button type="button" className="elder-btn" onClick={() => nav('/elder', { replace: true })}>홈으로</button>
      </>
    )

  return <main className="elder elder--fit elder-family">{body}</main>
}
