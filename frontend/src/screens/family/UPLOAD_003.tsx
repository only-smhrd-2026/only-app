/**
 * UPLOAD_003 — 사진 올리기 결과 (FR-ME-001). UPLOAD_002 가 uploadResult 에 남긴 가족방별 결과를 보여 준다.
 * 실패한 곳이 있으면 [실패한 곳 다시 보내기] → UPLOAD_002 가 실패한 곳만 체크해 같은 사진·같은 번호로 다시 보낸다(D17).
 * 'AI 가 사진을 분류하는 중'·'기기 연결 안 됐으면 초대 안내'는 그걸 주는 서버가 아직 없어 넣지 않았다.
 */
import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { uploadDraft, uploadResult } from '../../lib/uploadDraft'
import { PhotoGrid } from './UPLOAD_001'

export default function UPLOAD_003() {
  const nav = useNavigate()
  // 열 때 한 번만 복사 — 다시 보내기·로그아웃으로 uploadResult 가 바뀌어도 이 화면은 그대로
  const [result] = useState(() => ({
    rooms: uploadResult.rooms,
    files: uploadDraft.files,
    same: uploadDraft.batchId === uploadResult.batchId,
  }))
  if (result.rooms.length === 0) return <Navigate to="/upload" replace /> // 새로고침 등으로 결과가 없음

  const ok = result.rooms.filter((r) => r.ok)
  const failed = result.rooms.filter((r) => !r.ok)
  // 실패가 있는데 그 사이 새 사진을 골랐다(묶음 번호가 다름) — 지난 결과라 보여 주지 않는다.
  // 안 막으면 뒤로 가기로 돌아왔을 때 앞 묶음 실패 줄 옆에 새 사진이 보였다(코드 리뷰에서 재현해 사용자와 정해 더함).
  // 전부 성공이면 고른 사진을 비워 번호가 원래 다르고, 사진도 서버 응답으로 그려서 섞이지 않는다
  if (failed.length > 0 && !result.same) return <Navigate to="/upload" replace />

  return (
    <main className="page fam-skin">
      <h1>올린 결과</h1>
      <section className="card">
        {failed.length === 0 ? (
          <>
            <p>사진 {ok[0].photos.length}장을 {ok.map((r) => r.name).join('·')}께 보냈어요</p>
            <ul className="upload-grid">
              {ok[0].photos.map((p, i) => (
                <li key={p.photo_id}><img src={p.url} alt={`올린 사진 ${i + 1}`} /></li>
              ))}
            </ul>
            <p>내일부터 오늘의 한 장 후보가 돼요.</p>
          </>
        ) : (
          <>
            <p>{ok.length}곳 완료 · {failed.length}곳 실패</p>
            {result.rooms.map((r) => (
              <p key={r.room_id} className={r.ok ? undefined : 'error'}>{r.text}</p>
            ))}
            <PhotoGrid files={result.files} />
          </>
        )}
        {/* 실패가 남아도 나가는 버튼은 늘 보인다 — 계속 실패하는 가족방(예: 방에서 나가짐)이 있어도 다시 보내기만 누르며 갇히지 않게 */}
        <div className="row">
          {failed.length > 0 && (
            <button className="btn" onClick={() => nav('/upload/target', { replace: true })}>실패한 곳 다시 보내기</button>
          )}
          <Link className="btn secondary" to="/upload">사진 더 올리기</Link>
          <Link className={failed.length > 0 ? 'btn secondary' : 'btn'} to="/">가족 홈으로</Link>
        </div>
      </section>
    </main>
  )
}
