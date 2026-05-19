"""
test_auth.py — InfoCord Test Suite
====================================
Covers:
  - Signup / Login / Session / Lockout (Auth)
  - Category CRUD
  - Note CRUD (with Phase 4 AES-GCM encryption assertions)
  - crypto_utils unit tests (encrypt, decrypt, tamper detection)

Environment:
  - Uses SQLite in-memory so no Postgres setup is needed.
  - Sets NOTE_ENCRYPTION_KEY automatically — tests are self-contained.
  - Run with: pytest test_auth.py -v
"""

import base64
import os
import secrets
import pytest

# ── Set required env vars BEFORE importing run.py ────────────────────────────
# This must happen before any app import so _load_key() finds the variable.
TEST_KEY = base64.b64encode(secrets.token_bytes(32)).decode()
os.environ.setdefault("NOTE_ENCRYPTION_KEY", TEST_KEY)
os.environ.setdefault("TEST_DATABASE_URI", "sqlite:///:memory:")
os.environ.setdefault("FLASK_SECRET_KEY", "test-only-secret")

from run import app, db  # noqa: E402 — import must come after env setup
from crypto_utils import encrypt_note, decrypt_note, generate_iv  # noqa: E402


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def client():
    """
    Provides a Flask test client backed by a fresh in-memory SQLite database.
    Each test gets a clean slate — tables are created before and dropped after.
    """
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SECRET_KEY"] = "test-only-secret"

    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client
        with app.app_context():
            db.drop_all()


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def signup_and_login(client, email="crud@example.com", password="password123", name="CRUD User"):
    """Sign up and immediately log in. Returns the login response."""
    client.post("/auth/signup", json={"email": email, "password": password, "name": name})
    return client.post("/auth/login", json={"email": email, "password": password})


def make_category(client, name="Notes", color="000000"):
    """Create a category and return its ID."""
    res = client.post("/categories", json={"name": name, "color": color})
    return res.get_json()["id"]


def make_note(client, category_id, content="test note"):
    """Create a note and return the full response JSON."""
    res = client.post("/notes", json={"category_id": category_id, "content": content})
    return res.get_json()


# ─────────────────────────────────────────────
# CRYPTO UNIT TESTS
# ─────────────────────────────────────────────

class TestCryptoUtils:
    """Unit tests for crypto_utils.py — isolated from Flask."""

    def test_generate_iv_is_12_bytes(self):
        iv = generate_iv()
        assert len(base64.b64decode(iv)) == 12, "IV must be exactly 12 bytes for AES-GCM"

    def test_generate_iv_is_unique(self):
        ivs = {generate_iv() for _ in range(100)}
        assert len(ivs) == 100, "IVs must be unique — reuse would break AES-GCM security"

    def test_encrypt_returns_two_strings(self):
        ciphertext, iv = encrypt_note("hello world")
        assert isinstance(ciphertext, str)
        assert isinstance(iv, str)

    def test_encrypt_output_is_base64(self):
        ciphertext, iv = encrypt_note("hello")
        # Should not raise
        base64.b64decode(ciphertext)
        base64.b64decode(iv)

    def test_ciphertext_differs_from_plaintext(self):
        plaintext = "super secret note"
        ciphertext, _ = encrypt_note(plaintext)
        assert ciphertext != plaintext, "Ciphertext must not equal plaintext"

    def test_same_plaintext_produces_different_ciphertext(self):
        """Proves a fresh IV is used on every encrypt call."""
        plaintext = "identical content"
        ct1, iv1 = encrypt_note(plaintext)
        ct2, iv2 = encrypt_note(plaintext)
        assert ct1 != ct2, "Same plaintext must produce different ciphertexts (unique IV)"
        assert iv1 != iv2, "Each encryption must use a unique IV"

    def test_round_trip(self):
        plaintext = "InfoCord note with emoji 🔒 and unicode: ñoño"
        ciphertext, iv = encrypt_note(plaintext)
        recovered = decrypt_note(ciphertext, iv)
        assert recovered == plaintext

    def test_round_trip_empty_string(self):
        ciphertext, iv = encrypt_note("")
        assert decrypt_note(ciphertext, iv) == ""

    def test_round_trip_long_content(self):
        plaintext = "a" * 9999
        ciphertext, iv = encrypt_note(plaintext)
        assert decrypt_note(ciphertext, iv) == plaintext

    def test_tampered_ciphertext_raises(self):
        ciphertext, iv = encrypt_note("sensitive data")
        # Corrupt the ciphertext by replacing it with garbage
        garbage = base64.b64encode(b"this is definitely not valid ciphertext padding").decode()
        with pytest.raises(ValueError, match="decryption failed"):
            decrypt_note(garbage, iv)

    def test_wrong_iv_raises(self):
        ciphertext, _ = encrypt_note("some note")
        _, different_iv = encrypt_note("another note")
        with pytest.raises(ValueError):
            decrypt_note(ciphertext, different_iv)

    def test_missing_ciphertext_raises(self):
        with pytest.raises(ValueError):
            decrypt_note("", "someiv")

    def test_missing_iv_raises(self):
        with pytest.raises(ValueError):
            decrypt_note("someciphertext", "")

    def test_invalid_base64_ciphertext_raises(self):
        with pytest.raises(ValueError):
            decrypt_note("!!!not_base64!!!", generate_iv())

    def test_encrypt_wrong_type_raises(self):
        with pytest.raises(TypeError):
            encrypt_note(12345)  # type: ignore

    def test_missing_key_raises(self):
        original = os.environ.pop("NOTE_ENCRYPTION_KEY")
        try:
            with pytest.raises(EnvironmentError, match="NOTE_ENCRYPTION_KEY"):
                encrypt_note("test")
        finally:
            os.environ["NOTE_ENCRYPTION_KEY"] = original  # always restore

    def test_wrong_length_key_raises(self):
        original = os.environ["NOTE_ENCRYPTION_KEY"]
        # 16-byte key — valid base64 but wrong length for AES-256
        short_key = base64.b64encode(secrets.token_bytes(16)).decode()
        os.environ["NOTE_ENCRYPTION_KEY"] = short_key
        try:
            with pytest.raises(EnvironmentError, match="32 bytes"):
                encrypt_note("test")
        finally:
            os.environ["NOTE_ENCRYPTION_KEY"] = original


