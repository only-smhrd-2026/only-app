import { pixelsOf, resizeImage } from './resizeImage'

// 서버 config.py 의 UPLOAD_MAX_BYTES·UPLOAD_MAX_PIXELS·PHOTO_MAX_SIDE 와 같게 (추억 올리기 UPLOAD_001·가족 일기 FDIARY_001)
export const MAX_BYTES = 10 * 1024 * 1024
const UPLOAD_MAX_PIXELS = 30_000_000
const PHOTO_MAX_SIDE = 2560

/**
 * 상한(10MB·3000만 화소)을 넘는 사진만 긴 변 2560px 로 줄인다. 줄이면 촬영일(EXIF)이 빠져서 상한 안 사진은 원본 그대로.
 * 브라우저가 못 여는 사진(HEIC 등)은 원본 그대로 — 서버가 거절하고 결과 화면에 실패로 나온다.
 * 화면 파일이 아닌 여기 두는 까닭: 화면 파일이 함수를 내보내면 저장할 때마다 페이지가 새로 열려 고른 사진이 사라진다
 */
export async function fitPhoto(f: File): Promise<File> {
  try {
    if (f.size <= MAX_BYTES && (await pixelsOf(f)) <= UPLOAD_MAX_PIXELS) return f
    return await resizeImage(f, PHOTO_MAX_SIDE)
  } catch {
    return f
  }
}
