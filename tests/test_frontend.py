from fastapi.testclient import TestClient

from payops.api import create_app


def test_console_and_assets_are_served(sessions):
    with TestClient(create_app(sessions)) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "text/html" in page.headers["content-type"]
        assert 'id="payment-form"' in page.text
        for asset in ("app.js", "core.mjs", "style.css"):
            response = client.get(f"/assets/{asset}")
            assert response.status_code == 200
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/assets/../api.py").status_code == 404
        assert client.get("/payments").json() == []


def test_console_routes_stay_out_of_api_reference(sessions):
    with TestClient(create_app(sessions)) as client:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/" not in paths
        assert "/payments" in paths
