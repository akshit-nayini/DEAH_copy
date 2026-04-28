import pytest
from pathlib import Path


@pytest.fixture
def app():
    from app import create_app
    application = create_app({"TESTING": True, "SECRET_KEY": "test", "ADMIN_PASSWORD": "admin"})
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


def test_root_redirects_to_login_when_not_logged_in(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_page_loads(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"login" in response.data.lower()


def test_login_with_correct_credentials(client):
    response = client.post("/login", data={"password": "admin"}, follow_redirects=False)
    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]


def test_login_with_wrong_password(client):
    response = client.post("/login", data={"password": "wrong"}, follow_redirects=False)
    assert response.status_code == 200
    assert b"invalid" in response.data.lower()


def test_dashboard_requires_login(client):
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_dashboard_accessible_when_logged_in(client):
    client.post("/login", data={"password": "admin"})
    response = client.get("/dashboard")
    assert response.status_code == 200


def test_logout_clears_session(client):
    client.post("/login", data={"password": "admin"})
    client.get("/logout")
    response = client.get("/dashboard")
    assert response.status_code == 302
