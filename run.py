import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from functools import wraps
import secrets

# ── In-memory session tokens (Bearer auth) ────────────────────────────────────
# Lets the browser send an Authorization: Bearer <token> header instead of
# relying on SameSite=Lax cookies, which are blocked on cross-origin POST
# requests (e.g. when the HTML is opened from file:// or a different port).
_active_tokens: dict = {}   # token_str → user_id_str

from flask import Flask, request, jsonify, session, g, render_template, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import SQLAlchemyError
from flask_limiter import Limiter
from werkzeug.security import generate_password_hash, check_password_hash

from dotenv import load_dotenv
from flask_cors import CORS


load_dotenv() 

# authentication information
DB_PORT          = os.getenv("DB_PORT")
DB_username      = os.getenv("DB_username")
DB_password      = os.getenv("DB_password")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
DATABASE_URL     = os.getenv("DATABASE_URL")

MAX_NOTE_LENGTH           = 10000
MAX_CATEGORY_NAME         = 120
MAX_NOTE_LINKS            = 10
MAX_FAILED_ATTEMPTS       = 5
LOCKOUT_DURATION_MINUTES  = 15

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
app.config['PERMANENT_SESSION_LIFETIME']  = timedelta(days=7)
app.config["RATELIMIT_ENABLED"]           = os.getenv("FLASK_ENV") == "production" # 


def normalize_db_url(url: str) -> str:
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url and url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


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
# DB / MIGRATE / LIMITER
# ─────────────────────────────────────────────

db      = SQLAlchemy()
migrate = Migrate() # what does migrate do? it is used to migrate the database to the latest version

db.init_app(app)
migrate.init_app(app, db)

def rate_limit_key() -> str:
    """Rate-limit by account identity — never by client IP."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        user_id_str = _active_tokens.get(auth_header[7:])
        if user_id_str:
            return f"user:{user_id_str}"
    if session.get("logged_in") and session.get("user_id"):
        return f"user:{session['user_id']}"
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if email:
        return f"email:{email}"
    return "anon"


limiter = Limiter(
    key_func=rate_limit_key,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


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
            user_id_str = _active_tokens.get(token)
            if user_id_str:
                # Populate session so current_user() keeps working unchanged
                session["logged_in"] = True
                session["user_id"]   = user_id_str
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


@app.route("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:
        logger.error(f"Health check DB probe failed: {exc}")
        db_status = "unavailable"

    status = "ok" if db_status == "ok" else "degraded"
    http_code = 200 if status == "ok" else 503
    return jsonify({"status": status, "db": db_status}), http_code


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

@app.route("/auth/signup", methods=["POST"])
@limiter.limit("10 per hour")
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
@limiter.limit("20 per hour; 5 per minute") # why did we set these limits? to prevent brute force attacks
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
    bearer_token = secrets.token_urlsafe(32) # what is this? a token for the user to authenticate with
    _active_tokens[bearer_token] = str(user.id) # what is this? a dictionary to store the user's token

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
        _active_tokens.pop(auth_header[7:], None)
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
@limiter.limit("5 per hour")
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


if __name__ == "__main__":
    app.run(debug=True)