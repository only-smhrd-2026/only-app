/**
 * GROUP_002 — 가족방 탭 (11/23 시안 f-room, 이슈 #24). 위 막대에서 고른 분의 가족방 한 화면:
 * 할머니 폰(연결됨·마지막으로 연 때 / 연결 3단계) → '올린 사진 n장 ›'(사진첩 탭) → 구성원(초대·내보내기·쓸 수 있는 링크)
 * → 할머니 화면 설정(#52, D74 — 글자 크기·말 속도·목소리·말하는 방법은 칩을 누르면 바로 저장, 추억 시간·이름·부르는 말은 판에서)
 * → 위험한 설정(폰 연결 끊기·가족방 나가기·회원 탈퇴). 버튼은 방장에게만, 방장이 아니면 보기만.
 * 링크 주소(토큰)는 이 화면 state 에만 둔다 (D16 — localStorage·console 금지). 서버는 토큰을 저장하지 않아 나가면 다시 못 본다.
 */
import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type {
  InviteCreatedOut,
  InviteKind,
  InviteOut,
  MemberOut,
  RelationTag,
  RoomOut,
  RoomSettingsIn,
} from '../../api/types'
import FamIcon from '../../components/FamIcon'
import { Avatar } from '../../components/FamilyFrame'
import Sim from '../../components/Sim'
import { useFamily } from '../../hooks/useFamily'
import { useFetch } from '../../hooks/useFetch'
import { PROMPT, say, stopSpeaking } from '../../lib/audio'
import { logout } from '../../lib/logout'
import './GROUP_002.css'

// ── 할머니 화면 설정 (목업 ⑥ 설정 판, D74). 일기 시간은 넣지 않음(11/13 결정). 이름·부르는 말은 아래 TEXTS(글로 고치기)
type ElderKey = 'elder_name' | 'elder_honorific'
type SetKey = Exclude<keyof RoomSettingsIn, 'diary_time' | ElderKey>
type SetDef = { key: SetKey; name: string; help: (hon: string) => string; opts: [value: string, label: string, px?: number][] }

const hourLabel = (h: number) => (h === 0 ? '밤 12시' : h < 12 ? `오전 ${h}시` : h === 12 ? '낮 12시' : `오후 ${h - 12}시`)
const SETS: SetDef[] = [
  {
    key: 'memory_time',
    name: '추억 시간',
    help: () => '매일 이 시간에 오늘의 한 장이 정해져요',
    opts: Array.from({ length: 24 }, (_, h) => [`${String(h).padStart(2, '0')}:00`, hourLabel(h)]), // 정각만 (D44)
  },
  {
    key: 'font_size',
    name: '글자 크기',
    help: (hon) => `${hon} 화면의 글자 크기예요`,
    opts: [
      ['L', '보통', 22],
      ['XL', '크게', 24],
      ['XXL', '아주 크게', 28],
    ], // 어르신 화면 글자 22·24·28px (D51) — 그 크기로 미리 보여 준다
  },
  {
    key: 'tts_speed',
    name: '말 속도',
    help: (hon) => `${hon}께 말하는 빠르기예요`,
    opts: [
      ['0.80', '천천히'],
      ['0.90', '보통'],
      ['1.00', '조금 빠르게'],
    ],
  },
  {
    key: 'tts_voice',
    name: '목소리',
    help: (hon) => `${hon}께 들려 드리는 목소리예요 · 고르면 그 목소리로 인사해요`,
    opts: [
      ['FEMALE', '여자 목소리'],
      ['MALE', '남자 목소리'],
    ],
  },
  {
    key: 'device_input_mode',
    name: '말하는 방법',
    help: () => '마이크를 쓰기 어려우시면 버튼만으로도 이야기할 수 있어요',
    opts: [
      ['VOICE', '음성+버튼'],
      ['BUTTON', '버튼만'],
    ],
  },
]
/** 서버 값을 판의 값 모양으로 — 추억 시간 '09:00:00' → '09:00', 말 속도 0.9 → '0.90' */
function curOf(r: RoomOut, k: SetKey) {
  if (k === 'memory_time') return r.memory_time.slice(0, 5)
  if (k === 'tts_speed') return Number(r.tts_speed).toFixed(2)
  return String(r[k])
}
const labelOf = (s: SetDef, v: string) => s.opts.find((o) => o[0] === v)?.[1] ?? v

// ── 글로 고치는 칸 (FR-AD-003·007) — 구성원 호칭(비우면 호칭 없음)·어르신 이름·부르는 말. 글자 수는 서버 schemas/rooms.py 와 같게
const TEXTS: Record<'nickname' | ElderKey, { name: string; max: number; help: (hon: string) => string }> = {
  nickname: { name: '호칭', max: 12, help: (hon) => `${hon}께서 이분을 부르는 말이에요 (예: 큰딸) · 비우면 이름으로 불러요` },
  elder_name: { name: '어르신 이름', max: 10, help: () => '위 막대와 가족 홈에 보이는 이름이에요' },
  elder_honorific: { name: '부르는 말', max: 20, help: () => 'AI 와 가족 화면이 어르신을 부르는 말이에요 (예: 할머니)' },
}

