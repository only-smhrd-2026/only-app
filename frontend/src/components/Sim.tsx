/** 꼬마심심이 그림 (11/23 시안). 꾸밈 그림이라 화면 읽기에는 안 읽힌다 */
import ask from '../assets/sim/sim_ask.webp'
import curious from '../assets/sim/sim_curious.webp'
import hello from '../assets/sim/sim_hello.webp'
import joy from '../assets/sim/sim_joy.webp'
import smile from '../assets/sim/sim_smile.webp'
import thumbs from '../assets/sim/sim_thumbs.webp'

const SRC = { ask, curious, hello, joy, smile, thumbs }
export type SimFace = keyof typeof SRC

export default function Sim({ face, size, className }: { face: SimFace; size: number; className?: string }) {
  return <img className={className} src={SRC[face]} width={size} height={Math.round(size * 0.914)} alt="" aria-hidden="true" draggable={false} />
}