# ─────────────────────────────────────────────
# SIGNUP TESTS
# ─────────────────────────────────────────────

class TestSignup:
    def test_signup_success(self, client):
        res = client.post("/auth/signup", json={
            "email": "test@example.com",
            "password": "password123",
            "name": "Test User"
        })
        assert res.status_code == 201
        assert res.get_json()["user"]["email"] == "test@example.com"

    def test_signup_missing_fields(self, client):
        res = client.post("/auth/signup", json={"email": "", "password": "", "name": ""})
        assert res.status_code == 400

    def test_signup_invalid_email(self, client):
        res = client.post("/auth/signup", json={
            "email": "not-an-email",
            "password": "password123",
            "name": "User"
        })
        assert res.status_code == 400

    def test_signup_short_password(self, client):
        res = client.post("/auth/signup", json={
            "email": "short@example.com",
            "password": "abc",
            "name": "Short"
        })
        assert res.status_code == 400

    def test_signup_duplicate_email(self, client):
        payload = {"email": "dup@example.com", "password": "password123", "name": "User"}
        client.post("/auth/signup", json=payload)
        res = client.post("/auth/signup", json=payload)
        assert res.status_code == 409

    def test_signup_name_too_long(self, client):
        res = client.post("/auth/signup", json={
            "email": "long@example.com",
            "password": "password123",
            "name": "x" * 101
        })
        assert res.status_code == 400


# ─────────────────────────────────────────────
# LOGIN TESTS
# ─────────────────────────────────────────────

class TestLogin:
    def test_login_success(self, client):
        signup_and_login(client, "login@example.com")
        res = client.post("/auth/login", json={
            "email": "login@example.com",
            "password": "password123"
        })
        assert res.status_code == 200
        assert res.get_json()["message"] == "Login successful"

    def test_login_wrong_password(self, client):
        signup_and_login(client, "wrong@example.com")
        res = client.post("/auth/login", json={
            "email": "wrong@example.com",
            "password": "badpass"
        })
        assert res.status_code == 401

    def test_login_nonexistent_user(self, client):
        res = client.post("/auth/login", json={
            "email": "ghost@example.com",
            "password": "password123"
        })
        assert res.status_code == 401

    def test_login_missing_fields(self, client):
        res = client.post("/auth/login", json={"email": "", "password": ""})
        assert res.status_code == 400


# ─────────────────────────────────────────────
# SESSION TESTS
# ─────────────────────────────────────────────

