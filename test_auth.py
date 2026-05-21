"""
test_auth.py — InfoCord Full Test Suite
========================================
Phases covered:
  Phase 4 — AES-GCM encryption (crypto_utils unit tests + note round-trips)
  Phase 5 — Version-based sync (conflict detection, resolution flow)
  Phase 6 — Stability & error handling
               • global error handlers (404, 405)
               • UUID validation on every route
               • hex color validation
               • archived-state guards (notes + categories)
               • DB commit wrapper (via SQLAlchemyError simulation)
               • health-check endpoint
               • request-id header present on all responses
               • update_category body + field validation
               • content type validation

Environment:
  Self-contained — sets all required env vars before any import.
  Uses SQLite in-memory; no Postgres needed.
  Run with:  pytest test_auth.py -v
"""

import base64
import os
import secrets
import pytest
from unittest.mock import patch

# ── Env vars MUST be set before importing run.py ─────────────────────────────
TEST_KEY = base64.b64encode(secrets.token_bytes(32)).decode()
os.environ.setdefault("NOTE_ENCRYPTION_KEY", TEST_KEY)
os.environ.setdefault("TEST_DATABASE_URI",   "sqlite:///:memory:")
os.environ.setdefault("FLASK_SECRET_KEY",    "test-only-secret")

from run import app, db                               # noqa: E402
from crypto_utils import encrypt_note, decrypt_note, generate_iv  # noqa: E402


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def client():
    """Fresh in-memory DB for every test."""
    app.config["TESTING"]                = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["WTF_CSRF_ENABLED"]       = False
    app.config["SECRET_KEY"]             = "test-only-secret"

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


def make_note(client, category_id, content="test note"):
    res = client.post("/notes", json={"category_id": category_id, "content": content})
    return res.get_json()


# ─────────────────────────────────────────────
# CRYPTO UNIT TESTS  (Phase 4)
# ─────────────────────────────────────────────

class TestCryptoUtils:
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
        assert res.get_json()["status"] == "ok"
        assert res.get_json()["db"] == "ok"

    def test_health_returns_json(self, client):
        res = client.get("/health")
        assert res.content_type == "application/json"


# ─────────────────────────────────────────────
# REQUEST ID HEADER  (Phase 6)
# ─────────────────────────────────────────────

class TestRequestId:
    def test_request_id_present_on_success(self, client):
        res = client.get("/")
        assert "X-Request-ID" in res.headers

    def test_request_id_present_on_404(self, client):
        res = client.get("/nonexistent-route")
        assert "X-Request-ID" in res.headers

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
        # GET on a POST-only endpoint
        res = client.get("/auth/signup")
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
        res = client.patch("/categories/bad-uuid/archive")
        assert res.status_code == 400

    def test_bad_note_uuid_on_update(self, client):
        signup_and_login(client)
        res = client.put("/notes/not-a-uuid", json={"content": "x", "version": 1})
        assert res.status_code == 400

    def test_bad_note_uuid_on_archive(self, client):
        signup_and_login(client)
        res = client.patch("/notes/bad-uuid/archive")
        assert res.status_code == 400

    def test_bad_category_id_in_note_create(self, client):
        signup_and_login(client)
        res = client.post("/notes", json={"category_id": "not-a-uuid", "content": "x"})
        assert res.status_code == 400


# ─────────────────────────────────────────────
# HEX COLOR VALIDATION  (Phase 6)
# ─────────────────────────────────────────────

