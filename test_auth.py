"""
test_auth.py — InfoCord Full Test Suite
========================================
Phases covered:
  Phase 4 — True E2EE: server receives/stores ciphertext+iv+salt, never plaintext
  Phase 5 — Version-based sync (conflict detection, resolution flow)
  Phase 6 — Stability & error handling
               • global error handlers (404, 405)
               • UUID validation on every route
               • hex color validation
               • archived-state guards (notes + categories)
               • health-check endpoint
               • request-id header present on all responses
               • update_category body + field validation

Architecture note:
  The server is a zero-knowledge storage layer. It never decrypts notes.
  Tests simulate what a browser client would do: encrypt before sending,
  and would decrypt after receiving (but we just verify the ciphertext
  round-trips correctly — actual decryption is the browser's job).

Environment:
  Self-contained — sets all required env vars before any import.
  Default: SQLite in-memory locally; CI sets TEST_DATABASE_URI for Postgres.
  Run with:  pytest test_auth.py -v
"""

import base64
import os
import secrets
import pytest

# ── Env vars MUST be set before importing run.py ─────────────────────────────
TEST_KEY = base64.b64encode(secrets.token_bytes(32)).decode()
os.environ.setdefault("NOTE_ENCRYPTION_KEY", TEST_KEY)
os.environ.setdefault("TEST_DATABASE_URI",   "sqlite:///:memory:")
os.environ.setdefault("FLASK_SECRET_KEY",    "test-only-secret")

from run import app, db, normalize_db_url                       # noqa: E402
from crypto_utils import encrypt_note, decrypt_note, generate_iv  # noqa: E402


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

def _test_db_uri() -> str:
    raw = (
        os.environ.get("TEST_DATABASE_URI")
        or os.environ.get("DATABASE_URL")
        or "sqlite:///:memory:"
    )
    if raw.startswith(("postgresql://", "postgres://")):
        return normalize_db_url(raw)
    return raw


@pytest.fixture
def client():
    """Fresh DB for every test (SQLite in-memory locally, Postgres in CI)."""
    app.config["TESTING"]                 = True
    app.config["SQLALCHEMY_DATABASE_URI"] = _test_db_uri()
    app.config["WTF_CSRF_ENABLED"]        = False
    app.config["SECRET_KEY"]              = "test-only-secret"

    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client
        with app.app_context():
            db.drop_all()


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def signup_and_login(client, email="crud@example.com",
                     password="password123", name="CRUD User"):
    client.post("/auth/signup", json={"email": email, "password": password, "name": name})
    return client.post("/auth/login", json={"email": email, "password": password})


def make_category(client, name="Notes", color="000000"):
    res = client.post("/categories", json={"name": name, "color": color})
    return res.get_json()["id"]


def fake_encrypted_payload(plaintext="test note content"):
    """
    Simulate what the browser does: encrypt with server-side crypto_utils
    and return the payload a client would POST.
    Normally this would be Web Crypto API in the browser; here we use
    the server's crypto_utils purely to generate realistic test data.
    """
    ct, iv = encrypt_note(plaintext)
    # Generate a fake per-note PBKDF2 salt (browser would derive this)
    salt = base64.b64encode(secrets.token_bytes(16)).decode()
    return {"ciphertext": ct, "iv": iv, "salt": salt}


def make_note(client, category_id, plaintext="test note", title="Test Note"):
    payload = fake_encrypted_payload(plaintext)
    res = client.post("/notes", json={
        "category_id": category_id,
        "title":       title,
        **payload
    })
    return res.get_json()


def update_note_payload(plaintext="updated content", title="Updated"):
    payload = fake_encrypted_payload(plaintext)
    return {"title": title, **payload}


# ─────────────────────────────────────────────
# CRYPTO UNIT TESTS  (crypto_utils.py)
# ─────────────────────────────────────────────

class TestCryptoUtils:
    """
    Unit tests for crypto_utils.py.
    These test the SERVER-SIDE crypto helper used by tests to generate
    realistic ciphertext. The actual E2EE crypto runs in the browser
    via Web Crypto API.
    """

    def test_generate_iv_is_12_bytes(self):
        assert len(base64.b64decode(generate_iv())) == 12

    def test_generate_iv_is_unique(self):
        ivs = {generate_iv() for _ in range(100)}
        assert len(ivs) == 100

    def test_encrypt_returns_two_strings(self):
        ct, iv = encrypt_note("hello")
        assert isinstance(ct, str) and isinstance(iv, str)

    def test_encrypt_output_is_base64(self):
        ct, iv = encrypt_note("hello")
        base64.b64decode(ct)
        base64.b64decode(iv)

    def test_ciphertext_differs_from_plaintext(self):
        ct, _ = encrypt_note("super secret")
        assert ct != "super secret"

    def test_same_plaintext_produces_different_ciphertext(self):
        ct1, iv1 = encrypt_note("identical")
        ct2, iv2 = encrypt_note("identical")
        assert ct1 != ct2 and iv1 != iv2

    def test_round_trip(self):
        pt = "InfoCord 🔒 unicode ñoño"
        ct, iv = encrypt_note(pt)
        assert decrypt_note(ct, iv) == pt

    def test_round_trip_empty_string(self):
        ct, iv = encrypt_note("")
        assert decrypt_note(ct, iv) == ""

    def test_round_trip_long_content(self):
        pt = "a" * 9999
        ct, iv = encrypt_note(pt)
        assert decrypt_note(ct, iv) == pt

    def test_tampered_ciphertext_raises(self):
        ct, iv = encrypt_note("sensitive")
        garbage = base64.b64encode(b"not valid ciphertext padding here!!").decode()
        with pytest.raises(ValueError, match="decryption failed"):
            decrypt_note(garbage, iv)

    def test_wrong_iv_raises(self):
        ct, _ = encrypt_note("note a")
        _, iv2 = encrypt_note("note b")
        with pytest.raises(ValueError):
            decrypt_note(ct, iv2)

    def test_missing_ciphertext_raises(self):
        with pytest.raises(ValueError):
            decrypt_note("", "someiv")

    def test_missing_iv_raises(self):
        with pytest.raises(ValueError):
            decrypt_note("somect", "")

    def test_invalid_base64_raises(self):
        with pytest.raises(ValueError):
            decrypt_note("!!!bad!!!", generate_iv())

    def test_encrypt_wrong_type_raises(self):
        with pytest.raises(TypeError):
            encrypt_note(12345)  # type: ignore

    def test_missing_key_raises(self):
        original = os.environ.pop("NOTE_ENCRYPTION_KEY")
        try:
            with pytest.raises(EnvironmentError, match="NOTE_ENCRYPTION_KEY"):
                encrypt_note("test")
        finally:
            os.environ["NOTE_ENCRYPTION_KEY"] = original

    def test_wrong_length_key_raises(self):
        original = os.environ["NOTE_ENCRYPTION_KEY"]
        os.environ["NOTE_ENCRYPTION_KEY"] = base64.b64encode(secrets.token_bytes(16)).decode()
        try:
            with pytest.raises(EnvironmentError, match="32 bytes"):
                encrypt_note("test")
        finally:
            os.environ["NOTE_ENCRYPTION_KEY"] = original


