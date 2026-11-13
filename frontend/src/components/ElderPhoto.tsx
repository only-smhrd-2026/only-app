/**
 * 어르신 화면의 사진 칸 (D60). 사진을 잘라내지 않고 찍은 모양 그대로(가로는 가로로, 세로는 세로로) 보여 주고,
 * 누르면 화면 가득 크게 띄운다. 크게 본 화면은 아무 데나 누르거나 폰의 뒤로 키로 닫힌다(<dialog>).
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
        aria-label={`${alt} 크게 보기`}
        onClick={() => zoom.current?.showModal()}
      >
        <img src={src} alt={alt} />
      </button>
      <dialog ref={zoom} className="elder-zoom" aria-label={alt} onClick={() => zoom.current?.close()}>
        <img src={src} alt={alt} />
        <p>화면을 누르면 닫혀요</p>
      </dialog>
    </>
  )
}
