/** GROUP_001 — 가족방 만들기. 디자인 없음 (김승희 교체). */
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'

export default function GROUP_001() {
  const nav = useNavigate()
  const [error, setError] = useState<string>()

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    try {
      await api('/api/rooms', {
        body: {
          elder_name: f.get('elder_name'),
          elder_honorific: f.get('elder_honorific'),
          relation_tag: f.get('relation_tag'),
          nickname: f.get('nickname') || null,
        },
      })
      nav('/', { replace: true })
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  return (
    <main className="page">
      <h1>가족방 만들기</h1>
      <form className="form card" onSubmit={submit}>
        <label>어르신 성함<input name="elder_name" required maxLength={10} /></label>
        <label>호칭<input name="elder_honorific" defaultValue="할머니" maxLength={20} /></label>
        <label>나와의 관계
          <select name="relation_tag" defaultValue="CHILD">
            <option value="CHILD">자녀</option>
            <option value="GRANDCHILD">손주</option>
            <option value="OTHER">기타</option>
          </select>
        </label>
        <label>어르신이 부르는 내 이름 (선택)<input name="nickname" maxLength={12} /></label>
        {error && <p className="error">{error}</p>}
        <button className="btn">만들기</button>
      </form>
    </main>
  )
}
