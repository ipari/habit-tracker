import json

from fastapi.testclient import TestClient

from tests.conftest import login


def test_pages_link_installable_manifest_and_local_htmx(client: TestClient) -> None:
    response = client.get("/login")

    assert response.status_code == 200
    assert (
        'name="viewport" content="width=device-width, initial-scale=1, minimum-scale=1, '
        'maximum-scale=1, user-scalable=no, viewport-fit=cover"'
    ) in response.text
    assert 'rel="manifest" href="http://testserver/static/manifest.webmanifest"' in response.text
    assert 'src="http://testserver/static/vendor/htmx-2.0.10.min.js"' in response.text
    assert 'src="http://testserver/static/js/theme.js?v=1"' in response.text
    assert 'href="http://testserver/static/css/app.css?v=39"' in response.text
    assert 'href="http://testserver/static/icons/favicon.svg?v=3"' in response.text
    assert 'href="http://testserver/static/icons/app-icon-180.png?v=5"' in response.text

    stylesheet = client.get("/static/css/app.css")
    assert "scrollbar-gutter: stable both-edges" in stylesheet.text
    assert "scrollbar-color: var(--scrollbar-thumb" in stylesheet.text
    assert "left: 50%" in stylesheet.text
    assert "width: min(calc(100% - 3.5rem), 35rem)" in stylesheet.text
    assert "width: 2.3rem" in stylesheet.text
    assert 'src="http://testserver/static/js/app.js?v=7"' in response.text
    assert "cdn.jsdelivr.net" not in response.text
    assert 'id="offline-status"' in response.text
    assert 'id="app-alert-dialog"' in response.text
    assert 'role="alertdialog"' in response.text
    assert 'aria-modal="true"' in response.text

    script = client.get("/static/js/app.js")
    assert "window.appAlert" in script.text
    assert "window.appConfirm" in script.text
    assert "showModal()" in script.text
    assert "window.confirm(" not in script.text

    assert ".app-alert-dialog::backdrop" in stylesheet.text
    assert "background: rgb(0 0 0 / 55%)" in stylesheet.text
    assert ".app-alert-actions button:focus-visible" in stylesheet.text


def test_manifest_defines_standalone_app(client: TestClient) -> None:
    response = client.get("/static/manifest.webmanifest")

    assert response.status_code == 200
    manifest = json.loads(response.text)
    assert manifest["start_url"] == "/today"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["icons"][0]["sizes"] == "192x192"
    assert manifest["icons"][1]["sizes"] == "512x512"
    assert any(icon["purpose"] == "maskable" for icon in manifest["icons"])
    assert all("?v=5" in icon["src"] for icon in manifest["icons"])

    dock_icon = client.get("/static/icons/app-icon-512.png")
    assert dock_icon.status_code == 200
    assert dock_icon.content[25] == 6  # PNG color type 6 is RGBA.

    favicon = client.get("/static/icons/favicon.svg")
    assert favicon.status_code == 200
    assert 'r="190"' in favicon.text
    assert 'fill="#34c759"' in favicon.text


def test_service_worker_controls_app_scope_without_caching_html(client: TestClient) -> None:
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["service-worker-allowed"] == "/"
    assert 'url.pathname.startsWith("/static/")' in response.text
    cache_and_fetch_source = response.text.split('self.addEventListener("push"')[0]
    assert '"/today"' not in cache_and_fetch_source


def test_installed_app_offers_notification_permission_after_user_action(
    client: TestClient,
) -> None:
    assert 'id="notification-permission-prompt"' not in client.get("/login").text

    login(client)
    page = client.get("/today")
    script = client.get("/static/js/app.js")

    assert 'id="notification-permission-prompt"' in page.text
    assert "습관 알림을 받아보세요" in page.text
    assert "알림 허용" in page.text
    assert "appinstalled" in script.text
    assert "(display-mode: standalone)" in script.text
    assert "Notification.requestPermission()" in script.text
    assert "PushManager" in script.text
    worker = client.get("/sw.js")
    assert 'self.addEventListener("push"' in worker.text
    assert "showNotification" in worker.text
    assert 'self.addEventListener("notificationclick"' in worker.text
    assert '"/static/js/share.js?v=2"' in worker.text
    assert '"/static/js/theme.js?v=1"' in worker.text
    assert '"/static/css/app.css?v=39"' in worker.text
    assert '"/static/js/app.js?v=7"' in worker.text
    assert '"/static/icons/favicon.svg?v=3"' in worker.text
    assert '"/static/icons/app-icon-512.png?v=5"' in worker.text
    assert '"/static/icons/app-icon-maskable-512.png?v=5"' in worker.text

    settings = client.get("/settings")
    assert 'data-notification-open' in settings.text
    assert 'data-notification-disconnect' in settings.text
    assert 'id="notification-permission-status"' in settings.text
    assert 'method: "DELETE"' in script.text
    assert "subscription.unsubscribe()" in script.text
