/** 꼬마심심이 그림 (11/23 시안 + 11/26 날씨 그림 6장 — 승희 님). 꾸밈 그림이라 화면 읽기에는 안 읽힌다 */
import ask from '../assets/sim/sim_ask.webp'
import curious from '../assets/sim/sim_curious.webp'
import hello from '../assets/sim/sim_hello.webp'
import hot from '../assets/sim/sim_hot.webp'
import joy from '../assets/sim/sim_joy.webp'
import raincoat from '../assets/sim/sim_raincoat.webp'
import smile from '../assets/sim/sim_smile.webp'
import snow from '../assets/sim/sim_snow.webp'
import thumbs from '../assets/sim/sim_thumbs.webp'
import umbrella from '../assets/sim/sim_umbrella.webp'
import wind from '../assets/sim/sim_wind.webp'
import winter from '../assets/sim/sim_winter.webp'

// 날씨 그림 이름 = 서버 GET /api/elder/weather 의 look (api/types WeatherLook)
const SRC = { ask, curious, hello, joy, smile, thumbs, hot, raincoat, snow, umbrella, wind, winter }
export type SimFace = keyof typeof SRC

export default function Sim({ face, size, className }: { face: SimFace; size: number; className?: string }) {
  return <img className={className} src={SRC[face]} width={size} height={Math.round(size * 0.914)} alt="" aria-hidden="true" draggable={false} />
}
