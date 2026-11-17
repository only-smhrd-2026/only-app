/**
 * POLICY_001 — 이용약관·개인정보 처리방침 (/policy). 로그인 전에도 열려야 해서 틀(FamilyFrame) 밖 화면이다(App.tsx).
 * 시작 화면(LOGIN_001)의 [보기]·추억 올리기 1/3 의 '자세히 ›'(#vendors, D71)에서 온다.
 * 글은 Drive 「동의 문구·개인정보 처리방침 (초안)」 11/17 판 그대로. **아직 초안** — 홍진성이 확정하면 글만 바꾼다.
 * [팀 확인] 다섯 곳(확정 때 고칠 곳): ① 책임자·연락처·시행일(맨 아래 — 책임자는 실명 대신 '팀 ONLy (팀장)', CLAUDE.md 1-5)
 * ② 모두 지우는 날 2026-12-31 ③ 백업 7일 ④ 맡기는 곳의 Anthropic·Google·리턴제로 두는 기간 ⑤ 마음 알림 안내 위치(이 화면 밖)
 */
import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import FamIcon from '../../components/FamIcon'
import '../../components/FamilyFrame.css'
import './POLICY_001.css'

/** 표 대신 줄마다 작은 카드 — 폰 폭(390px)에서 3~4칸 표는 너무 좁다 */
type Row = { head: string; lines: [string, string][] }

const COLLECT: Row[] = [
  {
    head: '가족',
    lines: [
      ['모으는 것', '이메일, 이름, 비밀번호(암호로 바꿔 저장), 어르신과의 관계, 호칭'],
      ['쓰는 곳', '로그인, 가족방 구성원 표시, 어르신이 부르는 이름'],
    ],
  },
  {
    head: '가족방',
    lines: [
      ['모으는 것', '어르신 이름, 부르는 말, 글자 크기·목소리 같은 설정'],
      ['쓰는 곳', '어르신 화면과 AI 대화'],
    ],
  },
  {
    head: '가족이 올린 것',
    lines: [
      ['모으는 것', '사진, 사진 설명, 사진 속 사람, 가족 일기, 하트·리액션'],
      ['쓰는 곳', '오늘의 한 장, 사진첩, 가족 소식'],
    ],
  },
  {
    head: '어르신',
    lines: [
      ['모으는 것', '대화를 받아 적은 글, 기운 없는 말·위급한 말 표시, 일기, 그림일기 그림, 어르신이 찍은 사진'],
      ['쓰는 곳', '회상 대화, 일기, 주간 이야기, 마음 알림'],
    ],
  },
  {
    head: '어르신 (동의한 경우만)',
    lines: [
      ['모으는 것', '마음 체크 8문항 답 (건강 정보)'],
      ['쓰는 곳', "가족 홈의 '요즘 어떠신지' 한 줄"],
    ],
  },
  {
    head: '기기',
    lines: [
      ['모으는 것', '어르신 폰 연결 표시, 마이크·알림 허용 여부, 마지막으로 연 때'],
      ['쓰는 곳', '어르신 폰 로그인, 가족방 탭의 연결 상태'],
    ],
  },
  {
    head: '모두',
    lines: [
      ['모으는 것', '서버 접속 기록(IP 주소, 접속 시각)'],
      ['쓰는 곳', '오류 확인, 부정 이용 막기'],
    ],
  },
]

const KEEP: [string, string][] = [
  ['가족 계정', '탈퇴할 때까지'],
  ['가족방과 어르신 대화 글', '가족방이 있는 동안'],
  ['사진, 일기', '지울 때까지'],
  ['마음 체크 답', '가족방이 있는 동안'],
  ['AI가 기억하는 이야기', '정해 둔 만료일까지'],
  ['초대 링크', '가족 링크 7일, 어르신 링크 24시간'],
  ['서버 접속 기록', '3개월 (통신비밀보호법)'],
]

const VENDORS: Row[] = [
  {
    head: 'AWS (한국, 서울)',
    lines: [
      ['맡기는 일', '서버와 데이터베이스'],
      ['보내는 정보', '위의 모든 정보'],
      ['두는 기간', '우리 보관 기간과 같아요'],
    ],
  },
  {
    head: 'Cloudflare R2',
    lines: [
      ['맡기는 일', '사진 저장'],
      ['보내는 정보', '사진, 그림일기 그림'],
      ['두는 기간', '우리 보관 기간과 같아요'],
    ],
  },
  {
    head: 'Anthropic (미국)',
    lines: [
      ['맡기는 일', '대화·일기·주간 이야기 글 만들기, 사진 살펴보기'],
      ['보내는 정보', '어르신 대화 글, 일기 글, 가족이 쓴 한마디, 사진, 사진 설명·사진 속 사람 호칭'],
      ['두는 기간', '30일 안에 지움, 학습에 쓰지 않음 (이용정책 위반으로 표시된 대화는 최대 2년)'],
    ],
  },
  {
    head: 'Google (미국)',
    lines: [
      ['맡기는 일', '글을 목소리로 읽기'],
      ['보내는 정보', '어르신께 읽어 드릴 글'],
      ['두는 기간', '글과 음성을 기록하지 않음'],
    ],
  },
  {
    head: '리턴제로 (한국)',
    lines: [
      ['맡기는 일', '목소리를 글로 받아 적기'],
      ['보내는 정보', '어르신 목소리'],
      ['두는 기간', '받아 적은 결과·실행 기록 3일 보관 후 삭제 (음성 원본 보관·학습 여부는 약관에 없음)'],
    ],
  },
  {
    head: 'Cloudflare Workers AI',
    lines: [
      ['맡기는 일', '그림일기 그림 그리기'],
      ['보내는 정보', '그림에 넣을 사물 이름 3개까지 (사람 정보 없음)'],
      ['두는 기간', '보관하지 않음 (Cloudflare 안내)'],
    ],
  },
]

