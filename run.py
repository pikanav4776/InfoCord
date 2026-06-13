import logging
import os
import re
import uuid
import hashlib
import hmac
from datetime import datetime, timedelta
from functools import wraps
import secrets

from flask import Flask, request, jsonify, session, g, render_template, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import or_
from werkzeug.security import generate_password_hash, check_password_hash

from dotenv import load_dotenv
from flask_cors import CORS


load_dotenv() 

# authentication information
DB_PORT          = os.getenv("DB_PORT")
DB_username      = os.getenv("DB_username")
DB_password      = os.getenv("DB_password")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")


def sanitize_database_url(url: str | None) -> str:
    """Strip whitespace/quotes/newlines from pasted connection strings (Render dashboard)."""
    if not url:
        return ""
    cleaned = url.strip().strip('"').strip("'")
    return cleaned.replace("\r", "").replace("\n", "")


DATABASE_URL = sanitize_database_url(os.getenv("DATABASE_URL"))

MAX_NOTE_LENGTH           = 10000
MAX_CATEGORY_NAME         = 120
MAX_NOTE_LINKS            = 10
MAX_FAILED_ATTEMPTS       = 5
LOCKOUT_DURATION_MINUTES  = 15
TOKEN_EXPIRY_DAYS         = 7

# Alembic head — keep in sync with migrations/versions/ (Gate A health check)
EXPECTED_MIGRATION_REVISION = "e8f4a1b2c3d5"
REQUIRED_SCHEMA_TABLES = (
    "users",
    "categories",
    "notes",
    "note_links",
    "auth_tokens",
    "rate_limit_buckets",
)

app = Flask(__name__)
CORS(
    app,
    supports_credentials=True,
    origins=[
        re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"),
        "null",                               # file:// origin
        "https://infocord.onrender.com",
    ],
)

app.config['SECRET_KEY']                  = FLASK_SECRET_KEY # for signing
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # optimization
app.config['SESSION_COOKIE_HTTPONLY']     = True #
app.config['SESSION_COOKIE_SECURE']       = os.getenv("FLASK_ENV") == "production" # Cookie only sent over HTTPS in production
app.config['SESSION_COOKIE_SAMESITE']     = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME']  = timedelta(days=TOKEN_EXPIRY_DAYS)
app.config["RATELIMIT_ENABLED"]           = False  # auth rate limits use PostgreSQL buckets


def normalize_db_url(url: str) -> str:
    url = sanitize_database_url(url)
    if not url:
        return url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    # Neon Connect may append channel_binding=require; Render/libpq often rejects it (503).
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    if parsed.query:
        q = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k.lower() != "channel_binding"
        ]
        url = urlunparse(parsed._replace(query=urlencode(q)))
    return url


def _safe_db_error_hint(exc: Exception) -> str:
    """First-line DB error for /health — no credentials or full URLs."""
    msg = str(exc).split("\n")[0][:240]
    msg = re.sub(r"postgresql[^\s'\"]+", "[connection-url]", msg, flags=re.IGNORECASE)
    return msg


def _db_host_hint() -> str | None:
    """Non-secret host/db identifier so Gate A can confirm the same DB was migrated."""
    raw = os.getenv("DATABASE_URL") or app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    if not raw:
        return None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(raw.replace("postgresql+psycopg2://", "postgresql://", 1))
        host = parsed.hostname or ""
        dbname = (parsed.path or "").lstrip("/").split("?")[0] or ""
        return f"{host}/{dbname}" if host else None
    except Exception:
        return None


app.config['SQLALCHEMY_DATABASE_URI'] = (
    os.getenv('TEST_DATABASE_URI') # when would this occur? when running tests
    or normalize_db_url(DATABASE_URL) # when would this occur? # when running the app
    or f'postgresql+psycopg2://{DB_username}:{DB_password}@localhost:{DB_PORT}/infocord_mvp' # when would this occur? # fallback to local database
)


# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

def _configure_logging() -> None:
    """Selects the logging level based on the environment."""
    log_level = logging.DEBUG if os.getenv("FLASK_ENV") != "production" else logging.INFO 
    fmt = "%(asctime)s | %(levelname)-8s | %(request_id)s | %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S"

    handler = logging.StreamHandler()
    handler.setFormatter(_RequestIdFormatter(fmt, datefmt=datefmt))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    if os.getenv("FLASK_ENV") == "production":
        logging.getLogger("werkzeug").setLevel(logging.WARNING)


class _RequestIdFormatter(logging.Formatter):
    """Injects g.request_id into every log record (falls back to '-')."""
    def format(self, record: logging.LogRecord) -> str:
        try:
            from flask import g as flask_g
            record.request_id = getattr(flask_g, "request_id", "-")
        except RuntimeError:
            record.request_id = "-"
        return super().format(record)


