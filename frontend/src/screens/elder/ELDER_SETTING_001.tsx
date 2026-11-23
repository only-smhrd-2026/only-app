/**
 * ELDER_SETTING_001 — 어르신 설정 (11/23 새 화면, 시안 e-settings). 홈 '설정' 칸에서 온다.
 * 글자 크기·목소리·말 빠르기를 3칸(목소리는 2칸) 중에 누르면 바로 바뀐다 → PATCH /api/elder/settings (가족방 설정 칸과 같은 값).
 * 누르는 순간 화면·목소리에 먼저 반영하고, 저장이 실패하면 되돌린 뒤 소리로 알린다.
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { ElderHomeOut, ElderSettingsIn, ElderSettingsOut } from '../../api/types'
import { IC } from '../../components/ElderUi'
import type { ElderNavState } from '../../hooks/useElderSession'
import { PROMPT, say, setVoice, speak, stopSpeaking } from '../../lib/audio'
import { setElderFont } from '../../lib/elderFont'
import './ELDER_SETTING_001.css'

const FONTS = [['L', '보통'], ['XL', '크게'], ['XXL', '아주 크게']] as const
const VOICES = [['FEMALE', '여자 목소리'], ['MALE', '남자 목소리']] as const
const SPEEDS = [['0.80', '천천히'], ['0.90', '보통'], ['1.00', '조금 빠르게']] as const
const INTRO = '설정이에요. 글자 크기, 목소리, 말 빠르기를 바꿀 수 있어요.'

export default function ELDER_SETTING_001() {
  const { home } = (useLocation().state ?? {}) as ElderNavState
  const [set, setSet] = useState<ElderSettingsOut | undefined>(home?.settings)
  const [error, setError] = useState<string>()
  const speed = Number(set?.tts_speed) || 0.9

  // 새로고침 등으로 홈 정보가 없으면 서버에서 읽는다
  useEffect(() => {
    if (set) return
    api<ElderHomeOut>('/api/elder/home').then((h) => setSet(h.settings), (e: unknown) => setError(e instanceof ApiError ? e.message : '설정을 읽지 못했어요.'))
  }, [set])

  useEffect(() => {
    void speak(INTRO, speed)
    return () => stopSpeaking()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 들어올 때 한 번만
  }, [])

  const latest = useRef(0)
  function apply(s: ElderSettingsOut) {
    setSet(s)
    setElderFont(s.font_size)
    setVoice(s.tts_voice)
  }

  async function change(patch: ElderSettingsIn, after: (s: ElderSettingsOut) => void) {
    if (!set) return
    const mine = ++latest.current // 빨리 연달아 누르면 마지막 누름의 응답만 반영한다
    const before = set
    const next = { ...set, ...patch }
    setError(undefined)
    apply(next)
    after(next)
    try {
      const saved = await api<ElderSettingsOut>('/api/elder/settings', { method: 'PATCH', body: patch })
      if (mine === latest.current) apply(saved)
    } catch (e) {
      if (mine !== latest.current) return // 뒤에 누른 것이 있으면 그 결과를 따른다
      apply(before)
      const message = e instanceof ApiError ? e.message : '바꾸지 못했어요. 다시 눌러 주세요.'
      setError(message)
      void speak(message, Number(before.tts_speed) || 0.9)
    }
  }

  const pick3 = <T extends string>(items: readonly (readonly [T, string])[], on: string | undefined, onPick: (v: T) => void) => (
    <div className="eset-pick">
      {items.map(([v, label]) => (
        <button
          key={v}
          type="button"
          className={`elder-btn elder-btn--secondary${on === v ? ' elder-btn--on' : ''}`}
          aria-pressed={on === v}
          disabled={!set}
          onClick={() => onPick(v)}
        >
          {on === v && IC.check}
          {label}
        </button>
      ))}
    </div>
  )
  const speedKey = set ? Number(set.tts_speed).toFixed(2) : undefined

  return (
    <main className="elder eset">
      <h1>설정</h1>
      <section className="eset-group">
        <h2>글자 크기</h2>
        <p className="elder-sub" style={{ fontSize: 'var(--elder-font-size)' }}>가나다 글자가 잘 보이세요?</p>
        {pick3(FONTS, set?.font_size, (v) => void change({ font_size: v }, (s) => void speak('이 크기로 바꿨어요.', Number(s.tts_speed) || 0.9)))}
      </section>
      <section className="eset-group">
        <h2>목소리</h2>
        {pick3(VOICES, set?.tts_voice, (v) => void change({ tts_voice: v }, (s) => void say(PROMPT.voiceHello, Number(s.tts_speed) || 0.9, null, v)))}
      </section>
      <section className="eset-group">
        <h2>말 빠르기</h2>
        {pick3(SPEEDS, speedKey, (v) => void change({ tts_speed: v }, () => void speak('이 빠르기로 말씀드릴게요.', Number(v))))}
      </section>
      {error && <p className="elder-text" role="alert">{error}</p>}
      <p className="elder-sub">누르면 바로 바뀌어요. 가족도 가족방 설정에서 바꿀 수 있어요.</p>
    </main>
  )
}
