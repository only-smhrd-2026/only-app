/**
 * UPLOAD_003 — 추억 올리기 3/3: 등록 확인 (FR-ME-001, 목업 설계자료/목업_1115_가족 ④ '추억 올리기 3/3'). 하위 화면(위 ←).
 * UPLOAD_002 가 uploadResult 에 남긴 가족방별 결과를 보여 준다: 보낸 곳·장 수, 다음에 일어날 일 두 줄.
 * 실패한 곳이 있으면 [실패한 곳 다시 보내기] → UPLOAD_002 가 실패한 곳만 골라 같은 사진·같은 번호로 다시 보낸다(D17).
 * 어르신 폰이 아직 연결 전이고 사진이 3장 이상이면(기기 링크 조건) 가족방 탭으로 가는 연결 안내.
 */
import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import type { RoomOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import { useFetch } from '../../hooks/useFetch'
import { uploadDraft, uploadResult } from '../../lib/uploadDraft'
import { Thumb } from './UPLOAD_001'
import './steps.css'
import './UPLOAD_003.css'

// 어르신 폰 연결 링크를 만들 수 있는 사진 수 — 서버의 기기 링크 조건과 같게 (가족 홈 '시작 3단계'와 같은 셈, D70)
const LINK_MIN_PHOTOS = 3

export default function UPLOAD_003() {
  const nav = useNavigate()
  // 열 때 한 번만 복사 — 다시 보내기·로그아웃으로 uploadResult 가 바뀌어도 이 화면은 그대로
  const [result] = useState(() => ({
    rooms: uploadResult.rooms,
    files: uploadDraft.files,
    same: uploadDraft.batchId === uploadResult.batchId,
  }))
  // 폰 연결·사진 수는 방금 올린 뒤의 값을 새로 읽는다. 못 읽으면 연결 안내만 빠진다
  const rooms = useFetch<RoomOut[]>(result.rooms.length > 0 ? '/api/rooms' : null)
  if (result.rooms.length === 0) return <Navigate to="/upload" replace /> // 새로고침 등으로 결과가 없음

  const ok = result.rooms.filter((r) => r.ok)
  const failed = result.rooms.filter((r) => !r.ok)
  // 실패가 있는데 그 사이 새 사진을 골랐다(묶음 번호가 다름) — 지난 결과라 보여 주지 않는다.
  // 안 막으면 뒤로 가기로 돌아왔을 때 앞 묶음 실패 줄 옆에 새 사진이 보였다(코드 리뷰에서 재현해 사용자와 정해 더함).
  // 전부 성공이면 고른 사진을 비워 번호가 원래 다르고, 사진 수도 서버 응답으로 세어서 섞이지 않는다
  if (failed.length > 0 && !result.same) return <Navigate to="/upload" replace />

  const okNames = ok.map((r) => r.name).join(' · ')
  // 보낸 방 중 폰이 아직 연결 전이고 사진이 모인 방. 연결 링크는 방장만 만들 수 있어(서버 require_owner) 방장에게만 보인다
  const toLink = (rooms.data ?? []).filter(
    (room) =>
      room.is_owner &&
      ok.some((r) => r.room_id === room.room_id) &&
      !room.device_connected &&
      room.photo_count >= LINK_MIN_PHOTOS,
  )

  return (
    <main className="st">
      <div className="st-prog" aria-hidden="true">
        <i style={{ width: '100%' }} />
      </div>
      <div className="st-body">
        {failed.length === 0 ? (
          <div className="up3-result">
            <span className="up3-ic" aria-hidden="true">
              <FamIcon name="check" />
            </span>
            <h1>사진 {ok[0].photos.length}장을 보냈어요</h1>
            <p>{okNames}께</p>
          </div>
        ) : (
          <div className="up3-result">
            <span className="up3-ic up3-ic--warn" aria-hidden="true">
              !
            </span>
            <h1>{ok.length === 0 ? '보내지 못했어요' : `${failed.length}곳은 못 보냈어요`}</h1>
            <p>
              {ok.length > 0 && `${okNames} 완료 · `}
              {failed.map((r) => r.name).join(' · ')} 실패
            </p>
          </div>
        )}

        {failed.length > 0 && (
          <section className="fam-card up3-fails">
            {failed.map((r) => (
              <div key={r.room_id} className="up3-fail">
                {result.files[0] && (
                  <span className="up3-tb">
                    <Thumb file={result.files[0]} alt="" />
                  </span>
                )}
                <span>
                  <b>{r.name}</b>
                  <small>
                    사진 {result.files.length}장 · {r.why}
                  </small>
                </span>
              </div>
            ))}
          </section>
        )}

        {ok.length > 0 && (
          <section className="fam-card up3-info">
            <p>
              <FamIcon name="sparkle" />
              <span>AI가 10분 안에 사진을 살펴봐요</span>
            </p>
            <p>
              <FamIcon name="calendar" />
              <span>내일부터 '오늘의 한 장'으로 {okNames}께 보여 드려요</span>
            </p>
          </section>
        )}

        {toLink.map((room) => (
          <Link key={room.room_id} className="up3-link" to={`/groups/${room.room_id}/members`}>
            <FamIcon name="phone" />
            <span>
              이제 {room.elder_name} {room.elder_honorific} 폰을 연결해요
            </span>
            <FamIcon name="chevRight" />
          </Link>
        ))}
      </div>

      {/* 실패가 남아도 나가는 버튼은 늘 보인다 — 계속 실패하는 가족방(예: 방에서 나가짐)이 있어도 다시 보내기만 누르며 갇히지 않게 */}
      <div className="st-cta">
        {failed.length > 0 ? (
          <>
            <Link className="fam-btn fam-btn--tonal" to="/">
              가족 홈으로
            </Link>
            <button
              type="button"
              className="fam-btn fam-btn--primary st-wide"
              onClick={() => nav('/upload/target', { replace: true })}
            >
              실패한 곳 다시 보내기
            </button>
          </>
        ) : (
          <>
            <Link className="fam-btn fam-btn--tonal" to="/upload">
              사진 더 올리기
            </Link>
            <Link className="fam-btn fam-btn--primary" to="/">
              가족 홈으로
            </Link>
          </>
        )}
      </div>
    </main>
  )
}