_configure_logging()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# DB / MIGRATE
# ─────────────────────────────────────────────

db      = SQLAlchemy()
migrate = Migrate()

db.init_app(app)
migrate.init_app(app, db)


def _hash_token(raw_token: str) -> str:
    """HMAC-SHA256 with server secret — raw tokens are never stored in PostgreSQL."""
    secret = (app.config.get("SECRET_KEY") or FLASK_SECRET_KEY or "").encode("utf-8")
    if not secret:
        raise RuntimeError("FLASK_SECRET_KEY is required for auth token hashing")
    return hmac.new(secret, raw_token.encode("utf-8"), hashlib.sha256).hexdigest()


def create_auth_token(user_id) -> str:
    """Issue a Bearer token persisted in PostgreSQL (safe across workers/restarts)."""
    purge_expired_auth_tokens()
    raw_token = secrets.token_urlsafe(32)
    db.session.add(AuthToken(
        token_hash=_hash_token(raw_token),
        user_id=user_id,
        expires_at=datetime.now() + timedelta(days=TOKEN_EXPIRY_DAYS),
    ))
    db.session.commit()
    return raw_token


def resolve_auth_token(raw_token: str):
    if not raw_token:
        return None
    row = db.session.get(AuthToken, _hash_token(raw_token))
    if not row or row.expires_at < datetime.now():
        if row:
            db.session.delete(row)
            db.session.commit()
        return None
    return row.user_id


def revoke_auth_token(raw_token: str) -> None:
    if not raw_token:
        return
    row = db.session.get(AuthToken, _hash_token(raw_token))
    if row:
        db.session.delete(row)
        db.session.commit()


def revoke_all_user_tokens(user_id) -> None:
    AuthToken.query.filter_by(user_id=user_id).delete()
    db.session.commit()


def purge_expired_auth_tokens() -> None:
    AuthToken.query.filter(AuthToken.expires_at < datetime.now()).delete()
    db.session.commit()


def rate_limit_key() -> str:
    """Rate-limit by account identity — never by client IP."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        user_id = resolve_auth_token(auth_header[7:])
        if user_id:
            return f"user:{user_id}"
    if session.get("logged_in") and session.get("user_id"):
        return f"user:{session['user_id']}"
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if email:
        return f"email:{email}"
    return "anon"


def _window_start(now: datetime, window_seconds: int) -> datetime:
    if window_seconds <= 60:
        return now.replace(second=0, microsecond=0)
    if window_seconds <= 3600:
        return now.replace(minute=0, second=0, microsecond=0)
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % window_seconds))


def _allow_db_rate_limit(scope: str, max_count: int, window_seconds: int) -> bool:
    """Fixed-window rate limit backed by PostgreSQL (multi-worker safe)."""
    window_start = _window_start(datetime.now(), window_seconds)

    bucket = RateLimitBucket.query.filter_by(
        bucket_key=scope,
        window_start=window_start,
    ).first()

    if not bucket:
        db.session.add(RateLimitBucket(bucket_key=scope, window_start=window_start, count=1))
        db.session.commit()
        return True

    if bucket.count >= max_count:
        return False

    bucket.count += 1
    db.session.commit()
    return True


def db_rate_limit(*rules):
    """
    Decorator: db_rate_limit((5, 60), (20, 3600))  → 5/min and 20/hour.
    Each rule is (max_count, window_seconds).
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if app.config.get("TESTING") or os.getenv("FLASK_ENV") != "production":
                return f(*args, **kwargs)
            identity = rate_limit_key()
            for max_count, window_seconds in rules:
                scope = f"{request.endpoint}:{identity}:{window_seconds}"
                if not _allow_db_rate_limit(scope, max_count, window_seconds):
                    logger.warning(f"429 Rate Limited: {request.path} scope={scope}")
                    return jsonify({"error": "Too many requests. Please slow down."}), 429
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ─────────────────────────────────────────────
# REQUEST LIFECYCLE HOOKS 
# ─────────────────────────────────────────────

@app.before_request
def _before_request() -> None:
    g.request_id = str(uuid.uuid4())[:8] # why truncate the UUID here?
    g.start_time = datetime.now()
    logger.info(f"{request.method} {request.path} — started")


@app.after_request
def _after_request(response):
    elapsed_ms = int((datetime.now() - g.start_time).total_seconds() * 1000)
    logger.info(
        f"{request.method} {request.path} — "
        f"{response.status_code} ({elapsed_ms}ms)"
    )
    response.headers["X-Request-ID"] = g.request_id
    return response