# ─────────────────────────────────────────────
# HEALTH CHECK  (Phase 6)
# ─────────────────────────────────────────────

class TestHealth:
    def test_health_ok(self, client):
        res = client.get("/health")
        assert res.status_code == 200
        body = res.get_json()
        assert body["status"] == "ok"
        assert body["db"] == "ok"

    def test_health_returns_json(self, client):
        res = client.get("/health")
        assert res.content_type == "application/json"

    def test_health_includes_gate_a_schema_fields(self, client):
        res = client.get("/health")
        body = res.get_json()
        assert body["migration_expected"] == "e8f4a1b2c3d5"
        assert "schema_tables_present" in body
        assert "schema_tables_missing" in body
        assert "migration_ok" in body
        assert "schema_ok" in body
        # SQLite test DB uses create_all — all model tables, no alembic_version row
        assert body["schema_ok"] is True

    def test_health_migration_ok_when_alembic_at_head(self, client):
        with client.application.app_context():
            db.session.execute(db.text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL)"
            ))
            db.session.execute(db.text("DELETE FROM alembic_version"))
            db.session.execute(db.text(
                "INSERT INTO alembic_version (version_num) VALUES ('e8f4a1b2c3d5')"
            ))
            db.session.commit()
        res = client.get("/health")
        body = res.get_json()
        assert body["migration_ok"] is True
        assert body["migration_revision"] == "e8f4a1b2c3d5"


# ─────────────────────────────────────────────
# REQUEST ID HEADER  (Phase 6)
# ─────────────────────────────────────────────

class TestRequestId:
    def test_request_id_present_on_success(self, client):
        assert "X-Request-ID" in client.get("/").headers

    def test_request_id_present_on_404(self, client):
        assert "X-Request-ID" in client.get("/nonexistent-route").headers

    def test_request_id_is_unique_per_request(self, client):
        r1 = client.get("/")
        r2 = client.get("/")
        assert r1.headers["X-Request-ID"] != r2.headers["X-Request-ID"]


# ─────────────────────────────────────────────
# GLOBAL ERROR HANDLERS  (Phase 6)
# ─────────────────────────────────────────────

