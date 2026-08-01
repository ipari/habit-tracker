from fastapi.testclient import TestClient

from tests.conftest import csrf_token, login
from tests.test_habits import create_habit


def test_share_page_uses_current_streak_and_saved_preset(client: TestClient) -> None:
    habit_id = create_habit(client)
    token = csrf_token(client)
    today_page = client.get("/today")
    assert f'href="/habits/{habit_id}/share"' not in today_page.text
    detail_page = client.get(f"/habits/{habit_id}")
    assert f'href="/habits/{habit_id}/share?from=habits"' in detail_page.text

    completion_path = today_page.text.split(
        f'action="/habits/{habit_id}/completions/', 1
    )[1].split('"', 1)[0]
    client.post(
        f"/habits/{habit_id}/completions/{completion_path}",
        data={"completed": "true", "csrf_token": token},
    )

    response = client.get(f"/habits/{habit_id}/share")

    assert response.status_code == 200
    assert 'data-habit-name="물 마시기"' in response.text
    assert 'data-habit-emoji="💧"' in response.text
    assert 'data-streak="1"' in response.text
    assert "data-start-label=" in response.text
    assert 'data-preset="ocean"' in response.text
    assert 'width="1080"' in response.text
    assert 'height="1920"' in response.text
    assert "/static/js/share.js" in response.text
    assert "공유하기" in response.text
    assert ">공유</button>" in response.text
    assert ">다운로드</button>" in response.text
    assert "현재 연속 달성 기록을" not in response.text
    assert "공유 이미지는 1080\u00d71920" not in response.text
    assert "owner" not in response.text


def test_share_page_requires_login_and_unknown_habit_is_not_found(
    client: TestClient,
) -> None:
    assert client.get("/habits/1/share").status_code == 401
    login(client)
    assert client.get("/habits/999/share").status_code == 404


def test_share_script_has_file_share_and_download_fallback(client: TestClient) -> None:
    script = client.get("/static/js/share.js")

    assert script.status_code == 200
    assert 'canvas.toBlob' in script.text
    assert 'new File(' in script.text
    assert 'navigator.canShare' in script.text
    assert 'navigator.share' in script.text
    assert 'link.download' in script.text
    assert 'canvas.width' in script.text
    assert 'canvas.height' in script.text
    assert "composer.dataset.startLabel" in script.text
    assert "context.fillText(startLabel" in script.text
    assert 'setStatus("공유 이미지가 준비되었습니다.")' not in script.text