# ─────────────────────────────────────────────
# GLOBAL ERROR HANDLERS
# ─────────────────────────────────────────────

@app.errorhandler(400)
def bad_request(e):
    logger.warning(f"400 Bad Request: {e}")
    return jsonify({"error": "Bad request", "detail": str(e)}), 400


@app.errorhandler(404)
def not_found(e):
    logger.warning(f"404 Not Found: {request.path}")
    return jsonify({"error": "Resource not found"}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    logger.warning(f"405 Method Not Allowed: {request.method} {request.path}")
    return jsonify({"error": "Method not allowed"}), 405


@app.errorhandler(429)
def rate_limited(e):
    logger.warning(f"429 Rate Limited: {request.path}")
    return jsonify({"error": "Too many requests. Please slow down."}), 429


@app.errorhandler(500)
def internal_error(e):
    logger.error(f"500 Internal Server Error: {e}", exc_info=True)
    return jsonify({"error": "An internal error occurred. Please try again later."}), 500


@app.errorhandler(Exception)
def unhandled_exception(e):
    logger.error(f"Unhandled exception on {request.method} {request.path}: {e}", exc_info=True)
    try:
        db.session.rollback()
    except Exception:
        pass
    return jsonify({"error": "An unexpected error occurred."}), 500


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def is_valid_email(email: str) -> bool:
    return "@" in email and "." in email.split("@")[-1]


def is_valid_hex_color(color: str) -> bool:
    """Accepts 6-character hex strings (e.g. 'FF0000'). Case-insensitive."""
    if len(color) != 6:
        return False
    try:
        int(color, 16)
        return True
    except ValueError:
        return False


def parse_uuid(value: str, label: str):
    try:
        return uuid.UUID(value), None
    except (ValueError, AttributeError):
        logger.warning(f"Invalid UUID for {label}: {value!r}")
        return None, (jsonify({"error": f"Invalid {label} format"}), 400)


def require_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # ── Bearer token (cross-origin / file:// clients) ───────────────────
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            user_id = resolve_auth_token(token)
            if user_id:
                session["logged_in"] = True
                session["user_id"]   = str(user_id)
                return f(*args, **kwargs)
        # ── Cookie session fallback (same-origin / Render) ──────────────────
        if not session.get("logged_in"):
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return wrapper


def current_user():
    user_id, err = parse_uuid(session.get("user_id", ""), "user_id")
    if err:
        return None
    return db.session.get(User, user_id)


def db_commit(label: str):
    try:
        db.session.commit()
        return None
    except SQLAlchemyError as exc:
        db.session.rollback()
        logger.error(f"DB commit failed ({label}): {exc}", exc_info=True)
        return jsonify({"error": "Database error. Please try again."}), 500


def get_linked_note_ids(note_id) -> list[str]:
    rows = NoteLink.query.filter_by(source_note_id=note_id).all()
    return [str(row.target_note_id) for row in rows]


def note_to_json(note: "Note") -> dict:
    return {
        "id":            str(note.id),
        "title":         note.title,
        "ciphertext":    note.content,
        "iv":            note.iv,
        "salt":          note.salt,
        "category_id":   str(note.category_id) if note.category_id else None,
        "archived":      note.archived,
        "version":       note.version,
        "linked_note_ids": get_linked_note_ids(note.id),
        "created_at":    note.created_at.isoformat(),
        "updated_at":    note.updated_at.isoformat(),
    }


def set_note_links(note: "Note", linked_ids: list, user: "User"):
    """Replace outgoing links for a note. Returns an error response tuple or None."""
    if linked_ids is None:
        return None

    if not isinstance(linked_ids, list):
        return jsonify({"error": "linked_note_ids must be an array"}), 400

    if len(linked_ids) > MAX_NOTE_LINKS:
        return jsonify({"error": f"A note can link to at most {MAX_NOTE_LINKS} other notes"}), 400

    normalized: list[uuid.UUID] = []
    seen: set[str] = set()
    for raw_id in linked_ids:
        note_uuid, err = parse_uuid(str(raw_id), "linked_note_id")
        if err:
            return err
        if note_uuid == note.id:
            return jsonify({"error": "A note cannot link to itself"}), 400
        key = str(note_uuid)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(note_uuid)

    for target_uuid in normalized:
        target = db.session.get(Note, target_uuid)
        if not target or target.user_id != user.id:
            return jsonify({"error": f"Linked note {target_uuid} not found"}), 404
        if target.archived:
            return jsonify({"error": "Cannot link to an archived note"}), 409

    NoteLink.query.filter_by(source_note_id=note.id).delete()
    for target_uuid in normalized:
        db.session.add(NoteLink(source_note_id=note.id, target_note_id=target_uuid))
    return None


# ─────────────────────────────────────────────
# ROOT / HEALTH
# ─────────────────────────────────────────────

@app.route("/")
def home():
    return jsonify({"message": "InfoCord API running"})

@app.route('/app')
def frontend():
    with open('templates/index.html', 'r', encoding='utf-8') as f:
        content = f.read()
    return content, 200, {'Content-Type': 'text/html'}


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)