function Cards({ rows }: { rows: Row[] }) {
  return (
    <ul className="pol-cards">
      {rows.map((r) => (
        <li key={r.head}>
          <b>{r.head}</b>
          <dl>
            {r.lines.map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        </li>
      ))}
    </ul>
  )
}

export default function POLICY_001() {
  const nav = useNavigate()
  const { hash } = useLocation()
  // react-router 가 history.state.idx 에 앱 안 순번을 적는다 — 0 이면 주소로 바로 열었다 → 시작 화면으로 (SubFrame 과 같은 방법)
  const back = () => ((window.history.state?.idx ?? 0) > 0 ? nav(-1) : nav('/login', { replace: true }))
  // '자세히 ›'(#vendors)로 왔으면 그 칸으로, 아니면 맨 위로 — react-router 는 창 스크롤을 스스로 옮기지 않아
  // 시작 화면(창 스크롤)에서 내려가 있던 위치 그대로 열린다(리뷰 6번, 크롬에서 재현)
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView()
    else window.scrollTo(0, 0)
  }, [hash])

  return (
    <main className="fam pol">
      <header className="fam-bar fam-bar--sub pol-bar">
        <button type="button" className="fam-icon-btn" onClick={back} aria-label="돌아가기">
          <FamIcon name="arrowLeft" />
        </button>
      </header>

      <div className="pol-body">
        <h1>약관·개인정보 처리방침</h1>

        <section>
          <h2>하루한장은</h2>
          <p>
            하루한장은 가족 사진과 AI 회상 대화로 어르신의 하루를 함께하고, 가족과 소식을 나누는 앱이에요.
            스마트인재개발원 학원 프로젝트로 만들었고, 시험 기간(11/23~12/4)과 발표에 쓰여요. 의료 서비스가 아니며,
            마음 체크와 마음 알림은 진단이 아니에요. 위급할 때는 119에 연락해 주세요.
          </p>
        </section>

        <section>
          <h2>모으는 정보와 쓰는 곳</h2>
          <Cards rows={COLLECT} />
          <p>
            어르신 목소리 녹음은 글로 받아 적은 뒤 저장하지 않아요. 서버 기록(로그)에는 어르신·가족이 한 말, 사진
            설명을 남기지 않아요.
          </p>
        </section>

        <section>
          <h2>얼마나 두는지</h2>
          <dl className="pol-keep">
            {KEEP.map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
          <p>
            지우거나, 가족방을 나가거나, 탈퇴하면 화면에서는 바로 사라져요. 서버의 매일 백업에는 최대 7일 남았다가
            지워져요. 프로젝트가 끝나는 2026년 12월 31일에는 모든 자료를 지워요.
          </p>
        </section>

        <section id="vendors">
          <h2>맡기는 곳</h2>
          <p>
            앱을 운영하려고 아래 회사에 일을 맡겨요. 미국 회사로 가는 정보는 앱을 쓰는 동안, 필요한 때마다
            인터넷(암호화 연결)으로 보내요.
          </p>
          <Cards rows={VENDORS} />
          <p>
            가족이 올린 사진과 어르신이 일기에 찍은 사진이 미국으로 가요. 보내고 싶지 않으면 사진을 올리지 않으면
            돼요. 이때 오늘의 한 장과 사진 대화는 쓸 수 없고, 사진 없는 일기와 대화는 쓸 수 있어요.
          </p>
        </section>

        <section>
          <h2>지우는 방법</h2>
          <ul className="pol-list">
            <li>
              사진: 가족방 탭, 올린 사진, 사진을 누르고 [이 사진 지우기]. 내가 올린 사진만 지울 수 있고, 방장은 그 방
              사진을 모두 지울 수 있어요.
            </li>
            <li>일기: 내가 쓴 일기에서 지우기.</li>
            <li>
              가족방 나가기: 가족방 탭 맨 아래 [이 가족방 나가기]. 나가면 그 가족방의 일기와 사진을 볼 수 없어요. 내가
              쓴 일기는 남아요.
            </li>
          </ul>
          <p>그 밖의 정보를 보거나, 고치거나, 지우고 싶으면 아래 문의처로 알려 주세요.</p>
          <p>지운 사진은 사진 파일까지 바로 지워져요. 다만 매일 백업에는 최대 7일 남았다가 지워져요.</p>
        </section>

        <section>
          <h2>정보를 지키는 방법</h2>
          <ul className="pol-list">
            <li>비밀번호는 원래 글자로 저장하지 않고 암호로 바꿔 저장해요.</li>
            <li>앱과 서버 사이는 암호화 연결(HTTPS)로만 주고받아요.</li>
            <li>다른 가족방의 사진과 일기는 그 방 구성원만 볼 수 있어요.</li>
            <li>사진의 위치 정보(GPS)는 저장할 때 빼요.</li>
          </ul>
        </section>

        <section>
          <h2>문의</h2>
          <p>개인정보 보호 책임자: 팀 ONLy (팀장)</p>
          <p>연락처: haruhanjang@example.com (프로젝트용 임시 주소)</p>
        </section>

        <section>
          <h2>시행일</h2>
          <p>이 방침은 2026년 11월 23일부터 적용해요.</p>
        </section>
      </div>
    </main>
  )
}
