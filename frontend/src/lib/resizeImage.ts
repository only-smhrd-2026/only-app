async function readImage<T>(file: File, read: (image: HTMLImageElement) => T | Promise<T>): Promise<T> {
  const url = URL.createObjectURL(file)
  try {
    const image = new Image()
    image.src = url
    await image.decode()
    return await read(image)
  } finally {
    URL.revokeObjectURL(url)
  }
}

/** 브라우저가 촬영 방향을 적용한 사진의 전체 픽셀 수. */
export async function pixelsOf(file: File): Promise<number> {
  return readImage(file, (image) => image.naturalWidth * image.naturalHeight)
}

/** 긴 변만 제한하고 비율을 유지한다. 작은 사진은 변환하지 않는다. */
export async function resizeImage(file: File, maxEdge: number): Promise<File> {
  if (!Number.isFinite(maxEdge) || maxEdge < 1) throw new Error('사진의 최대 크기를 확인해 주세요.')

  return readImage(file, async (image) => {
    const edge = Math.max(image.naturalWidth, image.naturalHeight)
    if (edge <= maxEdge) return file

    const scale = Math.floor(maxEdge) / edge
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
    const context = canvas.getContext('2d')
    if (!context) throw new Error('사진을 줄이지 못했어요.')
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((result) => {
        if (result) resolve(result)
        else reject(new Error('사진을 저장하지 못했어요.'))
      }, 'image/jpeg', 0.85)
    })
    const name = file.name.replace(/\.[^.]+$/, '') + '.jpg'
    return new File([blob], name, { type: 'image/jpeg', lastModified: file.lastModified })
  })
}