@app.route("/manifest.webmanifest")
def web_manifest():
    return send_from_directory("static", "manifest.webmanifest", mimetype="application/manifest+json")


@app.route("/legal/privacy")
def privacy_policy():
    return render_template("legal/privacy.html")


@app.route("/legal/terms")
def terms_of_service():
    return render_template("legal/terms.html")


def _probe_schema() -> dict:
    """Report Alembic revision and required tables (Gate A verification)."""
    migration_revision = None
    migration_ok = False
    try:
        migration_revision = db.session.execute(
            db.text("SELECT version_num FROM alembic_version LIMIT 1")
        ).scalar()
        migration_ok = migration_revision == EXPECTED_MIGRATION_REVISION
    except Exception:
        db.session.rollback()

    dialect = db.engine.dialect.name
    present: list[str] = []
    missing: list[str] = list(REQUIRED_SCHEMA_TABLES)

    try:
        if dialect == "sqlite":
            rows = db.session.execute(
                db.text("SELECT name FROM sqlite_master WHERE type='table'")
            ).scalars().all()
            present = [t for t in REQUIRED_SCHEMA_TABLES if t in rows]
        else:
            rows = db.session.execute(
                db.text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            ).scalars().all()
            present = [t for t in REQUIRED_SCHEMA_TABLES if t in rows]
        missing = [t for t in REQUIRED_SCHEMA_TABLES if t not in present]
    except Exception as exc:
        logger.warning(f"Schema table probe failed: {exc}")
        db.session.rollback()

    return {
        "db_host": _db_host_hint(),
        "migration_revision": migration_revision,
        "migration_expected": EXPECTED_MIGRATION_REVISION,
        "migration_ok": migration_ok,
        "schema_tables_present": present,
        "schema_tables_missing": missing,
        "schema_ok": len(missing) == 0,
    }


