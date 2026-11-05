-- =====================================================================
-- 개발·시연용 시드 데이터 (실명·실사진 없음). backend 폴더에서 `uv run python -m scripts.seed` 가
-- schema.sql 다음에 이 파일을 실행하고, 이어서 사진 파일 3장·문제 은행(data/question_bank.json)·오늘의 한 장 1행을 넣습니다.
--
-- ★ 테스트 계정 (README 「10분 안에 실행」과 같은 값. 공개 저장소이므로 실제 비밀번호를 쓰지 않습니다)
--   가족 1 (방장): test@haru.local  / test1234   이름 김하루 (딸)
--   가족 2       : test2@haru.local / test1234   이름 박손주 (손주)
--   가족방       : 순자 할머니 (room_id 1)
-- ★ 어르신 기기 연결 링크 (한 번 쓰면 소모됨. 다시 쓰려면 시드를 다시 실행)
--   http://localhost:5173/elder/connect#seed-elder-link-token-only-for-dev-0001
--   (아래 invites.token_hash 는 이 토큰의 SHA-256. 만료 2030-12-31)
-- =====================================================================

INSERT INTO users (login_type, email, password_hash, name, terms_agreed_at) VALUES
  ('TEST', 'test@haru.local',  '$2b$10$3xaD/l6RRvPM2j33ks1a/e.P7WxMgKHthqx3fG77P6cUngyqfRHPq', '김하루', now()),
  ('TEST', 'test2@haru.local', '$2b$10$3xaD/l6RRvPM2j33ks1a/e.P7WxMgKHthqx3fG77P6cUngyqfRHPq', '박손주', now());

INSERT INTO family_rooms (elder_name, elder_honorific, owner_user_id)
VALUES ('순자', '할머니', (SELECT user_id FROM users WHERE email = 'test@haru.local'));

INSERT INTO room_members (room_id, user_id, relation_tag, nickname) VALUES
  (1, (SELECT user_id FROM users WHERE email = 'test@haru.local'),  'CHILD',      '큰딸'),
  (1, (SELECT user_id FROM users WHERE email = 'test2@haru.local'), 'GRANDCHILD', '막내 손주');

INSERT INTO invites (room_id, kind, token_hash, expires_at, created_by) VALUES
  (1, 'ELDER_DEVICE', 'b062bd93c413a38ca994f7106b429c2e15ba8dbd4c96b4b33b83b77ba6454a90',
   '2030-12-31 23:59:59+09', (SELECT user_id FROM users WHERE email = 'test@haru.local'));

-- 샘플 사진 3장 (파일은 seed.py 가 uploads/ 에 만들어 넣음). key = rooms/{room_id}/{upload_batch_id}/{index}.jpg
INSERT INTO photos (room_id, uploaded_by, upload_batch_id, object_key, taken_at, source, caption, people_note) VALUES
  (1, (SELECT user_id FROM users WHERE email = 'test@haru.local'), '11111111-1111-4111-8111-111111111111',
   'rooms/1/11111111-1111-4111-8111-111111111111/0.jpg', '2019-02-05', 'FAMILY', '설날 온 가족이 모인 날', '할머니, 큰딸, 손주 둘'),
  (1, (SELECT user_id FROM users WHERE email = 'test@haru.local'), '11111111-1111-4111-8111-111111111111',
   'rooms/1/11111111-1111-4111-8111-111111111111/1.jpg', '2021-11-20', 'FAMILY', '김장하던 날 마당', '할머니, 큰딸'),
  (1, (SELECT user_id FROM users WHERE email = 'test@haru.local'), '11111111-1111-4111-8111-111111111111',
   'rooms/1/11111111-1111-4111-8111-111111111111/2.jpg', '2023-05-05', 'FAMILY', '손주 생일 잔치', '할머니, 손주');

INSERT INTO group_vocab (room_id, term, kind, source) VALUES
  (1, '순자', 'NAME', 'MEMBER'),
  (1, '하루', 'NAME', 'MEMBER'),
  (1, '할머니', 'HONORIFIC', 'MEMBER');
