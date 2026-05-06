import pytest
from app import app, db, User
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta

@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SECRET_KEY"] = "test-secret"

    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client
        with app.app_context():
            db.drop_all()


# ─────────────────────────────────────────────
# SIGNUP TESTS
# ─────────────────────────────────────────────

def test_signup_success(client):
    res = client.post("/auth/signup", json={
        "email": "test@example.com",
        "password": "password123",
        "name": "Test User"
    })
    assert res.status_code == 201
    data = res.get_json()
    assert data["user"]["email"] == "test@example.com"


def test_signup_missing_fields(client):
    res = client.post("/auth/signup", json={
        "email": "",
        "password": "",
        "name": ""
    })
    assert res.status_code == 400


def test_signup_duplicate_email(client):
    client.post("/auth/signup", json={
        "email": "dup@example.com",
        "password": "password123",
        "name": "User1"
    })

    res = client.post("/auth/signup", json={
        "email": "dup@example.com",
        "password": "password123",
        "name": "User2"
    })

    assert res.status_code == 409


# ─────────────────────────────────────────────
# LOGIN TESTS
# ─────────────────────────────────────────────

def test_login_success(client):
    client.post("/auth/signup", json={
        "email": "login@example.com",
        "password": "password123",
        "name": "Login User"
    })

    res = client.post("/auth/login", json={
        "email": "login@example.com",
        "password": "password123"
    })

    assert res.status_code == 200
    assert res.get_json()["message"] == "Login successful"


def test_login_wrong_password(client):
    client.post("/auth/signup", json={
        "email": "wrong@example.com",
        "password": "password123",
        "name": "Wrong User"
    })

    res = client.post("/auth/login", json={
        "email": "wrong@example.com",
        "password": "wrongpass"
    })

    assert res.status_code == 401


def test_login_nonexistent_user(client):
    res = client.post("/auth/login", json={
        "email": "nope@example.com",
        "password": "password123"
    })

    assert res.status_code == 401


# ─────────────────────────────────────────────
# SESSION TESTS
# ─────────────────────────────────────────────

def test_me_requires_login(client):
    res = client.get("/auth/me")
    assert res.status_code == 401


def test_me_after_login(client):
    client.post("/auth/signup", json={
        "email": "me@example.com",
        "password": "password123",
        "name": "Me User"
    })

    client.post("/auth/login", json={
        "email": "me@example.com",
        "password": "password123"
    })

    res = client.get("/auth/me")
    assert res.status_code == 200
    assert res.get_json()["email"] == "me@example.com"


def test_logout(client):
    client.post("/auth/signup", json={
        "email": "logout@example.com",
        "password": "password123",
        "name": "Logout User"
    })

    client.post("/auth/login", json={
        "email": "logout@example.com",
        "password": "password123"
    })

    res = client.post("/auth/logout")
    assert res.status_code == 200

    res2 = client.get("/auth/me")
    assert res2.status_code == 401


# ─────────────────────────────────────────────
# LOCKOUT TEST
# ─────────────────────────────────────────────

def test_account_lockout(client):
    client.post("/auth/signup", json={
        "email": "lock@example.com",
        "password": "password123",
        "name": "Lock User"
    })

    # Fail login 5 times
    for _ in range(5):
        client.post("/auth/login", json={
            "email": "lock@example.com",
            "password": "wrongpass"
        })

    # Now account should be locked
    res = client.post("/auth/login", json={
        "email": "lock@example.com",
        "password": "password123"
    })

    assert res.status_code == 423