@app.route("/health")
def health():
    db_error_type = None
    db_error_hint = None
    try:
        db.session.execute(db.text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:
        logger.error(f"Health check DB probe failed: {exc}")
        db_status = "unavailable"
        db_error_type = type(exc).__name__
        db_error_hint = _safe_db_error_hint(exc)

    schema = _probe_schema() if db_status == "ok" else {}
    configured_host = _db_host_hint()

    status = "ok" if db_status == "ok" else "degraded"
    http_code = 200 if status == "ok" else 503
    payload = {
        "status": status,
        "db": db_status,
        **schema,
    }
    if db_status != "ok":
        payload["db_host_configured"] = configured_host
        payload["db_error_type"] = db_error_type
        payload["db_error_hint"] = db_error_hint
    return jsonify(payload), http_code


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

@app.route("/auth/signup", methods=["POST"])
@db_rate_limit((10, 3600))
def signup():
    """ Acquires the user's email, password, and name from the request body, and creates a new user in the database."""
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    email    = data.get("email", "").strip().lower()
    password = data.get("password", "")
    name     = data.get("name", "").strip()

    if not email or not password or not name:
        return jsonify({"error": "email, password, and name are required"}), 400

    if not is_valid_email(email):
        return jsonify({"error": "Invalid email format"}), 400

    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    if len(name) > 100:
        return jsonify({"error": "Name too long (max 100 characters)"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 409

    # --- Step 5: Generate Secure Recovery Key ---
    # 18 bytes raw data base64url encodes cleanly to 24 URL-safe characters
    raw_recovery_key = secrets.token_urlsafe(18)[:24]
    recovery_hash = generate_password_hash(raw_recovery_key)

    user = User(
        email=email,
        password_hash=generate_password_hash(password),
        name=name,
        recovery_key_hash=recovery_hash
    )
    db.session.add(user)

    if (err := db_commit("signup")):
        return err

    logger.info(f"New user registered: {email}")
    return jsonify({
        "message": "Account created successfully",
        "user": {"id": str(user.id), "email": user.email, "name": user.name},
        "recovery_key": raw_recovery_key  # Returned ONLY once
    }), 201


@app.route("/auth/login", methods=["POST"])
@db_rate_limit((5, 60), (20, 3600))
def login():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    email    = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    user = User.query.filter_by(email=email).first() # is this like some semantic search?

    if user and user.locked_until and datetime.now() < user.locked_until:
        logger.warning(f"Login attempt on locked account: {email}")
        return jsonify({"error": "Account temporarily locked. Try again later."}), 423

    if not user or not check_password_hash(user.password_hash, password): # why are we checking the password hash? because the password is hashed before being stored in the database
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = datetime.now() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                user.failed_login_attempts = 0
                logger.warning(f"Account locked after failed attempts: {email}")
            db.session.commit()
        logger.warning(f"Failed login attempt for: {email}")
        return jsonify({"error": "Invalid email or password"}), 401

    user.failed_login_attempts = 0
    user.locked_until = None

    if (err := db_commit("login")):
        return err

    session.permanent = True
    session["logged_in"] = True
    session["user_id"]   = str(user.id)

    # Also issue a Bearer token so cross-origin (file://) clients can
    # authenticate without relying on SameSite cookies.
    bearer_token = create_auth_token(user.id)

    logger.info(f"User logged in: {email}")
    return jsonify({
        "message": "Login successful",
        "user":    {"id": str(user.id), "email": user.email, "name": user.name},
        "token":   bearer_token,
    }), 200


@app.route("/auth/logout", methods=["POST"])
@require_login
def logout():
    user = current_user()
    logger.info(f"User logged out: {user.email if user else 'unknown'}")
    # Revoke Bearer token if present
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        revoke_auth_token(auth_header[7:])
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200


@app.route("/auth/me", methods=["GET"])
@require_login
def me(): # why'd we call this me? because it is the user's own information
    """ Returns the user's own information."""
    user = current_user()
    if not user:
        logger.warning(f"Session references deleted user: {session.get('user_id')}")
        session.clear()
        return jsonify({"error": "User account not found"}), 404

    return jsonify({"id": str(user.id), "email": user.email, "name": user.name})

@app.route("/auth/recover", methods=["POST"])
@db_rate_limit((5, 3600))
def recover_account():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    email        = data.get("email", "").strip().lower()
    recovery_key = data.get("recovery_key", "").strip() # recovery key is the key used to recover the account
    new_password = data.get("new_password", "")

    if not email or not recovery_key or not new_password:
        return jsonify({"error": "email, recovery_key, and new_password are required"}), 400

    if len(new_password) < 8:
        return jsonify({"error": "New password must be at least 8 characters"}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.recovery_key_hash:
        # Generic response to prevent user enumeration
        return jsonify({"error": "Invalid email or recovery key"}), 401

    if user.locked_until and datetime.now() < user.locked_until:
        return jsonify({"error": "Account temporarily locked. Try again later."}), 423

    if not check_password_hash(user.recovery_key_hash, recovery_key):  # why are we checking the recovery key hash? because the recovery key is hashed before being stored in the database
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = datetime.now() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            user.failed_login_attempts = 0
            logger.warning(f"Account locked via failed recovery: {email}")
        db.session.commit()
        return jsonify({"error": "Invalid email or recovery key"}), 401

    # Reset credentials and INVALIDATE the recovery key (one-time use)
    user.password_hash        = generate_password_hash(new_password)
    user.recovery_key_hash    = None   # consumed — must regenerate to get a new one
    user.failed_login_attempts = 0
    user.locked_until          = None

    if (err := db_commit("recover_account")):
        return err

    logger.info(f"Account credentials recovered via key: {email}")
    return jsonify({"message": "Password reset successful. You can now login with your new password."}), 200

@app.route("/auth/change-password", methods=["POST"])
@require_login
def change_password():
    user = current_user()
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")
    reencrypted_notes = data.get("notes", [])  # Expects list of { id, version, ciphertext, iv, salt }

    if not old_password or not new_password:
        return jsonify({"error": "old_password and new_password are required"}), 400

    if len(new_password) < 8:
        return jsonify({"error": "New password must be at least 8 characters"}), 400

    if not check_password_hash(user.password_hash, old_password):
        return jsonify({"error": "Invalid current password"}), 401

    # Atomically process notes to ensure zero state divergence 
    for item in reencrypted_notes:
        note_id = item.get("id")
        client_version = item.get("version")
        ciphertext = item.get("ciphertext") # note encryption
        iv = item.get("iv") # initialization
        salt = item.get("salt") # Secures encryption for the note? yes. 

        if not all([note_id, client_version, ciphertext, iv, salt]): # what is this? a check to ensure the note is not malformed
            return jsonify({"error": "Malformed note structures inside package payload"}), 400

        note_uuid, err = parse_uuid(note_id, "note_id") # checks if the note id is valid
        if err:
            return err

        note = db.session.get(Note, note_uuid)
        if not note or note.user_id != user.id:
            return jsonify({"error": f"Note {note_id} not found"}), 404

        # Mitigate concurrent write race-conditions during the migration batch
        if client_version != note.version:
            db.session.rollback()
            return jsonify({
                "error": "Version conflict during password alteration migration",
                "detail": f"Note {note_id} was altered mid-flight. Fetch latest changes and retry sequence.",
            }), 409

        note.content = ciphertext
        note.iv = iv
        note.salt = salt
        note.version += 1
        note.last_modified = datetime.now()

    # Update to new password 
    user.password_hash = generate_password_hash(new_password)

    if (err := db_commit("change_password_batch")):
        return err

    logger.info(f"Password changed and E2EE keys cycled for user: {user.email}")
    return jsonify({"message": "Password changed and notes re-encrypted successfully."}), 200

@app.route("/auth/recovery-key", methods=["POST"])
@require_login
def regenerate_recovery_key():
    """
    Generates a fresh recovery key for the current user.
    The old key is immediately invalidated.
    The plaintext key is returned exactly once — only the hash is stored.
    """
    user = current_user()
    if not user:
        return jsonify({"error": "User not found"}), 404

    raw_recovery_key      = secrets.token_urlsafe(18)[:24] # why is this random? because we need a unique recovery key for each user
    user.recovery_key_hash = generate_password_hash(raw_recovery_key) # give recovery key a hash

    if (err := db_commit("regenerate_recovery_key")):
        return err

    logger.info(f"Recovery key regenerated for user: {user.email}")
    return jsonify({
        "recovery_key": raw_recovery_key,
        "message":      "Store this key somewhere safe. It will not be shown again."
    }), 200


@app.route("/auth/account", methods=["DELETE"])
@require_login
def delete_account():
    """Permanently delete the authenticated user's account and all associated data."""
    user = current_user()
    if not user:
        return jsonify({"error": "User account not found"}), 404

    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if not password:
        return jsonify({"error": "password is required to confirm account deletion"}), 400

    if not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid password"}), 401

    email = user.email
    user_id = user.id

    note_ids = [row.id for row in Note.query.filter_by(user_id=user_id).all()]
    if note_ids:
        NoteLink.query.filter(
            db.or_(
                NoteLink.source_note_id.in_(note_ids),
                NoteLink.target_note_id.in_(note_ids),
            )
        ).delete(synchronize_session=False)
        Note.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    Category.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    AuthToken.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    db.session.delete(user)

    if (err := db_commit("delete_account")):
        return err

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        revoke_auth_token(auth_header[7:])
    session.clear()

    logger.info(f"Account deleted: {email}")
    return jsonify({"message": "Account and all associated data have been permanently deleted."}), 200


# ─────────────────────────────────────────────
# CATEGORY CRUD
# ─────────────────────────────────────────────

@app.route("/categories", methods=["POST"])
@require_login
def create_category():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    name  = data.get("name", "").strip()
    color = data.get("color", "").strip().lstrip("#").upper()

    if not name or not color:
        return jsonify({"error": "name and color are required"}), 400

    if len(name) > MAX_CATEGORY_NAME:
        return jsonify({"error": f"Category name too long (max {MAX_CATEGORY_NAME} characters)"}), 400

    if not is_valid_hex_color(color):
        return jsonify({"error": "color must be a 6-character hex value (e.g. FF0000 or #FF0000)"}), 400

    category = Category(user_id=current_user().id, name=name, color=color)
    db.session.add(category)

    if (err := db_commit("create_category")):
        return err

    logger.info(f"Category created: {name!r} for user {current_user().id}")
    return jsonify({"id": str(category.id), "name": category.name, "color": category.color}), 201


@app.route("/categories", methods=["GET"])
@require_login
def get_categories():
    categories = Category.query.filter_by(user_id=current_user().id).all()
    return jsonify([
        {"id": str(c.id), "name": c.name, "color": c.color, "archived": c.archived}
        for c in categories
    ])


@app.route("/categories/<category_id>", methods=["PUT"])
@require_login
def update_category(category_id):
    """ Updates a category."""
    cat_uuid, err = parse_uuid(category_id, "category_id")
    if err:
        return err

    category = db.session.get(Category, cat_uuid)
    if not category or category.user_id != current_user().id:
        return jsonify({"error": "Category not found"}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    if "name" in data:
        name = str(data["name"]).strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400
        if len(name) > MAX_CATEGORY_NAME:
            return jsonify({"error": f"Category name too long (max {MAX_CATEGORY_NAME} characters)"}), 400
        category.name = name

    if "color" in data:
        color = str(data["color"]).strip().lstrip("#").upper()
        if not is_valid_hex_color(color):
            return jsonify({"error": "color must be a 6-character hex value (e.g. FF0000 or #FF0000)"}), 400
        category.color = color

    if (err := db_commit("update_category")):
        return err

    return jsonify({"message": "Category updated"})


@app.route("/categories/<category_id>/archive", methods=["PATCH"])
@require_login
def archive_category(category_id):
    cat_uuid, err = parse_uuid(category_id, "category_id")
    if err:
        return err

    category = db.session.get(Category, cat_uuid)
    if not category or category.user_id != current_user().id:
        return jsonify({"error": "Category not found"}), 404

    if category.archived:
        return jsonify({"error": "Category is already archived", "detail": "Category is already archived"}), 409

    category.archived = True

    if (err := db_commit("archive_category")):
        return err

    logger.info(f"Category archived: {category.id}")
    return jsonify({"message": "Category archived"})


# ─────────────────────────────────────────────
# NOTE CRUD
# ─────────────────────────────────────────────

@app.route("/notes", methods=["POST"])
@require_login
def create_note():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    category_id = data.get("category_id") or None   # treat empty string as None
    ciphertext  = data.get("ciphertext", "")
    iv          = data.get("iv", "")
    salt        = data.get("salt", "")
    title       = data.get("title", "")

    if not ciphertext or not iv or not salt:
        return jsonify({"error": "ciphertext, iv, and salt are required"}), 400

    if not isinstance(ciphertext, str):
        return jsonify({"error": "ciphertext must be a string"}), 400

    if len(ciphertext) > MAX_NOTE_LENGTH * 2:  # ciphertext is larger than plaintext
        return jsonify({"error": "Note content too large"}), 400

    # Validate and authorise the category only when one was supplied
    resolved_cat_id = None
    if category_id:
        cat_uuid, err = parse_uuid(category_id, "category_id")
        if err:
            return err
        category = db.session.get(Category, cat_uuid)
        if not category or category.user_id != current_user().id:
            return jsonify({"error": "Category not found"}), 404
        if category.archived:
            return jsonify({"error": "Cannot add notes to an archived category"}), 409
        resolved_cat_id = category.id

    note = Note(
        user_id     = current_user().id,
        category_id = resolved_cat_id,
        content     = ciphertext,
        iv          = iv,
        salt        = salt,
        title       = title,
        version     = 1,
    )
    db.session.add(note)
    db.session.flush()

    if (link_err := set_note_links(note, data.get("linked_note_ids"), current_user())):
        db.session.rollback()
        return link_err

    if (err := db_commit("create_note")):
        return err

    if resolved_cat_id:
        logger.info(f"Note created: {note.id} in category {resolved_cat_id}")
    else:
        logger.info(f"Note created: {note.id} (no folder)")
    return jsonify({"id": str(note.id), "version": note.version}), 201


@app.route("/notes", methods=["GET"])
@require_login
def get_notes():
    notes = Note.query.filter_by(user_id=current_user().id).all()
    return jsonify([note_to_json(n) for n in notes])


@app.route("/notes/<note_id>", methods=["GET"])
@require_login
def get_note(note_id):
    note_uuid, err = parse_uuid(note_id, "note_id")
    if err:
        return err

    note = db.session.get(Note, note_uuid)
    if not note or note.user_id != current_user().id:
        return jsonify({"error": "Note not found"}), 404

    return jsonify(note_to_json(note))


@app.route("/notes/<note_id>", methods=["PUT"])
@require_login
def update_note(note_id):
    note_uuid, err = parse_uuid(note_id, "note_id")
    if err:
        return err

    note = db.session.get(Note, note_uuid)
    if not note or note.user_id != current_user().id:
        return jsonify({"error": "Note not found"}), 404

    if note.archived:
        return jsonify({"error": "Cannot update an archived note"}), 409

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    ciphertext = data.get("ciphertext", "")
    iv         = data.get("iv", "")
    salt       = data.get("salt", "")
    title      = data.get("title", note.title)

    if not ciphertext or not iv or not salt:
        return jsonify({"error": "ciphertext, iv, and salt are required"}), 400

    if not isinstance(ciphertext, str):
        return jsonify({"error": "ciphertext must be a string"}), 400

    if len(ciphertext) > MAX_NOTE_LENGTH * 2:
        return jsonify({"error": "Note content too large"}), 400

    client_version = data.get("version") # is this recording the actual text version of the note?

    if client_version is None:
        return jsonify({"error": "version is required"}), 400

    if not isinstance(client_version, int):
        return jsonify({"error": "version must be an integer"}), 400

    if client_version != note.version:
        logger.info(
            f"Version conflict on note {note.id}: "
            f"client={client_version}, server={note.version}"
        )
        return jsonify({
            "error":          "Version conflict",
            "detail":         "This note was modified elsewhere. Fetch the latest version and retry.",
            "server_version": note.version
        }), 409

    if "category_id" in data:
        category_id = data.get("category_id") or None
        if category_id:
            cat_uuid, err = parse_uuid(category_id, "category_id")
            if err:
                return err
            category = db.session.get(Category, cat_uuid)
            if not category or category.user_id != current_user().id:
                return jsonify({"error": "Category not found"}), 404
            if category.archived:
                return jsonify({"error": "Cannot add notes to an archived category"}), 409
            note.category_id = category.id
        else:
            note.category_id = None

    if "linked_note_ids" in data:
        if (link_err := set_note_links(note, data.get("linked_note_ids"), current_user())):
            return link_err

    note.content       = ciphertext
    note.iv            = iv
    note.salt          = salt
    note.title         = title
    note.last_modified = datetime.now()
    note.version      += 1

    if (err := db_commit("update_note")):
        return err

    logger.info(f"Note updated: {note.id} → version {note.version}")
    return jsonify({"message": "Note updated", "version": note.version})


@app.route("/notes/<note_id>/archive", methods=["PATCH"])
@require_login
def archive_note(note_id):
    note_uuid, err = parse_uuid(note_id, "note_id")
    if err:
        return err

    note = db.session.get(Note, note_uuid)
    if not note or note.user_id != current_user().id:
        return jsonify({"error": "Note not found"}), 404

    if note.archived:
        return jsonify({"error": "Note is already archived"}), 409

    note.archived = True

    if (err := db_commit("archive_note")):
        return err

    logger.info(f"Note archived: {note.id}")
    return jsonify({"message": "Note archived"})


@app.route("/notes/<note_id>/unarchive", methods=["PATCH"])
@require_login
def unarchive_note(note_id):
    note_uuid, err = parse_uuid(note_id, "note_id")
    if err:
        return err

    note = db.session.get(Note, note_uuid)
    if not note or note.user_id != current_user().id:
        return jsonify({"error": "Note not found"}), 404

    if not note.archived:
        return jsonify({"error": "Note is not archived"}), 409

    note.archived = False

    if (err := db_commit("unarchive_note")):
        return err

    logger.info(f"Note unarchived: {note.id}")
    return jsonify({"message": "Note unarchived"})


# ─────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────

class User(db.Model):
    __tablename__ = 'users'

    id            = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email         = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name          = db.Column(db.String(100), nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.now)

    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until          = db.Column(db.DateTime)
    
    # --- New Field for Step 5 ---
    recovery_key_hash     = db.Column(db.String(255), nullable=True)

class Category(db.Model):
    __tablename__ = 'categories'

    id         = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'))
    name       = db.Column(db.String(120), nullable=False)
    color      = db.Column(db.String(6),   nullable=False)
    archived   = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)


class Note(db.Model):
    __tablename__ = 'notes'

    id            = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'))
    category_id   = db.Column(UUID(as_uuid=True), db.ForeignKey('categories.id'))
    title         = db.Column(db.String(255))
    content       = db.Column(db.Text)        # base64 ciphertext — never plaintext
    iv            = db.Column(db.String(64))  # base64 IV/nonce
    salt          = db.Column(db.String(64))  # base64 PBKDF2 salt
    created_at    = db.Column(db.DateTime, default=datetime.now)
    updated_at    = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    archived      = db.Column(db.Boolean, default=False)
    last_modified = db.Column(db.DateTime, default=datetime.now)
    version       = db.Column(db.Integer, default=1, nullable=False)


class NoteLink(db.Model):
    __tablename__ = 'note_links'

    source_note_id = db.Column(UUID(as_uuid=True), db.ForeignKey('notes.id', ondelete='CASCADE'), primary_key=True)
    target_note_id = db.Column(UUID(as_uuid=True), db.ForeignKey('notes.id', ondelete='CASCADE'), primary_key=True)


class AuthToken(db.Model):
    """Bearer tokens: only HMAC-SHA256 hashes persisted; plaintext exists client-side only."""
    __tablename__ = 'auth_tokens'

    token_hash = db.Column(db.String(64), primary_key=True)  # HMAC-SHA256 hex digest
    user_id    = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class RateLimitBucket(db.Model):
    __tablename__ = 'rate_limit_buckets'

    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    bucket_key   = db.Column(db.String(255), nullable=False, index=True)
    window_start = db.Column(db.DateTime, nullable=False)
    count        = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint('bucket_key', 'window_start', name='uq_rate_limit_bucket_window'),
    )


if __name__ == "__main__":
    app.run(debug=True)