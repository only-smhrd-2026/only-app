"""D15: 어르신 말·일기·가족 글·사진 설명을 DEBUG 로그에도 남기지 않는다."""

import logging

import pytest

from tests.conftest import setup_elder
from tests.test_diary import _draft, _post, _talk
from tests.test_family_diary import _post as family_post
from tests.test_mood_signal import _say, _start
from tests.test_photos import _jpeg

SECRET = "파란우산비밀문장"


@pytest.mark.parametrize(
    "flow", ["elder_turn", "elder_diary", "family_diary", "photo", "family_ask", "family_draft", "mood_check"]
)
def test_personal_text_does_not_reach_logs(client, caplog, flow):
    caplog.set_level(logging.DEBUG)
    ctx = setup_elder(client)
    room = ctx["room_id"]
    caplog.clear()
    if flow == "elder_turn":
        sid = _start(client, ctx)
        assert _say(client, sid, SECRET)["state"] == "CONTINUE"
    elif flow == "elder_diary":
        sid, _ = _talk(client, answers=(SECRET, SECRET, SECRET, SECRET, "좋았어요"))
        draft = _draft(client, sid)
        assert draft.status_code == 200 and SECRET in draft.json()["body"]
        result = _post(client, sid)
        assert result.status_code == 201 and SECRET in result.json()["body"]
    elif flow == "family_diary":
        result = family_post(client, room, body=SECRET)
        assert result.status_code == 201 and result.json()["body"] == SECRET
    elif flow == "photo":
        result = client.post(
            f"/api/rooms/{room}/photos",
            files=[("files", ("sample.jpg", _jpeg(), "image/jpeg"))],
            data={"caption": SECRET, "people_note": SECRET},
        )
        assert result.status_code == 201
        assert result.json()["photos"][0]["caption"] == SECRET
        assert result.json()["photos"][0]["people_note"] == SECRET
    elif flow in ("family_ask", "family_draft"):
        endpoint = "ask" if flow == "family_ask" else "draft"
        body = {"text": SECRET} if endpoint == "ask" else {"text": SECRET, "question": SECRET, "answer": SECRET}
        result = client.post(f"/api/rooms/{room}/family-diary/{endpoint}", json=body)
        assert result.status_code == 200
    else:
        answers = [0, 1, 2, 3, 0, 1, 2, 3]
        assert client.post("/api/elder/mood-check", json={"answers": answers}).status_code == 200
        assert str(answers) not in caplog.text
    assert SECRET not in caplog.text
    assert all(
        f"/api/rooms/{room}/" not in record.getMessage() for record in caplog.records if record.name == "app.req"
    )