class TestErrorHandlers:
    def test_404_returns_json(self, client):
        res = client.get("/this/does/not/exist")
        assert res.status_code == 404
        assert res.content_type == "application/json"
        assert "error" in res.get_json()

    def test_405_returns_json(self, client):
        res = client.get("/auth/signup")   # GET on POST-only endpoint
        assert res.status_code == 405
        assert res.content_type == "application/json"
        assert "error" in res.get_json()

    def test_home_returns_json(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert res.content_type == "application/json"


# ─────────────────────────────────────────────
# UUID VALIDATION  (Phase 6)
# ─────────────────────────────────────────────

class TestUUIDValidation:
    def test_bad_category_uuid_on_update(self, client):
        signup_and_login(client)
        res = client.put("/categories/not-a-uuid", json={"name": "x"})
        assert res.status_code == 400
        assert "Invalid" in res.get_json()["error"]

    def test_bad_category_uuid_on_archive(self, client):
        signup_and_login(client)
        assert client.patch("/categories/bad-uuid/archive").status_code == 400

    def test_bad_note_uuid_on_update(self, client):
        signup_and_login(client)
        payload = update_note_payload()
        payload["version"] = 1
        assert client.put("/notes/not-a-uuid", json=payload).status_code == 400

    def test_bad_note_uuid_on_archive(self, client):
        signup_and_login(client)
        assert client.patch("/notes/bad-uuid/archive").status_code == 400

    def test_bad_category_id_in_note_create(self, client):
        signup_and_login(client)
        payload = fake_encrypted_payload()
        res = client.post("/notes", json={"category_id": "not-a-uuid", **payload})
        assert res.status_code == 400


# ─────────────────────────────────────────────
# HEX COLOR VALIDATION  (Phase 6)
# ─────────────────────────────────────────────

class TestHexColor:
    def test_valid_hex_color_accepted(self, client):
        signup_and_login(client)
        assert client.post("/categories", json={"name": "A", "color": "FF0000"}).status_code == 201

    def test_lowercase_hex_accepted(self, client):
        signup_and_login(client)
        assert client.post("/categories", json={"name": "B", "color": "ff0000"}).status_code == 201

    def test_short_hex_rejected(self, client):
        signup_and_login(client)
        res = client.post("/categories", json={"name": "C", "color": "FFF"})
        assert res.status_code == 400
        assert "hex" in res.get_json()["error"].lower()

    def test_invalid_hex_chars_rejected(self, client):
        signup_and_login(client)
        assert client.post("/categories", json={"name": "D", "color": "ZZZZZZ"}).status_code == 400

    def test_empty_color_rejected(self, client):
        signup_and_login(client)
        assert client.post("/categories", json={"name": "E", "color": ""}).status_code == 400

    def test_update_with_invalid_hex_rejected(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        assert client.put(f"/categories/{cat_id}", json={"color": "GGG"}).status_code == 400


# ─────────────────────────────────────────────
# ARCHIVED STATE GUARDS  (Phase 6)
# ─────────────────────────────────────────────

class TestArchivedGuards:
    def test_cannot_add_note_to_archived_category(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        client.patch(f"/categories/{cat_id}/archive")
        payload = fake_encrypted_payload()
        res = client.post("/notes", json={"category_id": cat_id, **payload})
        assert res.status_code == 409
        assert "archived" in res.get_json()["error"].lower()

    def test_cannot_update_archived_note(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        client.patch(f"/notes/{note_id}/archive")
        payload = update_note_payload()
        payload["version"] = 1
        res = client.put(f"/notes/{note_id}", json=payload)
        assert res.status_code == 409
        assert "archived" in res.get_json()["error"].lower()

    def test_cannot_archive_category_twice(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        client.patch(f"/categories/{cat_id}/archive")
        res = client.patch(f"/categories/{cat_id}/archive")
        assert res.status_code == 409
        assert "already archived" in res.get_json()["error"].lower()

    def test_cannot_archive_note_twice(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        client.patch(f"/notes/{note_id}/archive")
        res = client.patch(f"/notes/{note_id}/archive")
        assert res.status_code == 409
        assert "already archived" in res.get_json()["error"].lower()


# ─────────────────────────────────────────────
# UPDATE CATEGORY VALIDATION  (Phase 6)
# ─────────────────────────────────────────────

class TestUpdateCategoryValidation:
    def test_update_requires_json_body(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.put(f"/categories/{cat_id}", data="not json",
                         content_type="text/plain")
        assert res.status_code == 400

    def test_update_empty_name_rejected(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        assert client.put(f"/categories/{cat_id}", json={"name": "   "}).status_code == 400

    def test_update_name_too_long_rejected(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        assert client.put(f"/categories/{cat_id}", json={"name": "x" * 121}).status_code == 400

    def test_update_valid_name_succeeds(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        assert client.put(f"/categories/{cat_id}", json={"name": "Updated"}).status_code == 200

    def test_update_valid_color_succeeds(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        assert client.put(f"/categories/{cat_id}", json={"color": "AABBCC"}).status_code == 200


# ─────────────────────────────────────────────
# NOTE PAYLOAD VALIDATION  (Phase 6)
# ─────────────────────────────────────────────

class TestNotePayloadValidation:
    def test_missing_ciphertext_rejected(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.post("/notes", json={
            "category_id": cat_id, "iv": "abc", "salt": "abc"
        })
        assert res.status_code == 400
        assert "ciphertext" in res.get_json()["error"].lower()

    def test_missing_iv_rejected(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.post("/notes", json={
            "category_id": cat_id, "ciphertext": "abc", "salt": "abc"
        })
        assert res.status_code == 400

    def test_missing_salt_rejected(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.post("/notes", json={
            "category_id": cat_id, "ciphertext": "abc", "iv": "abc"
        })
        assert res.status_code == 400

    def test_create_note_requires_json(self, client):
        signup_and_login(client)
        res = client.post("/notes", data="not json", content_type="text/plain")
        assert res.status_code == 400

    def test_update_note_requires_json(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        res = client.put(f"/notes/{note_id}", data="not json", content_type="text/plain")
        assert res.status_code == 400

    def test_update_missing_ciphertext_rejected(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        res = client.put(f"/notes/{note_id}", json={"iv": "abc", "salt": "abc", "version": 1})
        assert res.status_code == 400


# ─────────────────────────────────────────────
# SIGNUP TESTS
# ─────────────────────────────────────────────

class TestSignup:
    def test_signup_success(self, client):
        res = client.post("/auth/signup", json={
            "email": "test@example.com", "password": "password123", "name": "Test"
        })
        assert res.status_code == 201
        assert res.get_json()["user"]["email"] == "test@example.com"

    def test_signup_missing_fields(self, client):
        res = client.post("/auth/signup", json={"email": "", "password": "", "name": ""})
        assert res.status_code == 400

    def test_signup_invalid_email(self, client):
        res = client.post("/auth/signup", json={
            "email": "not-an-email", "password": "password123", "name": "User"
        })
        assert res.status_code == 400

    def test_signup_short_password(self, client):
        res = client.post("/auth/signup", json={
            "email": "a@b.com", "password": "abc", "name": "User"
        })
        assert res.status_code == 400

    def test_signup_duplicate_email(self, client):
        payload = {"email": "dup@example.com", "password": "password123", "name": "User"}
        client.post("/auth/signup", json=payload)
        assert client.post("/auth/signup", json=payload).status_code == 409

    def test_signup_name_too_long(self, client):
        res = client.post("/auth/signup", json={
            "email": "long@example.com", "password": "password123", "name": "x" * 101
        })
        assert res.status_code == 400

    def test_signup_requires_json(self, client):
        res = client.post("/auth/signup", data="not json", content_type="text/plain")
        assert res.status_code == 400


# ─────────────────────────────────────────────
# LOGIN TESTS
# ─────────────────────────────────────────────

class TestLogin:
    def test_login_success(self, client):
        signup_and_login(client, "login@example.com")
        res = client.post("/auth/login", json={
            "email": "login@example.com", "password": "password123"
        })
        assert res.status_code == 200
        assert res.get_json()["message"] == "Login successful"

    def test_login_wrong_password(self, client):
        signup_and_login(client, "wrong@example.com")
        assert client.post("/auth/login", json={
            "email": "wrong@example.com", "password": "badpass"
        }).status_code == 401

    def test_login_nonexistent_user(self, client):
        assert client.post("/auth/login", json={
            "email": "ghost@example.com", "password": "password123"
        }).status_code == 401

    def test_login_missing_fields(self, client):
        assert client.post("/auth/login", json={"email": "", "password": ""}).status_code == 400

    def test_login_requires_json(self, client):
        assert client.post("/auth/login", data="not json",
                           content_type="text/plain").status_code == 400


# ─────────────────────────────────────────────
# SESSION TESTS
# ─────────────────────────────────────────────

class TestSession:
    def test_me_requires_login(self, client):
        assert client.get("/auth/me").status_code == 401

    def test_me_after_login(self, client):
        signup_and_login(client, "me@example.com")
        res = client.get("/auth/me")
        assert res.status_code == 200
        assert res.get_json()["email"] == "me@example.com"

    def test_logout_clears_session(self, client):
        signup_and_login(client)
        client.post("/auth/logout")
        assert client.get("/auth/me").status_code == 401

    def test_logout_requires_login(self, client):
        assert client.post("/auth/logout").status_code == 401


# ─────────────────────────────────────────────
# LOCKOUT TESTS
# ─────────────────────────────────────────────

class TestLockout:
    def test_account_lockout_after_5_failures(self, client):
        signup_and_login(client, "lock@example.com")
        client.post("/auth/logout")
        for _ in range(5):
            client.post("/auth/login", json={
                "email": "lock@example.com", "password": "wrongpass"
            })
        assert client.post("/auth/login", json={
            "email": "lock@example.com", "password": "password123"
        }).status_code == 423

    def test_failed_attempts_reset_on_success(self, client):
        signup_and_login(client, "reset@example.com")
        client.post("/auth/logout")
        for _ in range(4):
            client.post("/auth/login", json={
                "email": "reset@example.com", "password": "wrongpass"
            })
        assert client.post("/auth/login", json={
            "email": "reset@example.com", "password": "password123"
        }).status_code == 200


# ─────────────────────────────────────────────
# CATEGORY TESTS
# ─────────────────────────────────────────────

class TestCategories:
    def test_create_category(self, client):
        signup_and_login(client)
        res = client.post("/categories", json={"name": "School", "color": "FF0000"})
        assert res.status_code == 201
        data = res.get_json()
        assert data["name"] == "School"
        assert data["color"] == "FF0000"

    def test_create_category_requires_login(self, client):
        assert client.post("/categories",
                           json={"name": "x", "color": "000000"}).status_code == 401

    def test_create_category_missing_fields(self, client):
        signup_and_login(client)
        assert client.post("/categories", json={"name": "NoColor"}).status_code == 400

    def test_get_categories(self, client):
        signup_and_login(client)
        client.post("/categories", json={"name": "A", "color": "000000"})
        client.post("/categories", json={"name": "B", "color": "111111"})
        res = client.get("/categories")
        assert res.status_code == 200
        assert len(res.get_json()) == 2

    def test_categories_isolated_per_user(self, client):
        signup_and_login(client, "user1@example.com")
        client.post("/categories", json={"name": "Private", "color": "AAAAAA"})
        client.post("/auth/logout")
        signup_and_login(client, "user2@example.com")
        assert client.get("/categories").get_json() == []

    def test_update_category(self, client):
        signup_and_login(client)
        cat_id = make_category(client, "Old", "000000")
        assert client.put(f"/categories/{cat_id}", json={"name": "New"}).status_code == 200

    def test_archive_category(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        assert client.patch(f"/categories/{cat_id}/archive").status_code == 200

    def test_cannot_archive_another_users_category(self, client):
        signup_and_login(client, "owner@example.com")
        cat_id = make_category(client)
        client.post("/auth/logout")
        signup_and_login(client, "attacker@example.com")
        assert client.patch(f"/categories/{cat_id}/archive").status_code == 404


# ─────────────────────────────────────────────
# NOTE TESTS  (Phase 4 — true E2EE)
# ─────────────────────────────────────────────

class TestNotes:
    def test_create_note_success(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        payload = fake_encrypted_payload("hello world")
        res = client.post("/notes", json={"category_id": cat_id, **payload})
        assert res.status_code == 201

    def test_create_note_returns_id_and_version(self, client):
        """Server returns id + version only — never echoes plaintext."""
        signup_and_login(client)
        cat_id = make_category(client)
        note   = make_note(client, cat_id, "secret content")
        assert "id"      in note
        assert "version" in note
        assert note["version"] == 1

    def test_create_note_requires_login(self, client):
        payload = fake_encrypted_payload()
        assert client.post("/notes", json={"category_id": "x", **payload}).status_code == 401

    def test_create_note_without_category(self, client):
        signup_and_login(client)
        res = client.post("/notes", json=fake_encrypted_payload())
        assert res.status_code == 201
        note_id = res.get_json()["id"]
        note = client.get(f"/notes/{note_id}").get_json()
        assert note["category_id"] is None

    def test_update_note_category_optional(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        enc = fake_encrypted_payload("folder note")
        note_id = client.post("/notes", json={"category_id": cat_id, **enc}).get_json()["id"]
        enc2 = fake_encrypted_payload("no folder note")
        res = client.put(f"/notes/{note_id}", json={
            "category_id": None,
            **enc2,
            "version": 1,
        })
        assert res.status_code == 200
        assert client.get(f"/notes/{note_id}").get_json()["category_id"] is None

    def test_get_notes_returns_ciphertext_not_plaintext(self, client):
        """
        Core E2EE assertion: the server must return ciphertext, not plaintext.
        The browser is responsible for decryption — the server never decrypts.
        """
        signup_and_login(client)
        cat_id    = make_category(client)
        enc       = fake_encrypted_payload("my secret note")
        client.post("/notes", json={"category_id": cat_id, **enc})

        notes = client.get("/notes").get_json()
        assert len(notes) == 1

        returned_content = notes[0].get("ciphertext") or notes[0].get("content")
        # The returned value must NOT be the original plaintext
        assert returned_content != "my secret note"
        # It must be the ciphertext we sent
        assert returned_content == enc["ciphertext"]

    def test_get_notes_returns_iv_and_salt(self, client):
        """Client needs iv + salt to decrypt — server must return both."""
        signup_and_login(client)
        cat_id = make_category(client)
        enc    = fake_encrypted_payload("secret")
        client.post("/notes", json={"category_id": cat_id, **enc})

        notes = client.get("/notes").get_json()
        note  = notes[0]
        assert note["iv"]   == enc["iv"]
        assert note["salt"] == enc["salt"]

    def test_get_notes_returns_version(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        make_note(client, cat_id)
        notes = client.get("/notes").get_json()
        assert notes[0]["version"] == 1

    def test_multiple_notes_stored(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        make_note(client, cat_id, "note one",   "One")
        make_note(client, cat_id, "note two",   "Two")
        make_note(client, cat_id, "note three", "Three")
        assert len(client.get("/notes").get_json()) == 3

    def test_notes_isolated_per_user(self, client):
        signup_and_login(client, "user1@example.com")
        cat_id = make_category(client)
        make_note(client, cat_id)
        client.post("/auth/logout")
        signup_and_login(client, "user2@example.com")
        assert client.get("/notes").get_json() == []

    def test_update_note_success(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        payload = update_note_payload("updated secret")
        payload["version"] = 1
        res = client.put(f"/notes/{note_id}", json=payload)
        assert res.status_code == 200
        assert res.get_json()["version"] == 2

    def test_update_note_stores_new_ciphertext(self, client):
        """After update, GET must return the NEW ciphertext, not the old one."""
        signup_and_login(client)
        cat_id  = make_category(client)
        enc1    = fake_encrypted_payload("original")
        note_id = client.post("/notes", json={"category_id": cat_id, **enc1}).get_json()["id"]

        enc2 = fake_encrypted_payload("updated")
        client.put(f"/notes/{note_id}", json={"version": 1, **enc2})

        notes = client.get("/notes").get_json()
        returned = notes[0].get("ciphertext") or notes[0].get("content")
        assert returned == enc2["ciphertext"]
        assert returned != enc1["ciphertext"]

    def test_cannot_update_another_users_note(self, client):
        signup_and_login(client, "owner@example.com")
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        client.post("/auth/logout")
        signup_and_login(client, "attacker@example.com")
        payload = update_note_payload()
        payload["version"] = 1
        assert client.put(f"/notes/{note_id}", json=payload).status_code == 404

    def test_archive_note(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        assert client.patch(f"/notes/{note_id}/archive").status_code == 200

    def test_unarchive_note(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        client.patch(f"/notes/{note_id}/archive")
        res = client.patch(f"/notes/{note_id}/unarchive")
        assert res.status_code == 200
        assert client.get(f"/notes/{note_id}").get_json()["archived"] is False

    def test_cannot_unarchive_active_note(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        assert client.patch(f"/notes/{note_id}/unarchive").status_code == 409

    def test_create_note_with_links(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        note_a = make_note(client, cat_id, "alpha", "Note A")["id"]
        note_b = make_note(client, cat_id, "beta", "Note B")["id"]
        enc = fake_encrypted_payload("linked note")
        res = client.post("/notes", json={
            "title": "Hub",
            "linked_note_ids": [note_a, note_b],
            **enc,
        })
        assert res.status_code == 201
        hub_id = res.get_json()["id"]
        hub = client.get(f"/notes/{hub_id}").get_json()
        assert set(hub["linked_note_ids"]) == {note_a, note_b}

    def test_cannot_link_note_to_itself(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        enc = fake_encrypted_payload("self link")
        res = client.put(f"/notes/{note_id}", json={
            "linked_note_ids": [note_id],
            "version": 1,
            **enc,
        })
        assert res.status_code == 400

    def test_cannot_archive_another_users_note(self, client):
        signup_and_login(client, "owner@example.com")
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        client.post("/auth/logout")
        signup_and_login(client, "attacker@example.com")
        assert client.patch(f"/notes/{note_id}/archive").status_code == 404

    def test_nonexistent_category_rejected(self, client):
        signup_and_login(client)
        payload = fake_encrypted_payload()
        res = client.post("/notes", json={
            "category_id": "00000000-0000-0000-0000-000000000000",
            **payload
        })
        assert res.status_code == 404


# ─────────────────────────────────────────────
# PHASE 5 — VERSION SYNC TESTS
# ─────────────────────────────────────────────

class TestVersionSync:
    def test_create_note_returns_version_1(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        note   = make_note(client, cat_id)
        assert note["version"] == 1

    def test_successful_update_increments_version(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        payload = update_note_payload()
        payload["version"] = 1
        res = client.put(f"/notes/{note_id}", json=payload)
        assert res.get_json()["version"] == 2

    def test_version_increments_sequentially(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]

        p2 = update_note_payload("v2"); p2["version"] = 1
        r2 = client.put(f"/notes/{note_id}", json=p2)
        assert r2.get_json()["version"] == 2

        p3 = update_note_payload("v3"); p3["version"] = 2
        r3 = client.put(f"/notes/{note_id}", json=p3)
        assert r3.get_json()["version"] == 3

    def test_stale_version_rejected_409(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]

        p = update_note_payload("first"); p["version"] = 1
        client.put(f"/notes/{note_id}", json=p)

        p2 = update_note_payload("stale"); p2["version"] = 1
        assert client.put(f"/notes/{note_id}", json=p2).status_code == 409

    def test_conflict_response_includes_server_version(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]

        p = update_note_payload("bumped"); p["version"] = 1
        client.put(f"/notes/{note_id}", json=p)

        p2 = update_note_payload("conflict"); p2["version"] = 1
        res  = client.put(f"/notes/{note_id}", json=p2)
        body = res.get_json()
        assert res.status_code == 409
        assert body["server_version"] == 2
        assert "conflict" in body["error"].lower()

    def test_stale_write_does_not_overwrite_ciphertext(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        enc1    = fake_encrypted_payload("original")
        note_id = client.post("/notes", json={"category_id": cat_id, **enc1}).get_json()["id"]

        enc_win = fake_encrypted_payload("winner")
        pw = {"version": 1, **enc_win}
        client.put(f"/notes/{note_id}", json=pw)

        enc_stale = fake_encrypted_payload("loser")
        ps = {"version": 1, **enc_stale}
        client.put(f"/notes/{note_id}", json=ps)  # rejected

        notes = client.get("/notes").get_json()
        returned = notes[0].get("ciphertext") or notes[0].get("content")
        assert returned == enc_win["ciphertext"]

    def test_update_missing_version_rejected(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        payload = update_note_payload()  # no version key
        assert client.put(f"/notes/{note_id}", json=payload).status_code == 400

    def test_update_non_integer_version_rejected(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        payload = update_note_payload()
        payload["version"] = "one"
        assert client.put(f"/notes/{note_id}", json=payload).status_code == 400

    def test_future_version_rejected(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        payload = update_note_payload()
        payload["version"] = 99
        assert client.put(f"/notes/{note_id}", json=payload).status_code == 409

    def test_conflict_resolution_full_flow(self, client):
        """
        Full round-trip:
          Client A wins at version 1 → server at version 2
          Client B is stale (version 1) → 409
          Client B fetches latest → gets version 2
          Client B retries with version 2 → succeeds → version 3
        """
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id, "initial")["id"]

        pA = update_note_payload("A write"); pA["version"] = 1
        client.put(f"/notes/{note_id}", json=pA)

        pB = update_note_payload("B stale"); pB["version"] = 1
        assert client.put(f"/notes/{note_id}", json=pB).status_code == 409

        current_version = client.get("/notes").get_json()[0]["version"]
        assert current_version == 2

        pB2 = update_note_payload("B resolved"); pB2["version"] = current_version
        retry = client.put(f"/notes/{note_id}", json=pB2)
        assert retry.status_code == 200
        assert retry.get_json()["version"] == 3

# ─────────────────────────────────────────────
# RECOVERY KEY TESTS (Step 5)
# ─────────────────────────────────────────────

class TestAccountRecovery:
    def test_signup_returns_24_char_recovery_key(self, client):
        res = client.post("/auth/signup", json={
            "email": "recover@example.com", "password": "password123", "name": "Recover Me"
        })
        assert res.status_code == 201
        body = res.get_json()
        assert "recovery_key" in body
        assert len(body["recovery_key"]) == 24

    def test_recovery_success(self, client):
        # Register and extract recovery key
        res = client.post("/auth/signup", json={
            "email": "rec_flow@example.com", "password": "oldpassword123", "name": "Flow"
        })
        recovery_key = res.get_json()["recovery_key"]

        # Request reset
        rec_res = client.post("/auth/recover", json={
            "email": "rec_flow@example.com",
            "recovery_key": recovery_key,
            "new_password": "newpassword123"
        })
        assert rec_res.status_code == 200

        # Attempt login using new password
        login_res = client.post("/auth/login", json={
            "email": "rec_flow@example.com", "password": "newpassword123"
        })
        assert login_res.status_code == 200

    def test_recovery_fails_with_invalid_key(self, client):
        client.post("/auth/signup", json={
            "email": "bad_key@example.com", "password": "password123", "name": "User"
        })
        res = client.post("/auth/recover", json={
            "email": "bad_key@example.com",
            "recovery_key": "WRONG-KEY-12345678901234",
            "new_password": "newpassword123"
        })
        assert res.status_code == 401


# ─────────────────────────────────────────────
# PASSWORD CHANGE TESTS (Step 6)
# ─────────────────────────────────────────────

class TestPasswordChangeFlow:
    def test_change_password_and_reencrypt_notes(self, client):
        signup_and_login(client, "change_flow@example.com", "oldpassword123")
        cat_id = make_category(client)
        
        # Create an initial note
        note = make_note(client, cat_id, "Initial Secure Data")
        note_id = note["id"]

        # Prepare payload imitating client-side master password alteration
        new_encrypted = fake_encrypted_payload("Data updated with Key B")
        payload = {
            "old_password": "oldpassword123",
            "new_password": "newpassword123",
            "notes": [
                {
                    "id": note_id,
                    "version": 1,
                    "ciphertext": new_encrypted["ciphertext"],
                    "iv": new_encrypted["iv"],
                    "salt": new_encrypted["salt"]
                }
            ]
        }

        res = client.post("/auth/change-password", json=payload)
        assert res.status_code == 200

        # Confirm old password no longer works
        client.post("/auth/logout")
        assert client.post("/auth/login", json={
            "email": "change_flow@example.com", "password": "oldpassword123"
        }).status_code == 401

        # Confirm new password logs in and can access updated ciphertext
        client.post("/auth/login", json={
            "email": "change_flow@example.com", "password": "newpassword123"
        })
        
        fetched_note = client.get(f"/notes/{note_id}").get_json()
        assert fetched_note["ciphertext"] == new_encrypted["ciphertext"]
        assert fetched_note["version"] == 2

# ─────────────────────────────────────────────
# GET /notes/<id> ENDPOINT TESTS
# ─────────────────────────────────────────────

class TestGetSingleNote:
    """
    Tests for GET /notes/<note_id> — the single-note fetch endpoint used by
    the Flutter client during conflict resolution (fetch latest after 409).
    """

    def test_get_single_note_success(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id, "secret", "My Note")["id"]

        res = client.get(f"/notes/{note_id}")
        assert res.status_code == 200
        body = res.get_json()
        assert body["id"] == note_id

    def test_get_single_note_returns_all_fields(self, client):
        """Client needs id, ciphertext, iv, salt, version, title, category_id."""
        signup_and_login(client)
        cat_id = make_category(client)
        enc    = fake_encrypted_payload("content")
        note_id = client.post("/notes", json={
            "category_id": cat_id, "title": "Test Title", **enc
        }).get_json()["id"]

        note = client.get(f"/notes/{note_id}").get_json()
        for field in ["id", "title", "ciphertext", "iv", "salt", "version",
                      "category_id", "archived", "linked_note_ids",
                      "created_at", "updated_at"]:
            assert field in note, f"Missing field: {field}"

    def test_get_single_note_returns_correct_ciphertext(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        enc    = fake_encrypted_payload("secret content")
        note_id = client.post("/notes", json={"category_id": cat_id, **enc}).get_json()["id"]

        note = client.get(f"/notes/{note_id}").get_json()
        assert note["ciphertext"] == enc["ciphertext"]
        assert note["iv"]         == enc["iv"]
        assert note["salt"]       == enc["salt"]

    def test_get_single_note_requires_login(self, client):
        # Create a note, then sign out before fetching
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        client.post("/auth/logout")
        assert client.get(f"/notes/{note_id}").status_code == 401

    def test_get_single_note_wrong_user_returns_404(self, client):
        """Other users must not be able to read someone else's note ID."""
        signup_and_login(client, "owner@example.com")
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        client.post("/auth/logout")

        signup_and_login(client, "spy@example.com")
        assert client.get(f"/notes/{note_id}").status_code == 404

    def test_get_single_note_bad_uuid_returns_400(self, client):
        signup_and_login(client)
        assert client.get("/notes/not-a-uuid").status_code == 400

    def test_get_single_note_nonexistent_returns_404(self, client):
        signup_and_login(client)
        assert client.get("/notes/00000000-0000-0000-0000-000000000000").status_code == 404

    def test_get_single_note_reflects_update(self, client):
        """After a PUT, GET /notes/<id> must return the new ciphertext."""
        signup_and_login(client)
        cat_id  = make_category(client)
        enc1    = fake_encrypted_payload("original")
        note_id = client.post("/notes", json={"category_id": cat_id, **enc1}).get_json()["id"]

        enc2 = fake_encrypted_payload("updated")
        client.put(f"/notes/{note_id}", json={"version": 1, **enc2})

        note = client.get(f"/notes/{note_id}").get_json()
        assert note["ciphertext"] == enc2["ciphertext"]
        assert note["version"]    == 2


# ─────────────────────────────────────────────
# EXTENDED RECOVERY KEY TESTS (Step 5)
# ─────────────────────────────────────────────

class TestAccountRecoveryExtended:
    """
    Covers every edge case of the recovery flow not in TestAccountRecovery.
    """

    def test_recovery_requires_json(self, client):
        res = client.post("/auth/recover", data="not json",
                          content_type="text/plain")
        assert res.status_code == 400

    def test_recovery_missing_email(self, client):
        res = client.post("/auth/recover", json={
            "recovery_key": "SOMEKEY123456789012345",
            "new_password": "newpassword123"
        })
        assert res.status_code == 400

    def test_recovery_missing_recovery_key(self, client):
        res = client.post("/auth/recover", json={
            "email": "user@example.com",
            "new_password": "newpassword123"
        })
        assert res.status_code == 400

    def test_recovery_missing_new_password(self, client):
        res = client.post("/auth/recover", json={
            "email": "user@example.com",
            "recovery_key": "SOMEKEY123456789012345"
        })
        assert res.status_code == 400

    def test_recovery_new_password_too_short(self, client):
        client.post("/auth/signup", json={
            "email": "short@example.com", "password": "password123", "name": "User"
        })
        res = client.post("/auth/recover", json={
            "email": "short@example.com",
            "recovery_key": "SOMEKEY123456789012345",
            "new_password": "abc"
        })
        assert res.status_code == 400
        assert "8" in res.get_json()["error"]

    def test_recovery_nonexistent_email_returns_401(self, client):
        """Must not reveal whether the email exists."""
        res = client.post("/auth/recover", json={
            "email": "nobody@example.com",
            "recovery_key": "SOMEKEY123456789012345",
            "new_password": "newpassword123"
        })
        assert res.status_code == 401

    def test_recovery_key_is_one_time_use(self, client):
        """After a successful recovery, the same key must not work again."""
        res = client.post("/auth/signup", json={
            "email": "once@example.com", "password": "password123", "name": "Once"
        })
        recovery_key = res.get_json()["recovery_key"]

        # First recovery succeeds
        r1 = client.post("/auth/recover", json={
            "email": "once@example.com",
            "recovery_key": recovery_key,
            "new_password": "firstnewpass"
        })
        assert r1.status_code == 200

        # Second attempt with same key must fail
        r2 = client.post("/auth/recover", json={
            "email": "once@example.com",
            "recovery_key": recovery_key,
            "new_password": "secondnewpass"
        })
        assert r2.status_code == 401

    def test_recovery_old_password_no_longer_works(self, client):
        """After recovery reset, the original password must be rejected."""
        res = client.post("/auth/signup", json={
            "email": "oldpass@example.com", "password": "originalpass", "name": "Test"
        })
        recovery_key = res.get_json()["recovery_key"]

        client.post("/auth/recover", json={
            "email": "oldpass@example.com",
            "recovery_key": recovery_key,
            "new_password": "brandnewpass"
        })

        assert client.post("/auth/login", json={
            "email": "oldpass@example.com", "password": "originalpass"
        }).status_code == 401

    def test_recovery_lockout_after_5_bad_keys(self, client):
        """Brute-forcing recovery keys must trigger account lockout."""
        client.post("/auth/signup", json={
            "email": "brute@example.com", "password": "password123", "name": "Brute"
        })

        for _ in range(5):
            client.post("/auth/recover", json={
                "email": "brute@example.com",
                "recovery_key": "WRONGKEY000000000000000",
                "new_password": "newpassword123"
            })

        # Account is now locked — even correct password should be rejected
        res = client.post("/auth/login", json={
            "email": "brute@example.com", "password": "password123"
        })
        assert res.status_code == 423

    def test_signup_recovery_key_is_exactly_24_chars(self, client):
        res = client.post("/auth/signup", json={
            "email": "len@example.com", "password": "password123", "name": "Len"
        })
        key = res.get_json()["recovery_key"]
        assert len(key) == 24, f"Expected 24, got {len(key)}: {key!r}"

    def test_recovery_key_not_exposed_on_login(self, client):
        """The recovery key must never appear in a login response."""
        signup_and_login(client, "nokey@example.com")
        res = client.post("/auth/login", json={
            "email": "nokey@example.com", "password": "password123"
        })
        assert "recovery_key" not in res.get_json()

    def test_recovery_regenerate_key_requires_login(self, client):
        res = client.post("/auth/recovery-key")
        assert res.status_code == 401

    def test_recovery_regenerate_key_invalidates_old(self, client):
        """After regenerating, the old recovery key must no longer work."""
        res = client.post("/auth/signup", json={
            "email": "regen@example.com", "password": "password123", "name": "Regen"
        })
        old_key = res.get_json()["recovery_key"]

        # Login and regenerate
        client.post("/auth/login", json={
            "email": "regen@example.com", "password": "password123"
        })
        regen_res = client.post("/auth/recovery-key")
        assert regen_res.status_code == 200
        new_key = regen_res.get_json()["recovery_key"]
        assert new_key != old_key

        # Old key must no longer work
        client.post("/auth/logout")
        r = client.post("/auth/recover", json={
            "email": "regen@example.com",
            "recovery_key": old_key,
            "new_password": "newpassword123"
        })
        assert r.status_code == 401

    def test_recovery_regenerate_new_key_works(self, client):
        """After regenerating, the new key must work for recovery."""
        client.post("/auth/signup", json={
            "email": "newkey@example.com", "password": "password123", "name": "New"
        })
        client.post("/auth/login", json={
            "email": "newkey@example.com", "password": "password123"
        })
        new_key = client.post("/auth/recovery-key").get_json()["recovery_key"]
        client.post("/auth/logout")

        r = client.post("/auth/recover", json={
            "email": "newkey@example.com",
            "recovery_key": new_key,
            "new_password": "freshpassword123"
        })
        assert r.status_code == 200


# ─────────────────────────────────────────────
# EXTENDED PASSWORD CHANGE TESTS (Step 6)
# ─────────────────────────────────────────────

class TestPasswordChangeExtended:
    """
    Covers every edge case of /auth/change-password not in TestPasswordChangeFlow.
    """

    def test_change_password_requires_login(self, client):
        res = client.post("/auth/change-password", json={
            "old_password": "password123",
            "new_password": "newpassword123",
            "notes": []
        })
        assert res.status_code == 401

    def test_change_password_requires_json(self, client):
        signup_and_login(client)
        res = client.post("/auth/change-password", data="not json",
                          content_type="text/plain")
        assert res.status_code == 400

    def test_change_password_wrong_current_password(self, client):
        signup_and_login(client)
        res = client.post("/auth/change-password", json={
            "old_password": "WRONGPASSWORD",
            "new_password": "newpassword123",
            "notes": []
        })
        assert res.status_code == 401
        assert "Invalid" in res.get_json()["error"]

    def test_change_password_new_too_short(self, client):
        signup_and_login(client)
        res = client.post("/auth/change-password", json={
            "old_password": "password123",
            "new_password": "abc",
            "notes": []
        })
        assert res.status_code == 400
        assert "8" in res.get_json()["error"]

    def test_change_password_missing_old_password(self, client):
        signup_and_login(client)
        res = client.post("/auth/change-password", json={
            "new_password": "newpassword123",
            "notes": []
        })
        assert res.status_code == 400

    def test_change_password_missing_new_password(self, client):
        signup_and_login(client)
        res = client.post("/auth/change-password", json={
            "old_password": "password123",
            "notes": []
        })
        assert res.status_code == 400

    def test_change_password_no_notes_succeeds(self, client):
        """Password change with an empty notes list should succeed (user has no notes)."""
        signup_and_login(client)
        res = client.post("/auth/change-password", json={
            "old_password": "password123",
            "new_password": "newpassword123",
            "notes": []
        })
        assert res.status_code == 200

    def test_change_password_with_multiple_notes(self, client):
        """All notes in the batch must be re-encrypted atomically."""
        signup_and_login(client)
        cat_id = make_category(client)

        note1_id = make_note(client, cat_id, "note one",   "One")["id"]
        note2_id = make_note(client, cat_id, "note two",   "Two")["id"]
        note3_id = make_note(client, cat_id, "note three", "Three")["id"]

        enc1 = fake_encrypted_payload("new one")
        enc2 = fake_encrypted_payload("new two")
        enc3 = fake_encrypted_payload("new three")

        res = client.post("/auth/change-password", json={
            "old_password": "password123",
            "new_password": "newpassword123",
            "notes": [
                {"id": note1_id, "version": 1, **enc1},
                {"id": note2_id, "version": 1, **enc2},
                {"id": note3_id, "version": 1, **enc3},
            ]
        })
        assert res.status_code == 200

        # Each note must have the new ciphertext and version=2
        for nid, enc in [(note1_id, enc1), (note2_id, enc2), (note3_id, enc3)]:
            note = client.get(f"/notes/{nid}").get_json()
            assert note["ciphertext"] == enc["ciphertext"]
            assert note["version"]    == 2

    def test_change_password_version_conflict_aborts_all(self, client):
        """
        If one note in the batch has a version conflict, the entire
        operation must be rolled back — nothing should be committed.
        """
        signup_and_login(client)
        cat_id = make_category(client)

        note1_id = make_note(client, cat_id, "note a", "A")["id"]
        note2_id = make_note(client, cat_id, "note b", "B")["id"]

        # Bump note2 to version 2 so version=1 in the batch is stale
        enc_bump = fake_encrypted_payload("bumped")
        client.put(f"/notes/{note2_id}", json={"version": 1, **enc_bump})

        enc1 = fake_encrypted_payload("re-enc a")
        enc2 = fake_encrypted_payload("re-enc b")

        res = client.post("/auth/change-password", json={
            "old_password": "password123",
            "new_password": "newpassword123",
            "notes": [
                {"id": note1_id, "version": 1, **enc1},  # correct
                {"id": note2_id, "version": 1, **enc2},  # stale — should abort
            ]
        })
        assert res.status_code == 409

        # note1 must NOT have been updated (rollback means the old ciphertext is intact)
        note1 = client.get(f"/notes/{note1_id}").get_json()
        assert note1["version"] == 1

    def test_change_password_note_wrong_user_rejected(self, client):
        """A note belonging to a different user must be rejected mid-batch."""
        # Create a note as user1
        signup_and_login(client, "owner@example.com")
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        client.post("/auth/logout")

        # user2 tries to include user1's note in their password change
        signup_and_login(client, "attacker@example.com")
        enc = fake_encrypted_payload("steal")
        res = client.post("/auth/change-password", json={
            "old_password": "password123",
            "new_password": "newpassword123",
            "notes": [{"id": note_id, "version": 1, **enc}]
        })
        assert res.status_code == 404

    def test_change_password_malformed_note_entry_rejected(self, client):
        """A note entry missing ciphertext/iv/salt must be caught before any DB write."""
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]

        res = client.post("/auth/change-password", json={
            "old_password": "password123",
            "new_password": "newpassword123",
            "notes": [{"id": note_id, "version": 1}]  # missing ciphertext, iv, salt
        })
        assert res.status_code == 400

    def test_change_password_old_password_rejected_after_change(self, client):
        signup_and_login(client)
        client.post("/auth/change-password", json={
            "old_password": "password123",
            "new_password": "newpassword123",
            "notes": []
        })
        client.post("/auth/logout")
        assert client.post("/auth/login", json={
            "email": "crud@example.com", "password": "password123"
        }).status_code == 401

    def test_change_password_new_password_works_after_change(self, client):
        signup_and_login(client)
        client.post("/auth/change-password", json={
            "old_password": "password123",
            "new_password": "newpassword123",
            "notes": []
        })
        client.post("/auth/logout")
        assert client.post("/auth/login", json={
            "email": "crud@example.com", "password": "newpassword123"
        }).status_code == 200


# ─────────────────────────────────────────────
# ACCOUNT DELETION & DB-BACKED TOKENS
# ─────────────────────────────────────────────

class TestAccountDeletion:
    def test_delete_account_requires_login(self, client):
        assert client.delete("/auth/account", json={"password": "x"}).status_code == 401

    def test_delete_account_requires_password(self, client):
        signup_and_login(client)
        res = client.delete("/auth/account", json={})
        assert res.status_code == 400

    def test_delete_account_wrong_password(self, client):
        signup_and_login(client)
        res = client.delete("/auth/account", json={"password": "wrong"})
        assert res.status_code == 401

    def test_delete_account_removes_user_and_data(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        client.post("/notes", json=fake_encrypted_payload("secret"))
        res = client.delete("/auth/account", json={"password": "password123"})
        assert res.status_code == 200
        assert client.get("/auth/me").status_code == 401


class TestDbBackedTokens:
    def test_auth_token_stored_as_hmac_hash_not_plaintext(self, client):
        """Raw bearer tokens must never be persisted — only HMAC-SHA256 digests."""
        from run import AuthToken, app

        client.post("/auth/signup", json={
            "email": "hash@example.com", "password": "password123", "name": "Hash User"
        })
        res = client.post("/auth/login", json={
            "email": "hash@example.com", "password": "password123"
        })
        raw_token = res.get_json()["token"]

        with app.app_context():
            rows = AuthToken.query.all()
            assert len(rows) == 1
            assert rows[0].token_hash != raw_token
            assert len(rows[0].token_hash) == 64
            assert all(c in "0123456789abcdef" for c in rows[0].token_hash)

    def test_login_returns_bearer_token(self, client):
        client.post("/auth/signup", json={
            "email": "token@example.com", "password": "password123", "name": "Token User"
        })
        res = client.post("/auth/login", json={
            "email": "token@example.com", "password": "password123"
        })
        assert res.status_code == 200
        assert "token" in res.get_json()

    def test_bearer_token_authenticates_me(self, client):
        client.post("/auth/signup", json={
            "email": "bearer@example.com", "password": "password123", "name": "Bearer User"
        })
        login = client.post("/auth/login", json={
            "email": "bearer@example.com", "password": "password123"
        })
        token = login.get_json()["token"]
        client.post("/auth/logout")
        res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        assert res.get_json()["email"] == "bearer@example.com"


class TestLegalPages:
    def test_privacy_policy(self, client):
        res = client.get("/legal/privacy")
        assert res.status_code == 200
        assert b"Privacy Policy" in res.data

    def test_terms_of_service(self, client):
        res = client.get("/legal/terms")
        assert res.status_code == 200
        assert b"Terms of Service" in res.data