const RELATION: Record<RelationTag, string> = { CHILD: '자녀', GRANDCHILD: '손주', OTHER: '기타' }

type TextSheet = { t: 'text'; k: 'nickname'; m: MemberOut } | { t: 'text'; k: ElderKey }
type Sheet =
  | { t: 'invite'; kind: InviteKind }
  | { t: 'member'; m: MemberOut }
  | { t: 'kick'; m: MemberOut }
  | { t: 'owner'; m: MemberOut }
  | { t: 'unlink' }
  | { t: 'leave' }
  | { t: 'set'; s: SetDef }
  | TextSheet

const msgOf = (e: unknown) => (e instanceof ApiError ? e.message : '잘 안 됐어요. 다시 해 주세요')

/** 남은 시간 — 24시간 이하면 'N시간 남음', 넘으면 'N일 남음' (올림: 방금 만든 가족용 7일, 기기용 24시간).
 * 1분을 빼고 올린다 — 폰 시계가 서버보다 몇 초 늦으면 방금 만든 링크가 '8일'·'2일'로 보인다 */
function timeLeft(expiresAt: string) {
  const ms = new Date(expiresAt).getTime() - Date.now() - 60_000
  return ms <= 86_400_000 ? `${Math.ceil(ms / 3_600_000)}시간 남음` : `${Math.ceil(ms / 86_400_000)}일 남음`
}

/** 마지막으로 연 때 — '오늘 오전 9:12' · '어제 오후 3:05' · '11월 14일 오전 9:12' (한국 시간, D12) */
function seenLabel(iso: string) {
  const KST = { timeZone: 'Asia/Seoul' } as const
  const d = new Date(iso)
  const dayOf = (x: Date) => x.toLocaleDateString('sv-SE', KST)
  const time = d.toLocaleTimeString('ko-KR', { ...KST, hour: 'numeric', minute: '2-digit' })
  if (dayOf(d) === dayOf(new Date())) return `오늘 ${time}`
  if (dayOf(d) === dayOf(new Date(Date.now() - 86_400_000))) return `어제 ${time}`
  return `${d.toLocaleDateString('ko-KR', { ...KST, month: 'long', day: 'numeric' })} ${time}`
}

/** 위 막대에서 다른 분으로 바꾸면 주소의 방 번호만 바뀌고 화면은 그대로 남는다 →
 * key 로 화면을 새로 그려 앞 방의 구성원·링크·판이 새 방 아래에 남지 않게 한다 */
export default function GROUP_002() {
  const { roomId } = useParams()
  return <RoomTab key={roomId} />
}