class TestSession:
    def test_me_requires_login(self, client):
        res = client.get("/auth/me")
        assert res.status_code == 401

    def test_me_after_login(self, client):
        signup_and_login(client, "me@example.com")
        res = client.get("/auth/me")
        assert res.status_code == 200
        assert res.get_json()["email"] == "me@example.com"

    def test_logout_clears_session(self, client):
        signup_and_login(client)
        client.post("/auth/logout")
        res = client.get("/auth/me")
        assert res.status_code == 401

    def test_logout_requires_login(self, client):
        res = client.post("/auth/logout")
        assert res.status_code == 401


# ─────────────────────────────────────────────
# LOCKOUT TESTS
# ─────────────────────────────────────────────

class TestLockout:
    def test_account_lockout_after_5_failures(self, client):
        signup_and_login(client, "lock@example.com")
        client.post("/auth/logout")

        for _ in range(5):
            client.post("/auth/login", json={
                "email": "lock@example.com",
                "password": "wrongpass"
            })

        res = client.post("/auth/login", json={
            "email": "lock@example.com",
            "password": "password123"  # correct password — still locked
        })
        assert res.status_code == 423

    def test_failed_attempts_reset_on_success(self, client):
        signup_and_login(client, "reset@example.com")
        client.post("/auth/logout")

        # 4 failures — not yet locked
        for _ in range(4):
            client.post("/auth/login", json={
                "email": "reset@example.com",
                "password": "wrongpass"
            })

        # Correct login resets the counter
        res = client.post("/auth/login", json={
            "email": "reset@example.com",
            "password": "password123"
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
        res = client.post("/categories", json={"name": "School", "color": "FF0000"})
        assert res.status_code == 401

    def test_create_category_missing_fields(self, client):
        signup_and_login(client)
        res = client.post("/categories", json={"name": "NoColor"})
        assert res.status_code == 400

    def test_get_categories(self, client):
        signup_and_login(client)
        client.post("/categories", json={"name": "A", "color": "000000"})
        client.post("/categories", json={"name": "B", "color": "111111"})
        res = client.get("/categories")
        assert res.status_code == 200
        assert len(res.get_json()) == 2

    def test_get_categories_isolated_per_user(self, client):
        """Each user should only see their own categories."""
        signup_and_login(client, "user1@example.com")
        client.post("/categories", json={"name": "User1 Cat", "color": "AAAAAA"})
        client.post("/auth/logout")

        signup_and_login(client, "user2@example.com")
        res = client.get("/categories")
        assert res.get_json() == []

    def test_update_category(self, client):
        signup_and_login(client)
        cat_id = make_category(client, "Old Name", "000000")
        res = client.put(f"/categories/{cat_id}", json={"name": "New Name"})
        assert res.status_code == 200

    def test_archive_category(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.patch(f"/categories/{cat_id}/archive")
        assert res.status_code == 200

    def test_cannot_archive_another_users_category(self, client):
        signup_and_login(client, "owner@example.com")
        cat_id = make_category(client)
        client.post("/auth/logout")

        signup_and_login(client, "attacker@example.com")
        res = client.patch(f"/categories/{cat_id}/archive")
        assert res.status_code == 404


# ─────────────────────────────────────────────
# NOTE TESTS — Phase 4 encryption assertions
# ─────────────────────────────────────────────

class TestNotes:
    def test_create_note_success(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.post("/notes", json={"category_id": cat_id, "content": "hello world"})
        assert res.status_code == 201

    def test_create_note_returns_plaintext_to_caller(self, client):
        """The API should echo back plaintext, not ciphertext, on create."""
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.post("/notes", json={"category_id": cat_id, "content": "my secret note"})
        assert res.get_json()["content"] == "my secret note"

    def test_create_note_requires_login(self, client):
        res = client.post("/notes", json={"category_id": "fake-id", "content": "x"})
        assert res.status_code == 401

    def test_create_note_missing_category(self, client):
        signup_and_login(client)
        res = client.post("/notes", json={"content": "orphan note"})
        assert res.status_code == 400

    def test_note_length_validation(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.post("/notes", json={"category_id": cat_id, "content": "a" * 10001})
        assert res.status_code == 400

    def test_get_notes_returns_plaintext(self, client):
        """
        Phase 4 core assertion: GET /notes must return decrypted plaintext,
        not raw ciphertext from the database.
        """
        signup_and_login(client)
        cat_id = make_category(client)
        client.post("/notes", json={"category_id": cat_id, "content": "decrypted content"})

        res = client.get("/notes")
        assert res.status_code == 200
        notes = res.get_json()
        assert len(notes) == 1
        assert notes[0]["content"] == "decrypted content"

    def test_get_notes_content_is_not_base64_ciphertext(self, client):
        """
        The value returned in 'content' must be human-readable plaintext,
        not a base64 blob. This guards against accidentally returning raw DB values.
        """
        signup_and_login(client)
        cat_id = make_category(client)
        plaintext = "readable note content"
        client.post("/notes", json={"category_id": cat_id, "content": plaintext})

        notes = client.get("/notes").get_json()
        returned = notes[0]["content"]

        # Plaintext should match exactly
        assert returned == plaintext

        # It should NOT look like a base64 ciphertext (much longer than plaintext)
        assert len(returned) <= len(plaintext) + 10, (
            "Returned content looks like ciphertext — decryption may not be working"
        )

    def test_multiple_notes_all_decrypted(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        contents = ["note one", "note two", "note three"]
        for c in contents:
            client.post("/notes", json={"category_id": cat_id, "content": c})

        notes = client.get("/notes").get_json()
        returned = {n["content"] for n in notes}
        assert returned == set(contents)

    def test_notes_isolated_per_user(self, client):
        signup_and_login(client, "user1@example.com")
        cat_id = make_category(client)
        client.post("/notes", json={"category_id": cat_id, "content": "user1 note"})
        client.post("/auth/logout")

        signup_and_login(client, "user2@example.com")
        notes = client.get("/notes").get_json()
        assert notes == []

    def test_update_note(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        note = make_note(client, cat_id, "original")
        note_id = note["id"]

        # Phase 5: version must be supplied; new notes start at version=1
        res = client.put(f"/notes/{note_id}", json={"content": "updated", "version": 1})
        assert res.status_code == 200

    def test_update_note_content_re_encrypted(self, client):
        """After PUT, GET must return the updated plaintext — not the old value."""
        signup_and_login(client)
        cat_id = make_category(client)
        note_id = make_note(client, cat_id, "original content")["id"]

        client.put(f"/notes/{note_id}", json={"content": "updated content", "version": 1})

        notes = client.get("/notes").get_json()
        assert notes[0]["content"] == "updated content"

    def test_update_note_length_validation(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        res = client.put(f"/notes/{note_id}", json={"content": "a" * 10001})
        assert res.status_code == 400

    def test_cannot_update_another_users_note(self, client):
        signup_and_login(client, "owner@example.com")
        cat_id = make_category(client)
        note_id = make_note(client, cat_id, "private")["id"]
        client.post("/auth/logout")

        signup_and_login(client, "attacker@example.com")
        res = client.put(f"/notes/{note_id}", json={"content": "hacked"})
        assert res.status_code == 404

    def test_archive_note(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        res = client.patch(f"/notes/{note_id}/archive")
        assert res.status_code == 200

    def test_cannot_archive_another_users_note(self, client):
        signup_and_login(client, "owner@example.com")
        cat_id = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        client.post("/auth/logout")

        signup_and_login(client, "attacker@example.com")
        res = client.patch(f"/notes/{note_id}/archive")
        assert res.status_code == 404

    def test_invalid_category_id_rejected(self, client):
        signup_and_login(client)
        res = client.post("/notes", json={
            "category_id": "00000000-0000-0000-0000-000000000000",
            "content": "orphan"
        })
        assert res.status_code == 404


# ─────────────────────────────────────────────
# PHASE 5 — VERSION-BASED SYNC TESTS
# ─────────────────────────────────────────────

class TestVersionSync:
    """
    Phase 5 verifies that concurrent/stale updates are detected and rejected.

    The flow:
      1. Client creates a note → receives version=1
      2. Client sends PUT with version=1 → succeeds, server returns version=2
      3. If a second client (or stale tab) sends PUT with version=1 again
         → server rejects with 409 Conflict
      4. The stale client must GET the note to retrieve version=2, then retry.
    """

    def test_create_note_returns_version_1(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        res = client.post("/notes", json={"category_id": cat_id, "content": "v1"})
        assert res.status_code == 201
        assert res.get_json()["version"] == 1

    def test_get_notes_includes_version(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        client.post("/notes", json={"category_id": cat_id, "content": "versioned"})
        notes = client.get("/notes").get_json()
        assert "version" in notes[0]
        assert notes[0]["version"] == 1

    def test_successful_update_increments_version(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        note_id = make_note(client, cat_id, "original")["id"]

        res = client.put(f"/notes/{note_id}", json={"content": "updated", "version": 1})
        assert res.status_code == 200
        assert res.get_json()["version"] == 2

    def test_version_increments_on_each_update(self, client):
        """Sequential updates: version should climb 1 -> 2 -> 3."""
        signup_and_login(client)
        cat_id = make_category(client)
        note_id = make_note(client, cat_id, "v1")["id"]

        r2 = client.put(f"/notes/{note_id}", json={"content": "v2", "version": 1})
        assert r2.get_json()["version"] == 2

        r3 = client.put(f"/notes/{note_id}", json={"content": "v3", "version": 2})
        assert r3.get_json()["version"] == 3

    def test_stale_version_rejected_with_409(self, client):
        """
        Simulates a stale client sending an outdated version.
        The server must reject it so no data is silently overwritten.
        """
        signup_and_login(client)
        cat_id = make_category(client)
        note_id = make_note(client, cat_id, "original")["id"]

        # First update succeeds - server is now at version 2
        client.put(f"/notes/{note_id}", json={"content": "first update", "version": 1})

        # Stale client still thinks it's at version 1 - must be rejected
        res = client.put(f"/notes/{note_id}", json={"content": "stale write", "version": 1})
        assert res.status_code == 409

    def test_conflict_response_includes_server_version(self, client):
        """
        The 409 body must tell the client what version the server is at,
        so it knows what to fetch for conflict resolution.
        """
        signup_and_login(client)
        cat_id = make_category(client)
        note_id = make_note(client, cat_id, "original")["id"]

        client.put(f"/notes/{note_id}", json={"content": "bumped", "version": 1})

        res = client.put(f"/notes/{note_id}", json={"content": "conflict", "version": 1})
        body = res.get_json()
        assert res.status_code == 409
        assert body["server_version"] == 2
        assert "conflict" in body["error"].lower()

    def test_stale_write_does_not_overwrite_content(self, client):
        """
        After a rejected 409, the winning update's content must still be
        returned by GET - the stale write must not have landed.
        """
        signup_and_login(client)
        cat_id = make_category(client)
        note_id = make_note(client, cat_id, "original")["id"]

        client.put(f"/notes/{note_id}", json={"content": "winning write", "version": 1})

        # Stale write - rejected
        client.put(f"/notes/{note_id}", json={"content": "stale write", "version": 1})

        notes = client.get("/notes").get_json()
        assert notes[0]["content"] == "winning write"

    def test_update_missing_version_rejected(self, client):
        """Clients that omit version entirely get a 400, not a silent overwrite."""
        signup_and_login(client)
        cat_id = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        res = client.put(f"/notes/{note_id}", json={"content": "no version"})
        assert res.status_code == 400

    def test_update_non_integer_version_rejected(self, client):
        signup_and_login(client)
        cat_id = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        res = client.put(f"/notes/{note_id}", json={"content": "bad", "version": "one"})
        assert res.status_code == 400

    def test_future_version_rejected(self, client):
        """
        A client that sends a version higher than the server's is also a
        conflict - it should not be trusted.
        """
        signup_and_login(client)
        cat_id = make_category(client)
        note_id = make_note(client, cat_id)["id"]
        res = client.put(f"/notes/{note_id}", json={"content": "from the future", "version": 99})
        assert res.status_code == 409

    def test_client_conflict_resolution_flow(self, client):
        """
        Full round-trip simulating the correct conflict resolution sequence:
          1. Client A updates -> version 2
          2. Client B's write at version 1 is rejected (409)
          3. Client B fetches latest -> sees version 2
          4. Client B retries with version 2 -> succeeds -> version 3
        """
        signup_and_login(client)
        cat_id = make_category(client)
        note_id = make_note(client, cat_id, "initial")["id"]

        # Client A updates successfully
        client.put(f"/notes/{note_id}", json={"content": "client A write", "version": 1})

        # Client B sends stale write - rejected
        conflict = client.put(f"/notes/{note_id}", json={"content": "client B write", "version": 1})
        assert conflict.status_code == 409

        # Client B fetches latest to get current version
        notes = client.get("/notes").get_json()
        current_version = notes[0]["version"]
        assert current_version == 2

        # Client B retries with correct version - succeeds
        retry = client.put(f"/notes/{note_id}", json={
            "content": "client B resolved write",
            "version": current_version
        })
        assert retry.status_code == 200
        assert retry.get_json()["version"] == 3