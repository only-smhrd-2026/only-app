/**
 * FDIARY_001 — 오늘 한 장 1/3: 사진 고르기 (이슈 #41, 목업 설계자료/목업_1115_가족 ④ '오늘 한 장 1/3'). 아래 탭 '오늘 한 장' 첫 화면.
 * 가족도 일기를 써서 어르신께 보낸다(어르신 홈 '가족 소식'). 오늘 찍은 사진 1장(없으면 사진 없이) → FDIARY_002 한마디·일기 동무
 * → FDIARY_003 초안 확인·게시. 이 화면은 서버에 아무것도 보내지 않고 lib/familyDiaryDraft 에 담기만 한다.
 */
import { useState, type ChangeEvent } from 'react'
import { Link, useNavigate, useNavigationType } from 'react-router-dom'
import FamIcon from '../../components/FamIcon'
import { useFamily } from '../../hooks/useFamily'
import {
  clearFamilyDiaryDraft,
  familyDiaryDraft,
  restoreFamilyDiaryText,
  saveFamilyDiaryText,
} from '../../lib/familyDiaryDraft'
import { fitPhoto, MAX_BYTES } from '../../lib/fitPhoto' // 상한 넘는 사진 줄이기·10MB(서버와 같은 값)
import { Thumb } from './UPLOAD_001' // 미리보기 그림
import './steps.css'
import './FDIARY_001.css'

// 서버가 받는 사진 종류(D17). accept 는 부탁일 뿐이라 '파일' 앱 등에서 HEIC·PDF 가 올 수 있어 고를 때 바로 막는다
const TYPES = ['image/jpeg', 'image/png']

/** 폰 사진 창을 여는 칸. HEIC 는 서버가 받지 않는다(D17) — 이 accept 면 아이폰 Safari 가 보관함 사진을 JPEG 로 바꿔 준다 */
function FileInput({ onPick, disabled }: { onPick: (e: ChangeEvent<HTMLInputElement>) => void; disabled: boolean }) {
  return <input className="fd-file" type="file" accept="image/jpeg,image/png" onChange={onPick} disabled={disabled} />
}

export default function FDIARY_001() {
  const nav = useNavigate()
  const { me, room, rooms } = useFamily()
  // 다음 화면에서 뒤로 가기로 돌아올 때(POP)만 고른 사진을 되살린다. 탭으로 새로 들어오면 빈 상태(UPLOAD_001 과 같음).
  // 같은 창에서 로그아웃 뒤 다른 계정이 뒤로 가기로 와도 앞 사람 사진이 보이지 않게, 쓰기 시작한 사람이 같을 때만
  const resume = useNavigationType() === 'POP' && familyDiaryDraft.userId === me?.user_id
  const [photo, setPhoto] = useState<File | null>(() => (resume ? familyDiaryDraft.photo : null))
  const [error, setError] = useState('')
  const [preparing, setPreparing] = useState(false) // 큰 사진 줄이는 중 — 그동안 고르기·버튼 막기

  async function onPick(e: ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0]
    e.target.value = '' // 같은 사진을 다시 골라도 onChange 가 오게
    if (!picked) return // 고르다 취소 — 앞 사진 그대로
    if (!TYPES.includes(picked.type)) return setError('jpg·png 사진만 고를 수 있어요')
    setError('')
    setPreparing(true)
    let file: File
    try {
      file = await fitPhoto(picked) // 상한 넘는 사진만 줄인다(UPLOAD_001 과 같은 규칙)
    } finally {
      setPreparing(false)
    }
    // 줄여도 큰 사진(긴 변 2560 안인데 10MB 넘는 png 등)
    if (file.size > MAX_BYTES) return setError(`${MAX_BYTES / 1024 / 1024}MB보다 작은 사진을 골라 주세요`)
    setPhoto(file)
  }
  const blocked = !room || preparing // 가족방이 없거나 사진 준비 중이면 아래 버튼 막기

  function next(withPhoto: boolean) {
    if (!room || !me) return
    // 새로 시작했으면(탭으로 들어옴·다른 계정) 앞서 쓰다 만 한마디·질문·초안을 비운다. 뒤로 돌아온 것이면 그대로 두고 사진만 바꾼다
    if (!resume) clearFamilyDiaryDraft()
    restoreFamilyDiaryText(me.user_id) // 페이지를 새로 연 뒤 첫 [다음]만 — 같은 사람이 쓰던 글을 되살린다
    familyDiaryDraft.userId = me.user_id
    familyDiaryDraft.photo = withPhoto ? photo : null
    familyDiaryDraft.room = room
    familyDiaryDraft.rooms = rooms
    saveFamilyDiaryText()
    nav('/fdiary/write')
  }

  return (
    <main className="st">
      <div className="st-prog" aria-hidden="true">
        <i style={{ width: '33.3%' }} />
      </div>
      <div className="st-body">
        <div className="st-head">
          <p className="st-step">1/3 · 사진 고르기</p>
          <h1>오늘 한 장</h1>
          <p className="st-lead">오늘 찍은 사진 1장과 한마디로 소식을 전해요</p>
        </div>

        {photo ? (
          <div className="fd-photo">
            <Thumb file={photo} alt="고른 사진" />
            <label className="fd-again">
              <FileInput onPick={onPick} disabled={preparing} />
              <FamIcon name="imagePlus" />
              다른 사진
            </label>
          </div>
        ) : (
          <label className="fd-picker">
            <FileInput onPick={onPick} disabled={preparing} />
            <span className="fd-ring">
              <FamIcon name="imagePlus" />
            </span>
            <b>오늘 사진 고르기</b>
            <small>1장만 골라요 · 없으면 사진 없이 써도 돼요</small>
          </label>
        )}
        {preparing && (
          <p className="fd-hint" role="status">
            사진을 준비하는 중…
          </p>
        )}
        {error && (
          <p className="fam-error" role="alert">
            {error}
          </p>
        )}
        {!room && (
          <p className="fd-hint">
            먼저 가족방을 만들어 주세요 ·{' '}
            <Link to="/groups/new">가족방 만들기</Link>
          </p>
        )}
      </div>

      <div className="st-cta">
        {photo ? (
          <>
            <button type="button" className="fam-btn fam-btn--tonal" disabled={blocked} onClick={() => next(false)}>
              사진 없이
            </button>
            <button type="button" className="fam-btn fam-btn--primary st-wide" disabled={blocked} onClick={() => next(true)}>
              다음
            </button>
          </>
        ) : (
          <button type="button" className="fam-btn fam-btn--tonal" disabled={blocked} onClick={() => next(false)}>
            사진 없이 쓰기
          </button>
        )}
      </div>
    </main>
  )
}