function RoomTab() {
  const { roomId } = useParams()
  const nav = useNavigate()
  const { me, reloadRooms } = useFamily()
  // 이 탭을 열 때마다 새로 읽는다 — 갤럭시를 연결하고 돌아오면 '연결됐어요', 사진을 올리고 오면 사진 수가 바뀐다
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  // 설정을 바꾸면 서버가 돌려준 RoomOut 의 설정 칸으로 덮어쓴다 — 설정은 이 화면에서만 바뀌어 다시 읽지 않아도 된다
  const [settingsPatch, setSettingsPatch] = useState<Partial<RoomOut>>({})
  const found = rooms.data?.find((r) => String(r.room_id) === roomId)
  const room = found && { ...found, ...settingsPatch }
  const members = useFetch<MemberOut[]>(room ? `/api/rooms/${roomId}/members` : null)
  // 링크 목록은 방장만 부를 수 있다 — 방장이 아니면 부르지 않는다
  const invites = useFetch<InviteOut[]>(room?.is_owner ? `/api/rooms/${roomId}/invites` : null)
  const [sheet, setSheet] = useState<Sheet>()
  // 보내기·복사가 안 됐을 때 판 안에 보여 줄 주소 — 서버가 다시 보여 주지 않으므로 판을 닫거나 칩을 바꿔도 이 화면에 있는 동안 둔다
  const [made, setMade] = useState<Partial<Record<InviteKind, string>>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [note, setNote] = useState<string>()
  const [text, setText] = useState('') // 글로 고치기 판의 입력 칸

  useEffect(() => {
    if (!note) return
    const timer = window.setTimeout(() => setNote(undefined), 2600)
    return () => window.clearTimeout(timer)
  }, [note])

  const open = (s: Sheet) => (setError(undefined), setSheet(s))
  const close = () => (setSheet(undefined), setError(undefined))
  /** 글로 고치기 판 — 지금 값을 넣어 둔 채 연다 */
  const openText = (s: TextSheet, value: string) => (setText(value), open(s))

  /** 서버에 바꾸기를 보내고(body 가 있으면 POST, 없으면 DELETE) → 다시 읽고 → 판을 닫고 → 한 줄 알림. 두 번 눌러도 한 번만 (busy) */
  async function change(path: string, done: string, after: () => void, body?: unknown) {
    if (busy) return
    setBusy(true)
    setError(undefined)
    try {
      await api(path, body === undefined ? { method: 'DELETE' } : { body })
      after()
      setSheet(undefined)
      setNote(done)
    } catch (e) {
      setError(msgOf(e))
    }
    setBusy(false)
  }

  // 가족방 탭을 떠나면(다른 탭·다른 분으로 바꾸기) 들려주던 인사를 멈춘다 — 늦게 끝난 저장 뒤 다른 화면에서 소리가 나지 않게
  useEffect(() => stopSpeaking, [])

  /** 설정 판에서 하나 고르기 → 바뀐 칸만 PATCH → 판 닫고 한 줄 알림.
   * 목소리·말 속도는 고를 때마다 고른 값으로 인사를 들려준다 (D74 '천천히·보통·조금 빠르게 + 들려주기') */
  async function saveSetting(r: RoomOut, s: SetDef, value: string) {
    if (busy) return
    const hello = () => {
      const voice = s.key === 'tts_voice' ? (value as RoomOut['tts_voice']) : r.tts_voice
      const speed = s.key === 'tts_speed' ? Number(value) : Number(r.tts_speed)
      if (s.key === 'tts_voice' || s.key === 'tts_speed') void say(PROMPT.voiceHello, speed, null, voice)
    }
    if (curOf(r, s.key) === value) {
      close() // 앞서 실패한 문장이 판 밖(구성원 카드)에 남지 않게 같이 지운다
      hello() // 같은 값을 다시 눌러도 들어 볼 수 있게
      return
    }
    setBusy(true)
    setError(undefined)
    try {
      const out = await api<RoomOut>(`/api/rooms/${r.room_id}/settings`, { method: 'PATCH', body: { [s.key]: value } })
      setSettingsPatch((p) => ({ ...p, [s.key]: out[s.key] }))
      reloadRooms() // 가족 홈 '매일 오전 9시에…' 문장도 새 값으로
      setSheet(undefined)
      setNote(`바꿨어요 · ${s.name} ${labelOf(s, value)}`)
      hello()
    } catch (e) {
      setError(msgOf(e))
    }
    setBusy(false)
  }

  /** 글로 고치기 [저장] — 호칭은 구성원 PATCH(비우면 null = 호칭 없음), 어르신 이름·부르는 말은 설정 PATCH */
  async function saveText(r: RoomOut, s: TextSheet) {
    if (busy) return
    const value = text.trim()
    const before = s.k === 'nickname' ? (s.m.nickname ?? '') : r[s.k]
    if (value === before) return close() // 같은 값 — 보내지 않고 판만 닫는다(saveSetting 과 같음)
    setBusy(true)
    setError(undefined)
    try {
      if (s.k === 'nickname') {
        await api<MemberOut>(`/api/rooms/${r.room_id}/members/${s.m.user_id}`, {
          method: 'PATCH',
          body: { nickname: value || null },
        })
        members.reload() // 목록을 다시 읽어 그 줄에 새 호칭
      } else {
        const out = await api<RoomOut>(`/api/rooms/${r.room_id}/settings`, { method: 'PATCH', body: { [s.k]: value } })
        setSettingsPatch((p) => ({ ...p, [s.k]: out[s.k] }))
        reloadRooms() // 위 막대·가족 홈 문장도 새 이름으로
      }
      setSheet(undefined)
      const who = s.k === 'nickname' ? `${s.m.name}님 ` : ''
      setNote(value ? `바꿨어요 · ${who}${TEXTS[s.k].name} ${value}` : `${who}호칭을 지웠어요`)
    } catch (e) {
      setError(msgOf(e))
    }
    setBusy(false)
  }

  /** [나가기] (방장 아닌 가족) — 성공하면 가족 홈을 새로 연다(가족방 목록을 처음부터 다시 읽게).
   * 기억해 둔 가족방 번호(haru.fam.room)는 지우지 않는다 — 위 막대·알림이 목록에 없는 방이면 첫 가족방으로 간다 */
  async function leave(r: RoomOut) {
    if (busy) return
    setBusy(true)
    setError(undefined)
    try {
      await api(`/api/rooms/${r.room_id}/leave`, { method: 'POST' }) // 본문 없어도 method 를 적는다(D34)
    } catch (e) {
      // 404 = 이미 이 방 구성원이 아님(다른 기기에서 나감·그새 내보내짐) → 나간 것과 같다
      if (!(e instanceof ApiError && e.status === 404)) {
        setError(msgOf(e))
        setBusy(false)
        return
      }
    }
    // replace — 뒤로 가기로 나간 방 화면('찾을 수 없어요')에 돌아오지 않게. busy 는 그대로 둬 새로 열리는 동안 다시 못 누름
    window.location.replace('/')
  }

  /** [링크 만들고 보내기] — 폰 공유 창(카카오톡·문자), 없으면 복사, 둘 다 안 되면 판 안에 주소 (HOME_001 시작 3단계와 같은 방법) */
  async function makeLink(r: RoomOut, kind: InviteKind) {
    if (busy) return
    setBusy(true)
    setError(undefined)
    try {
      const created = await api<InviteCreatedOut>(`/api/rooms/${r.room_id}/invites`, { body: { kind } })
      invites.reload()
      const text =
        kind === 'ELDER_DEVICE'
          ? `${r.elder_honorific} 폰에서 이 링크를 열어 주세요 — 하루한장`
          : `${r.elder_name} ${r.elder_honorific}네 가족방에 초대해요 — 하루한장`
      let done: string | undefined
      if (navigator.share) {
        // 공유 창을 그냥 닫으면 실패로 온다 → 주소를 보여 줘 다시 보내거나 복사할 수 있게
        done = await navigator.share({ text, url: created.url }).then(
          () => '링크를 보냈어요',
          () => undefined,
        )
      } else if (navigator.clipboard) {
        done = await navigator.clipboard.writeText(created.url).then(
          () => '링크를 복사했어요 · 붙여 넣어 보내 주세요',
          () => undefined,
        )
      }
      // 새 링크를 만들면 전 주소는 못 쓴다 → 보냈으면 지우고, 못 보냈으면 새 주소로 바꾼다
      setMade((m) => ({ ...m, [kind]: done ? undefined : created.url }))
      if (done) {
        setSheet(undefined)
        setNote(done)
      }
    } catch (e) {
      setError(msgOf(e))
    }
    setBusy(false)
  }

  if (rooms.error?.status === 401) return <Navigate to="/login" replace />
  if (rooms.error) {
    return (
      <main className="fam-stack">
        <p className="fam-error">{rooms.error.message}</p>
        <button type="button" className="fam-text-btn" onClick={rooms.reload}>
          다시 시도
        </button>
      </main>
    )
  }
  if (!rooms.data) return <main className="fam-stack" aria-busy="true" />
  if (!room) {
    return (
      <main className="fam-stack">
        <p className="fam-error">가족방을 찾을 수 없어요</p>
        <Link className="fam-text-btn" to="/">
          가족 홈으로
        </Link>
      </main>
    )
  }

  const hon = room.elder_honorific
  const owner = room.is_owner
  const alive = invites.data ?? []
  const elderLinkAlive = alive.some((i) => i.kind === 'ELDER_DEVICE')
  const list = members.data ?? []
  const reloadAll = () => (rooms.reload(), reloadRooms()) // 이 화면 + 위 막대·가족 홈이 같은 숫자를 보게

  const [timeSet, ...chipSets] = SETS // 추억 시간은 24칸이라 판에서, 나머지는 칩으로 바로
  const fontPx = SETS[1].opts.find((o) => o[0] === room.font_size)?.[2]

  return (
    <main className="fam-stack gr">
      <h1 className="gr-sr">가족방</h1>

      {room.device_connected ? (
        <section className="fam-card gr-card gr-dev">
          <span className="fam-av fam-tone-a" aria-hidden="true">
            <Sim face="thumbs" size={40} />
          </span>
          <div>
            <b>{hon} 폰 연결됐어요</b>{' '}
            <i className="fam-tag fam-tag--ok">
              <FamIcon name="check" />
              연결됨
            </i>
            <p className="fam-mini">
              {room.device_last_seen_at ? `마지막으로 연 때 · ${seenLabel(room.device_last_seen_at)}` : `${hon} 폰에서 하루한장이 열려요`}
            </p>
            {/* 11/24: 어르신 폰에서 마이크가 막히면 그 폰이 알려 온다(lib/audio → PATCH /devices/me/permissions) — 켜는 길을 가족에게.
                ponytail: 아래 순서는 아직 실기기로 확인 전 — 갤럭시·아이폰에서 눌러 보고 글을 맞출 것 */}
            {room.device_perm_mic === false && (
              <div className="gr-mic" role="note">
                <b className="gr-danger">{hon} 폰 마이크가 꺼져 있어요</b>
                <p className="fam-mini">말로 일기를 쓰려면 {hon} 폰에서 마이크를 허용해 주세요</p>
                <ul className="fam-mini">
                  <li>갤럭시(크롬 앱·홈 화면 앱): 주소창 왼쪽 자물쇠(또는 ⋮ → 설정 → 사이트 설정) → 마이크 → 허용</li>
                  <li>아이폰: 설정 앱 → Safari → 마이크 → 허용 (또는 Safari 주소창 '가가' → 웹사이트 설정 → 마이크)</li>
                </ul>
              </div>
            )}
          </div>
        </section>
      ) : (
        <section className="fam-card gr-card">
          <div className="gr-dev">
            <span className="fam-av fam-tone-a" aria-hidden="true">
              <Sim face="hello" size={40} />
            </span>
            <div>
              <b>
                {room.elder_name} {hon} 폰을 연결해 주세요
              </b>
              <p className="fam-mini">연결하면 오늘의 한 장과 가족 소식이 {hon} 폰으로 가요</p>
            </div>
          </div>
          <ol className="gr-steps3">
            <li>
              <b>연결 링크 보내기</b>
              <span className="fam-mini">카카오톡으로 {hon}께 보내요</span>
            </li>
            <li>
              <b>{hon} 폰에서 링크 열기</b>
              <span className="fam-mini">[시작하기] → 마이크 '허용' · 곁에 계시면 같이 눌러 드려요</span>
            </li>
            <li>
              <b>홈 화면에 추가</b>
              <span className="fam-mini">크롬 메뉴 ⋮ → 홈 화면에 추가 · 다음부터 아이콘 하나로 열려요</span>
            </li>
          </ol>
          {room.photo_count < 3 ? (
            <>
              <p className="gr-lock">
                <FamIcon name="lock" />
                추억 사진을 3장 올리면 연결 링크를 보낼 수 있어요 (지금 {room.photo_count}장)
              </p>
              <Link className="fam-btn" to="/upload">
                <FamIcon name="image" />
                사진 올리기
              </Link>
            </>
          ) : !owner ? (
            <p className="fam-mini">방장이 연결 링크를 보내면 연결돼요</p>
          ) : (
            <>
              {elderLinkAlive && <p className="fam-mini">링크를 보냈어요 · {hon} 폰에서 열면 연결돼요</p>}
              <button type="button" className="fam-btn fam-btn--primary" onClick={() => open({ t: 'invite', kind: 'ELDER_DEVICE' })}>
                {elderLinkAlive ? '연결 링크 다시 보내기' : '연결 링크 보내기'}
              </button>
            </>
          )}
        </section>
      )}

      <Link className="fam-card gr-banner" to="/photos">
        <span className="gr-sq">
          <FamIcon name="image" />
        </span>
        <b>올린 사진 {room.photo_count}장</b>
        <FamIcon name="chevRight" />
      </Link>

      <section className="fam-card gr-card gr-members-card">
        <div className="gr-h-row">
          <h2>구성원 {members.data ? list.length : room.member_count}명</h2>
          {owner && (
            <button type="button" className="fam-btn fam-btn--sm" onClick={() => open({ t: 'invite', kind: 'FAMILY' })}>
              <FamIcon name="plus" />
              초대
            </button>
          )}
        </div>
        {members.error ? (
          <div>
            <p className="fam-error">{members.error.message}</p>
            <button type="button" className="fam-text-btn" onClick={members.reload}>
              다시 시도
            </button>
          </div>
        ) : (
          list.map((m) => (
            <div key={m.user_id} className="gr-setrow gr-member">
              <Avatar name={m.name} />
              <div>
                <b>
                  {m.name}
                  {m.nickname ? ` · ${m.nickname}` : ''}
                </b>
                <small className="fam-mini">
                  {RELATION[m.relation_tag]}
                  {m.is_owner ? ' · 방장' : ''}
                </small>
              </div>
              {m.user_id === me?.user_id && <i className="fam-tag">나</i>}
              {/* 방장은 자기 줄에도 ⋮ — 자기 호칭도 고칠 수 있게(판에서 내보내기는 숨김) */}
              {owner && (
                <button type="button" className="fam-icon-btn gr-more" onClick={() => open({ t: 'member', m })} aria-label={`${m.name} 더 보기`}>
                  ⋮
                </button>
              )}
            </div>
          ))
        )}
        {alive.map((i) => (
          <div key={i.kind} className="gr-link">
            <span>
              {i.kind === 'FAMILY' ? '가족 초대 링크' : `${hon} 폰 링크`} · {timeLeft(i.expires_at)}
            </span>
            <button
              type="button"
              className="fam-text-btn gr-danger"
              disabled={busy}
              onClick={() =>
                change(`/api/rooms/${roomId}/invites/${i.kind}`, '링크를 폐기했어요 · 이제 열리지 않아요', () => {
                  invites.reload()
                  setMade((m) => ({ ...m, [i.kind]: undefined })) // 폐기한 주소는 판에서도 지운다
                })
              }
            >
              폐기
            </button>
          </div>
        ))}
        {!sheet && error && (
          <p className="fam-error" role="alert">
            {error}
          </p>
        )}
      </section>

      <section className="fam-card gr-card">
        <h2>
          {room.elder_name} {hon} 화면 설정
        </h2>
        <p className="fam-mini gr-owner-note">
          {owner ? `바꾸면 바로 저장돼요 · ${hon}의 다음 대화부터 바뀌어요` : '방장만 바꿀 수 있어요. 다른 가족에게는 읽기만 보여요.'}
        </p>
        {(['elder_name', 'elder_honorific'] as const).map((k) => (
          <button key={k} type="button" className="gr-setrow gr-set" disabled={!owner} onClick={() => openText({ t: 'text', k }, room[k])}>
            <span>{TEXTS[k].name}</span>
            <b>{room[k]}</b>
            {owner && <FamIcon name="chevRight" className="gr-chev" />}
          </button>
        ))}
        <div className="gr-setrow">
          <div className="gr-grow">
            <b>{timeSet.name}</b>
            <p className="fam-mini">{timeSet.help(hon)}</p>
          </div>
          <button type="button" className="fam-btn fam-btn--sm" disabled={!owner} onClick={() => open({ t: 'set', s: timeSet })}>
            {labelOf(timeSet, curOf(room, timeSet.key))}
          </button>
        </div>
        {chipSets.map((s) => (
          <div key={s.key} className="gr-seg" role="group" aria-label={s.name}>
            <p className="gr-label" aria-hidden="true">
              {s.name}
            </p>
            <div className="fam-seg fam-seg--fill">
              {s.opts.map(([v, label]) => (
                <button
                  key={v}
                  type="button"
                  className="fam-chip"
                  aria-pressed={v === curOf(room, s.key)}
                  disabled={!owner || busy}
                  onClick={() => saveSetting(room, s, v)}
                >
                  {label}
                </button>
              ))}
            </div>
            {s.key === 'font_size' && fontPx && (
              <p className="gr-font-prev" style={{ fontSize: fontPx }}>
                {room.elder_name} {hon}, 안녕하세요
              </p>
            )}
          </div>
        ))}
        {!sheet && note === undefined && error === undefined ? null : null}
      </section>

      <section className="fam-card gr-card">
        <h2>위험한 설정</h2>
        {owner && room.device_connected && (
          <>
            <button type="button" className="fam-btn fam-btn--danger" onClick={() => open({ t: 'unlink' })}>
              {hon} 폰 연결 끊기
            </button>
            <p className="fam-mini">끊으면 {hon} 폰에 사진과 소식이 더 가지 않아요. 다시 쓰려면 새 연결 링크가 필요해요.</p>
          </>
        )}
        {/* 방장은 나갈 수 없다(서버 OWNER_CANNOT_LEAVE) — 방장 아닌 가족에게만 */}
        {!owner && (
          <button type="button" className="fam-btn fam-btn--danger" onClick={() => open({ t: 'leave' })}>
            이 가족방 나가기
          </button>
        )}
        {/* 로그아웃 — 바꾸기 판에만 있어 못 찾았다(11/24 실사용). 탈퇴보다 잘 보이게, 보통 버튼 */}
        <button type="button" className="fam-btn" onClick={() => logout(nav)}>
          로그아웃
        </button>
        {/* 회원 탈퇴 화면(ACCOUNT_001)으로 — 방장도 여기서 간다(방장 넘기기는 그 화면이 묻는다) */}
        <Link className="fam-text-btn gr-withdraw" to="/account/withdraw">
          회원 탈퇴
        </Link>
      </section>

      {sheet && (
        <>
          <button type="button" className="fam-scrim" aria-label="닫기" onClick={close} />
          <div className="fam-sheet" role="dialog" aria-label={sheetLabel(sheet, hon)}>
            <span className="fam-grab" />
            {sheet.t === 'invite' && (
              <>
                <h2>초대하기</h2>
                <div className="gr-chips">
                  {(['FAMILY', 'ELDER_DEVICE'] as const).map((k) => (
                    <button
                      key={k}
                      type="button"
                      className={sheet.kind === k ? 'gr-chip on' : 'gr-chip'}
                      onClick={() => open({ t: 'invite', kind: k })}
                    >
                      {k === 'FAMILY' ? '가족' : `${hon} 폰`}
                    </button>
                  ))}
                </div>
                <p className="gr-sheet-text">
                  {sheet.kind === 'FAMILY'
                    ? '가족이 링크를 열어 이름과 호칭을 정하고 들어와요 · 7일 동안 쓸 수 있어요'
                    : `${hon} 폰에서 한 번 열면 연결돼요 · 24시간 안에 한 번만 쓸 수 있어요`}
                </p>
                {sheet.kind === 'ELDER_DEVICE' && room.photo_count < 3 ? (
                  <>
                    <p className="gr-warn">
                      <FamIcon name="lock" />
                      추억 사진을 3장 올리면 만들 수 있어요 (지금 {room.photo_count}장)
                    </p>
                    <Link className="fam-text-btn gr-to-upload" to="/upload">
                      사진 올리기
                    </Link>
                  </>
                ) : (
                  alive.some((i) => i.kind === sheet.kind) && (
                    <p className="gr-sheet-text">새로 만들면 전에 보낸 링크는 더 쓸 수 없어요</p>
                  )
                )}
                {/* 기기 링크를 열면 그 폰이 새 기기가 되고 지금 폰은 끊긴다 (가족방당 1대, D38) */}
                {sheet.kind === 'ELDER_DEVICE' && room.device_connected && (
                  <p className="gr-warn">
                    이 링크를 열면 지금 연결된 {hon} 폰은 끊겨요. 폰을 바꿀 때만 보내 주세요
                  </p>
                )}
                {made[sheet.kind] && (
                  <p className="gr-url">
                    주소를 길게 눌러 복사해 보내 주세요 (화면을 나가면 다시 볼 수 없어요)
                    <br />
                    {made[sheet.kind]}
                  </p>
                )}
                <div className="gr-cta">
                  <button
                    type="button"
                    className="fam-btn fam-btn--primary fam-btn--block"
                    disabled={busy || (sheet.kind === 'ELDER_DEVICE' && room.photo_count < 3)}
                    onClick={() => makeLink(room, sheet.kind)}
                  >
                    {busy ? '만드는 중…' : made[sheet.kind] ? '새로 만들고 다시 보내기' : '링크 만들고 보내기'}
                  </button>
                </div>
              </>
            )}
            {sheet.t === 'member' && (
              <>
                <div className="gr-person">
                  <Avatar name={sheet.m.name} />
                  <div>
                    <b>
                      {sheet.m.name}
                      {sheet.m.nickname ? ` · ${sheet.m.nickname}` : ''}
                    </b>
                    <small>{RELATION[sheet.m.relation_tag]}</small>
                  </div>
                </div>
                <button
                  type="button"
                  className="fam-opt"
                  onClick={() => openText({ t: 'text', k: 'nickname', m: sheet.m }, sheet.m.nickname ?? '')}
                >
                  <span>
                    <b>호칭 고치기</b>
                    <small>
                      {hon}께서 부르는 말 · 지금 {sheet.m.nickname ?? '없음'}
                    </small>
                  </span>
                </button>
                {/* 방장(=내 줄)은 내보낼 수 없다 — 서버도 CANNOT_REMOVE_OWNER 로 거절 */}
                {/* 방장 넘기기 (D98) — 넘긴 나는 보통 가족으로 남는다 */}
                {!sheet.m.is_owner && (
                  <button type="button" className="fam-opt" onClick={() => open({ t: 'owner', m: sheet.m })}>
                    <span>
                      <b>방장 넘기기</b>
                      <small>넘기면 나는 보통 가족이 돼요</small>
                    </span>
                  </button>
                )}
                {!sheet.m.is_owner && (
                  <button type="button" className="fam-opt gr-opt-danger" onClick={() => open({ t: 'kick', m: sheet.m })}>
                    <span>
                      <b>가족방에서 내보내기</b>
                      <small>내보내면 되돌릴 수 없어요</small>
                    </span>
                  </button>
                )}
              </>
            )}
            {sheet.t === 'kick' && (
              <>
                <h2>{sheet.m.name}님을 내보낼까요?</h2>
                <p className="gr-sheet-text">
                  {room.elder_name} {hon}네 일기와 알림을 더 볼 수 없고, 되돌릴 수 없어요.
                </p>
                <div className="gr-cta gr-cta-two">
                  <button type="button" className="fam-btn fam-btn--tonal" onClick={close}>
                    취소
                  </button>
                  <button
                    type="button"
                    className="fam-btn gr-btn-danger"
                    disabled={busy}
                    onClick={() =>
                      change(`/api/rooms/${roomId}/members/${sheet.m.user_id}`, `${sheet.m.name}님을 내보냈어요`, () => {
                        members.reload()
                        reloadAll()
                      })
                    }
                  >
                    내보내기
                  </button>
                </div>
              </>
            )}
            {sheet.t === 'owner' && (
              <>
                <h2>{sheet.m.name}님에게 방장을 넘길까요?</h2>
                <p className="gr-sheet-text">
                  새 방장이 초대 링크, {hon} 폰 연결, 구성원 내보내기, {hon} 설정을 맡아요. 나는 보통 가족으로 남고, 내가 다시
                  가져올 수는 없어요.
                </p>
                <div className="gr-cta gr-cta-two">
                  <button type="button" className="fam-btn fam-btn--tonal" onClick={close}>
                    취소
                  </button>
                  <button
                    type="button"
                    className="fam-btn fam-btn--primary"
                    disabled={busy}
                    onClick={() =>
                      change(
                        `/api/rooms/${roomId}/owner`,
                        `${sheet.m.name}님이 이제 방장이에요`,
                        () => {
                          members.reload()
                          reloadAll()
                        },
                        { user_id: sheet.m.user_id },
                      )
                    }
                  >
                    넘기기
                  </button>
                </div>
              </>
            )}
            {sheet.t === 'set' && (
              <>
                <h2>{sheet.s.name}</h2>
                <p className="gr-sheet-text">{sheet.s.help(hon)}</p>
                <div className="gr-opts">
                  {sheet.s.opts.map(([v, label, px]) => {
                    const on = v === curOf(room, sheet.s.key)
                    return (
                      <button
                        key={v}
                        type="button"
                        className={on ? 'fam-opt on' : 'fam-opt'}
                        // 추억 시간은 24줄이라 판을 열면 고른 줄이 안 보일 수 있다 → 열릴 때 고른 줄까지 스크롤
                        ref={on ? (el) => el?.scrollIntoView({ block: 'center' }) : undefined}
                        disabled={busy}
                        onClick={() => saveSetting(room, sheet.s, v)}
                      >
                        <span>
                          <b>{label}</b>
                          {px && (
                            <small className="gr-font-prev" style={{ fontSize: px }}>
                              {room.elder_name} {hon}, 안녕하세요
                            </small>
                          )}
                        </span>
                        {on && <FamIcon name="check" className="fam-ok" />}
                      </button>
                    )
                  })}
                </div>
              </>
            )}
            {sheet.t === 'text' && (
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  void saveText(room, sheet)
                }}
              >
                <h2>{sheet.k === 'nickname' ? `${sheet.m.name}님 호칭` : TEXTS[sheet.k].name}</h2>
                <p className="gr-sheet-text">{TEXTS[sheet.k].help(hon)}</p>
                <input
                  className="gr-input"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  maxLength={TEXTS[sheet.k].max}
                  aria-label={TEXTS[sheet.k].name}
                  placeholder={`${TEXTS[sheet.k].max}자까지`}
                />
                <div className="gr-cta">
                  <button
                    type="submit"
                    className="fam-btn fam-btn--primary fam-btn--block"
                    disabled={busy || (sheet.k !== 'nickname' && !text.trim())} // 이름·부르는 말은 빈 칸 안 됨(서버 1자 이상)
                  >
                    {busy ? '저장하는 중…' : '저장'}
                  </button>
                </div>
              </form>
            )}
            {sheet.t === 'leave' && (
              <>
                <h2>
                  {room.elder_name} {hon}네 가족방에서 나갈까요?
                </h2>
                <p className="gr-sheet-text">
                  나가면 이 가족방 일기와 사진을 볼 수 없어요. 다시 들어오려면 초대 링크를 받아요. 내가 쓴 일기는 남아요.
                </p>
                <div className="gr-cta gr-cta-two">
                  <button type="button" className="fam-btn fam-btn--tonal" onClick={close}>
                    취소
                  </button>
                  <button type="button" className="fam-btn gr-btn-danger" disabled={busy} onClick={() => leave(room)}>
                    {busy ? '나가는 중…' : '나가기'}
                  </button>
                </div>
              </>
            )}
            {sheet.t === 'unlink' && (
              <>
                <h2>{hon} 폰 연결을 해제할까요?</h2>
                <p className="gr-sheet-text">
                  해제하면 {hon} 폰에서 하루한장이 열리지 않아요. 다시 쓰려면 {hon} 폰 링크를 새로 보내 주세요.
                </p>
                <div className="gr-cta gr-cta-two">
                  <button type="button" className="fam-btn fam-btn--tonal" onClick={close}>
                    취소
                  </button>
                  <button
                    type="button"
                    className="fam-btn gr-btn-danger"
                    disabled={busy}
                    onClick={() => change(`/api/rooms/${roomId}/device`, '연결을 해제했어요', reloadAll)}
                  >
                    연결 해제
                  </button>
                </div>
              </>
            )}
            {error && (
              <p className="fam-error" role="alert">
                {error}
              </p>
            )}
          </div>
        </>
      )}

      {note && (
        <p className="gr-snack" role="status">
          {note}
        </p>
      )}
    </main>
  )
}

function sheetLabel(s: Sheet, hon: string) {
  if (s.t === 'invite') return '초대하기'
  if (s.t === 'member') return `${s.m.name} 더 보기`
  if (s.t === 'kick') return `${s.m.name}님 내보내기`
  if (s.t === 'owner') return `${s.m.name}님에게 방장 넘기기`
  if (s.t === 'set') return s.s.name
  if (s.t === 'leave') return '가족방 나가기'
  if (s.t === 'text') return s.k === 'nickname' ? `${s.m.name}님 호칭 고치기` : `${TEXTS[s.k].name} 고치기`
  return `${hon} 폰 연결 해제`
}