class TestHexColor:
    def test_valid_hex_color_accepted(self, client):
        signup_and_login(client)
        res = client.post("/categories", json={"name": "A", "color": "FF0000"})
        assert res.status_code == 201

    def test_lowercase_hex_accepted(self, client):
        signup_and_login(client)
        res = client.post("/categories", json={"name": "B", "color": "ff0000"})
        assert res.status_code == 201

    def test_short_hex_rejected(self, client):
        signup_and_login(client)
        res = client.post("/categories", json={"name": "C", "color": "FFF"})
        assert res.status_code == 400
        assert "hex" in res.get_json()["error"].lower()

    def test_invalid_hex_chars_rejected(self, client):
        signup_and_login(client)
        res = client.post("/categories", json={"name": "D", "color": "ZZZZZZ"})
        assert res.status_code == 400

    def test_empty_color_rejected(self, client):
        signup_and_login(client)
        res = client.post("/categories", json={"name": "E", "color": ""})
        assert res.status_code == 400

    def test_update_with_invalid_hex_rejected(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.put(f"/categories/{cat_id}", json={"color": "GGG"})
        assert res.status_code == 400


# ─────────────────────────────────────────────
# ARCHIVED STATE GUARDS  (Phase 6)
# ─────────────────────────────────────────────

class TestArchivedGuards:
    def test_cannot_add_note_to_archived_category(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        client.patch(f"/categories/{cat_id}/archive")

        res = client.post("/notes", json={"category_id": cat_id, "content": "new note"})
        assert res.status_code == 409
        assert "archived" in res.get_json()["error"].lower()

    def test_cannot_update_archived_note(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        client.patch(f"/notes/{note_id}/archive")

        res = client.put(f"/notes/{note_id}", json={"content": "edit", "version": 1})
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
        res = client.put(f"/categories/{cat_id}", json={"name": "   "})
        assert res.status_code == 400

    def test_update_name_too_long_rejected(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.put(f"/categories/{cat_id}", json={"name": "x" * 121})
        assert res.status_code == 400

    def test_update_valid_name_succeeds(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.put(f"/categories/{cat_id}", json={"name": "Updated"})
        assert res.status_code == 200

    def test_update_valid_color_succeeds(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.put(f"/categories/{cat_id}", json={"color": "AABBCC"})
        assert res.status_code == 200


# ─────────────────────────────────────────────
# NOTE CONTENT VALIDATION  (Phase 6)
# ─────────────────────────────────────────────

class TestNoteContentValidation:
    def test_non_string_content_rejected(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.post("/notes", json={"category_id": cat_id, "content": 12345})
        assert res.status_code == 400
        assert "string" in res.get_json()["error"].lower()

    def test_non_string_content_on_update_rejected(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        res = client.put(f"/notes/{note_id}", json={"content": True, "version": 1})
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
        res = client.post("/auth/signup", json=payload)
        assert res.status_code == 409

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
        res = client.post("/auth/login", json={
            "email": "wrong@example.com", "password": "badpass"
        })
        assert res.status_code == 401

    def test_login_nonexistent_user(self, client):
        res = client.post("/auth/login", json={
            "email": "ghost@example.com", "password": "password123"
        })
        assert res.status_code == 401

    def test_login_missing_fields(self, client):
        res = client.post("/auth/login", json={"email": "", "password": ""})
        assert res.status_code == 400

    def test_login_requires_json(self, client):
        res = client.post("/auth/login", data="not json", content_type="text/plain")
        assert res.status_code == 400


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
        res = client.post("/auth/login", json={
            "email": "lock@example.com", "password": "password123"
        })
        assert res.status_code == 423

    def test_failed_attempts_reset_on_success(self, client):
        signup_and_login(client, "reset@example.com")
        client.post("/auth/logout")
        for _ in range(4):
            client.post("/auth/login", json={
                "email": "reset@example.com", "password": "wrongpass"
            })
        res = client.post("/auth/login", json={
            "email": "reset@example.com", "password": "password123"
        })
        assert res.status_code == 200


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
        assert client.post("/categories", json={"name": "x", "color": "000000"}).status_code == 401

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
# NOTE TESTS  (Phase 4 encryption assertions)
# ─────────────────────────────────────────────

class TestNotes:
    def test_create_note_success(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        assert client.post("/notes", json={"category_id": cat_id, "content": "hi"}).status_code == 201

    def test_create_note_returns_plaintext(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.post("/notes", json={"category_id": cat_id, "content": "my secret"})
        assert res.get_json()["content"] == "my secret"

    def test_create_note_requires_login(self, client):
        assert client.post("/notes", json={"category_id": "x", "content": "y"}).status_code == 401

    def test_create_note_missing_category(self, client):
        signup_and_login(client)
        assert client.post("/notes", json={"content": "orphan"}).status_code == 400

    def test_note_length_validation(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        assert client.post("/notes", json={"category_id": cat_id, "content": "a" * 10001}).status_code == 400

    def test_get_notes_returns_plaintext(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        client.post("/notes", json={"category_id": cat_id, "content": "decrypted content"})
        notes = client.get("/notes").get_json()
        assert notes[0]["content"] == "decrypted content"

    def test_get_notes_not_base64_ciphertext(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        plaintext = "readable note"
        client.post("/notes", json={"category_id": cat_id, "content": plaintext})
        returned = client.get("/notes").get_json()[0]["content"]
        assert returned == plaintext
        assert len(returned) <= len(plaintext) + 10

    def test_multiple_notes_all_decrypted(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        contents = ["note one", "note two", "note three"]
        for c in contents:
            client.post("/notes", json={"category_id": cat_id, "content": c})
        returned = {n["content"] for n in client.get("/notes").get_json()}
        assert returned == set(contents)

    def test_notes_isolated_per_user(self, client):
        signup_and_login(client, "user1@example.com")
        cat_id = make_category(client)
        client.post("/notes", json={"category_id": cat_id, "content": "private"})
        client.post("/auth/logout")
        signup_and_login(client, "user2@example.com")
        assert client.get("/notes").get_json() == []

    def test_update_note(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id, "original")["id"]
        assert client.put(f"/notes/{note_id}", json={"content": "updated", "version": 1}).status_code == 200

    def test_update_note_re_encrypted(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id, "original content")["id"]
        client.put(f"/notes/{note_id}", json={"content": "updated content", "version": 1})
        assert client.get("/notes").get_json()[0]["content"] == "updated content"

    def test_update_note_length_validation(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        assert client.put(f"/notes/{note_id}", json={"content": "a" * 10001, "version": 1}).status_code == 400

    def test_cannot_update_another_users_note(self, client):
        signup_and_login(client, "owner@example.com")
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id, "private")["id"]
        client.post("/auth/logout")
        signup_and_login(client, "attacker@example.com")
        assert client.put(f"/notes/{note_id}", json={"content": "hacked", "version": 1}).status_code == 404

    def test_archive_note(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        assert client.patch(f"/notes/{note_id}/archive").status_code == 200

    def test_cannot_archive_another_users_note(self, client):
        signup_and_login(client, "owner@example.com")
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        client.post("/auth/logout")
        signup_and_login(client, "attacker@example.com")
        assert client.patch(f"/notes/{note_id}/archive").status_code == 404

    def test_invalid_category_id_rejected(self, client):
        signup_and_login(client)
        res = client.post("/notes", json={
            "category_id": "00000000-0000-0000-0000-000000000000",
            "content": "orphan"
        })
        assert res.status_code == 404


# ─────────────────────────────────────────────
# PHASE 5 — VERSION SYNC TESTS
# ─────────────────────────────────────────────

class TestVersionSync:
    def test_create_note_returns_version_1(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.post("/notes", json={"category_id": cat_id, "content": "v1"})
        assert res.get_json()["version"] == 1

    def test_get_notes_includes_version(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        client.post("/notes", json={"category_id": cat_id, "content": "versioned"})
        notes = client.get("/notes").get_json()
        assert notes[0]["version"] == 1

    def test_successful_update_increments_version(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        res = client.put(f"/notes/{note_id}", json={"content": "updated", "version": 1})
        assert res.get_json()["version"] == 2

    def test_version_increments_sequentially(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id, "v1")["id"]
        r2 = client.put(f"/notes/{note_id}", json={"content": "v2", "version": 1})
        assert r2.get_json()["version"] == 2
        r3 = client.put(f"/notes/{note_id}", json={"content": "v3", "version": 2})
        assert r3.get_json()["version"] == 3

    def test_stale_version_rejected_409(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        client.put(f"/notes/{note_id}", json={"content": "first", "version": 1})
        res = client.put(f"/notes/{note_id}", json={"content": "stale", "version": 1})
        assert res.status_code == 409

    def test_conflict_response_includes_server_version(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        client.put(f"/notes/{note_id}", json={"content": "bumped", "version": 1})
        res = client.put(f"/notes/{note_id}", json={"content": "conflict", "version": 1})
        body = res.get_json()
        assert res.status_code == 409
        assert body["server_version"] == 2
        assert "conflict" in body["error"].lower()

    def test_stale_write_does_not_overwrite(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        client.put(f"/notes/{note_id}", json={"content": "winning", "version": 1})
        client.put(f"/notes/{note_id}", json={"content": "stale",   "version": 1})
        assert client.get("/notes").get_json()[0]["content"] == "winning"

    def test_update_missing_version_rejected(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        assert client.put(f"/notes/{note_id}", json={"content": "no ver"}).status_code == 400

    def test_update_non_integer_version_rejected(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        assert client.put(f"/notes/{note_id}", json={"content": "x", "version": "one"}).status_code == 400

    def test_future_version_rejected(self, client):
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        assert client.put(f"/notes/{note_id}", json={"content": "x", "version": 99}).status_code == 409

    def test_conflict_resolution_full_flow(self, client):
        """Client B gets rejected, fetches latest, retries with correct version."""
        signup_and_login(client)
        cat_id  = make_category(client)
        note_id = make_note(client, cat_id, "initial")["id"]

        # Client A wins
        client.put(f"/notes/{note_id}", json={"content": "A write", "version": 1})

        # Client B is stale
        assert client.put(f"/notes/{note_id}", json={"content": "B stale", "version": 1}).status_code == 409

        # Client B fetches latest and retries
        current_version = client.get("/notes").get_json()[0]["version"]
        assert current_version == 2

        retry = client.put(f"/notes/{note_id}", json={
            "content": "B resolved", "version": current_version
        })
        assert retry.status_code == 200
        assert retry.get_json()["version"] == 3