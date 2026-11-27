/**
 * 동그라미 사진 자르기 판 (11/27) — 내 정보 프로필 사진·가족방 어르신 얼굴 사진이 같이 쓴다.
 * 손가락으로 끌어 옮기고, 아래 막대로 크게·작게. [저장]하면 동그라미 안쪽을 정사각형 JPEG 로 넘긴다
 * (서버가 400px 로 줄이고, 화면은 동그라미로 보여 준다). 라이브러리 없이 canvas 만 쓴다.
 */
import { useMemo, useRef, useState, type PointerEvent } from 'react'
import './PhotoCrop.css'

const BOX = 280 // 자르는 칸 크기(px) — 가장 좁은 폰(320px)에서도 판 안에 들어감
const OUT = 800 // 보낼 그림 크기(px). 서버가 다시 400 으로 줄인다
const MAX_ZOOM = 3

type Pos = { x: number; y: number; zoom: number }

export default function PhotoCrop({
  file,
  title,
  onCancel,
  onDone,
}: {
  file: File
  title: string
  onCancel: () => void
  onDone: (jpeg: Blob) => void
}) {
  // 사진을 읽고 나면 주소는 지운다(loaded) — 읽힌 그림은 img 가 들고 있어 끌기·저장에 그대로 쓴다
  const url = useMemo(() => URL.createObjectURL(file), [file])
  const img = useRef<HTMLImageElement>(null)
  const [size, setSize] = useState<{ w: number; h: number }>()
  const [pos, setPos] = useState<Pos>({ x: 0, y: 0, zoom: 1 })
  const [failed, setFailed] = useState(false)
  const drag = useRef<{ id: number; x: number; y: number }>(null)

  // 짧은 변이 칸을 꽉 채우는 배율 × 확대. 사진이 칸 밖으로 비지 않게 위치를 묶는다
  const scaleOf = (zoom: number) => (size ? (BOX / Math.min(size.w, size.h)) * zoom : 1)
  const clamp = (x: number, y: number, zoom: number): Pos => {
    const s = scaleOf(zoom)
    const w = (size?.w ?? 0) * s
    const h = (size?.h ?? 0) * s
    return { x: Math.min(0, Math.max(BOX - w, x)), y: Math.min(0, Math.max(BOX - h, y)), zoom }
  }

  function loaded() {
    const el = img.current
    if (!el) return
    URL.revokeObjectURL(url)
    setSize({ w: el.naturalWidth, h: el.naturalHeight })
    const s = BOX / Math.min(el.naturalWidth, el.naturalHeight)
    setPos({ x: (BOX - el.naturalWidth * s) / 2, y: (BOX - el.naturalHeight * s) / 2, zoom: 1 }) // 가운데
  }

  function zoomTo(zoom: number) {
    // 칸 가운데를 기준으로 커지고 작아진다
    const k = scaleOf(zoom) / scaleOf(pos.zoom)
    setPos(clamp(BOX / 2 - (BOX / 2 - pos.x) * k, BOX / 2 - (BOX / 2 - pos.y) * k, zoom))
  }

  function down(e: PointerEvent) {
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY }
  }
  function move(e: PointerEvent) {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    setPos((p) => clamp(p.x + e.clientX - d.x, p.y + e.clientY - d.y, p.zoom))
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY }
  }

  function save() {
    const el = img.current
    if (!el || !size) return
    const s = scaleOf(pos.zoom)
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = OUT
    canvas.getContext('2d')?.drawImage(el, -pos.x / s, -pos.y / s, BOX / s, BOX / s, 0, 0, OUT, OUT)
    canvas.toBlob((b) => (b ? onDone(b) : setFailed(true)), 'image/jpeg', 0.9)
  }

  const s = scaleOf(pos.zoom)
  return (
    <>
      <button type="button" className="fam-scrim" aria-label="닫기" onClick={onCancel} />
      <div className="fam-sheet crop" role="dialog" aria-label={title}>
        <span className="fam-grab" />
        <h2>{title}</h2>
        <p className="fam-mini">손가락으로 끌어 얼굴을 동그라미 안에 맞춰 주세요</p>
        <div
          className="crop-box"
          style={{ width: BOX, height: BOX }}
          onPointerDown={down}
          onPointerMove={move}
          onPointerUp={() => (drag.current = null)}
          onPointerCancel={() => (drag.current = null)}
        >
          <img
            ref={img}
            src={url}
            alt=""
            draggable={false}
            onLoad={loaded}
            onError={() => setFailed(true)}
            style={size ? { width: size.w * s, height: size.h * s, transform: `translate(${pos.x}px, ${pos.y}px)` } : { opacity: 0 }}
          />
          <span className="crop-ring" aria-hidden="true" />
        </div>
        <label className="crop-zoom">
          <span>작게</span>
          <input
            type="range"
            min={1}
            max={MAX_ZOOM}
            step={0.01}
            value={pos.zoom}
            onChange={(e) => zoomTo(Number(e.target.value))}
            aria-label="사진 크게 보기"
            disabled={!size}
          />
          <span>크게</span>
        </label>
        {failed && (
          <p className="fam-error" role="alert">
            이 사진은 열 수 없어요. 다른 사진을 골라 주세요.
          </p>
        )}
        <div className="crop-btns">
          <button type="button" className="fam-btn" onClick={onCancel}>
            취소
          </button>
          <button type="button" className="fam-btn fam-btn--primary" onClick={save} disabled={!size || failed}>
            저장
          </button>
        </div>
      </div>
    </>
  )
}
