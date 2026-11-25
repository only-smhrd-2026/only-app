/**
 * 어르신 화면의 사진 칸 (D60, 11/23 시안 .photo). 사진을 잘라내지 않고 찍은 모양 그대로 흰 인화지 위에 보여 주고
 * (종이는 사진 크기에 맞춤), 오른쪽 아래 [크게] 표시. 누르면 화면 가득 크게 띄운다 — 아무 데나 누르거나 폰의 뒤로 키로 닫힌다(<dialog>).
 * 칸 크기는 부르는 화면이 className 으로 정한다 — 기본은 남는 자리를 채우는 elder-photo-box--grow.
 */
import { useRef } from 'react'

type Props = { src: string; alt: string; className?: string }

export default function ElderPhoto({ src, alt, className = '' }: Props) {
  const zoom = useRef<HTMLDialogElement>(null)
  return (
    <>
      <button
        type="button"
        className={`elder-photo-box elder-photo-box--grow elder-photo-box--whole ${className}`}
        aria-label={`${alt}. 누르면 크게 보여요`}
        onClick={() => zoom.current?.showModal()}
      >
        <span className="elder-photo-paper">
          {/* 세로 사진이면 칸에 data-shape="port" — 부르는 화면이 세로 사진을 조금 작게 (11/25 실사용) */}
          <img
            src={src}
            alt=""
            onLoad={(e) => {
              const i = e.currentTarget
              i.closest('button')?.setAttribute('data-shape', i.naturalHeight > i.naturalWidth ? 'port' : 'land')
            }}
          />
          <span className="elder-zoomtag" aria-hidden="true">
            <svg className="elder-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="6.5" />
              <path d="M16 16l4.5 4.5M11 8.5v5M8.5 11h5" />
            </svg>
            크게
          </span>
        </span>
      </button>
      <dialog ref={zoom} className="elder-zoom" aria-label={alt} onClick={() => zoom.current?.close()}>
        <img src={src} alt={alt} />
        <p>사진을 누르면 닫혀요</p>
      </dialog>
    </>
  )
}
