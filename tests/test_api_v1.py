"""Tests for FastAPI core endpoints and security headers."""


def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "ok"
    assert "device" in data


def test_caption_styles(client):
    res = client.get("/api/caption-styles")
    assert res.status_code == 200
    styles = res.json()
    assert isinstance(styles, list)
    assert len(styles) > 0
    names = [s.get("id") for s in styles]
    assert "hormozi_green" in names
    assert "beast_red" in names


def test_devices_endpoint(client):
    res = client.get("/api/devices")
    assert res.status_code == 200
    data = res.json()
    assert "devices" in data
    assert "default" in data
    assert "cuda_available" in data


def test_cors_security_headers(client):
    # Origin from localhost should be allowed
    res = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"

    # Origin from untrusted domain should NOT be reflected
    res_bad = client.options(
        "/health",
        headers={
            "Origin": "http://malicious-site.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_bad.headers.get("access-control-allow-origin") != "http://malicious-site.com"
