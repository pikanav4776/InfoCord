import logging
import os
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, session, g
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import SQLAlchemyError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash

from dotenv import load_dotenv

load_dotenv()

DB_PORT          = os.getenv("DB_PORT")
DB_username      = os.getenv("DB_username")
DB_password      = os.getenv("DB_password")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
DATABASE_URL     = os.getenv("DATABASE_URL")

MAX_NOTE_LENGTH           = 10000
MAX_CATEGORY_NAME         = 120
MAX_FAILED_ATTEMPTS       = 5
LOCKOUT_DURATION_MINUTES  = 15

app = Flask(__name__)

app.config['SECRET_KEY']                  = FLASK_SECRET_KEY
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY']     = True
app.config['SESSION_COOKIE_SECURE']       = os.getenv("FLASK_ENV") == "production"
app.config['SESSION_COOKIE_SAMESITE']     = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME']  = timedelta(days=7)
app.config["RATELIMIT_ENABLED"]           = os.getenv("FLASK_ENV") == "production"


def normalize_db_url(url: str) -> str:
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url and url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


app.config['SQLALCHEMY_DATABASE_URI'] = (
    os.getenv('TEST_DATABASE_URI')
    or normalize_db_url(DATABASE_URL)
    or f'postgresql+psycopg2://{DB_username}:{DB_password}@localhost:{DB_PORT}/infocord_mvp'
)


# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

def _configure_logging() -> None:
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
migrate = Migrate()

db.init_app(app)
migrate.init_app(app, db)

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://"
)


# ─────────────────────────────────────────────
# REQUEST LIFECYCLE HOOKS
# ─────────────────────────────────────────────

@app.before_request
def _before_request() -> None:
    g.request_id = str(uuid.uuid4())[:8]
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


# ─────────────────────────────────────────────
# ROOT / HEALTH
# ─────────────────────────────────────────────

@app.route("/")
def home():
    return jsonify({"message": "InfoCord API running"})


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

    user = User(
        email=email,
        password_hash=generate_password_hash(password),
        name=name
    )
    db.session.add(user)

    if (err := db_commit("signup")):
        return err

    logger.info(f"New user registered: {email}")
    return jsonify({
        "message": "Account created successfully",
        "user": {"id": str(user.id), "email": user.email, "name": user.name}
    }), 201


@app.route("/auth/login", methods=["POST"])
@limiter.limit("20 per hour; 5 per minute")
def login():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    email    = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    user = User.query.filter_by(email=email).first()

    if user and user.locked_until and datetime.now() < user.locked_until:
        logger.warning(f"Login attempt on locked account: {email}")
        return jsonify({"error": "Account temporarily locked. Try again later."}), 423

    if not user or not check_password_hash(user.password_hash, password):
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

    logger.info(f"User logged in: {email}")
    return jsonify({
        "message": "Login successful",
        "user": {"id": str(user.id), "email": user.email, "name": user.name}
    }), 200


@app.route("/auth/logout", methods=["POST"])
@require_login
def logout():
    user = current_user()
    logger.info(f"User logged out: {user.email if user else 'unknown'}")
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200


@app.route("/auth/me", methods=["GET"])
@require_login
def me():
    user = current_user()
    if not user:
        logger.warning(f"Session references deleted user: {session.get('user_id')}")
        session.clear()
        return jsonify({"error": "User account not found"}), 404

    return jsonify({"id": str(user.id), "email": user.email, "name": user.name})


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
        return jsonify({"error": "Category is already archived"}), 409

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

    category_id = data.get("category_id")
    ciphertext  = data.get("ciphertext", "")
    iv          = data.get("iv", "")
    salt        = data.get("salt", "")
    title       = data.get("title", "")

    if not category_id:
        return jsonify({"error": "category_id is required"}), 400

    if not ciphertext or not iv or not salt:
        return jsonify({"error": "ciphertext, iv, and salt are required"}), 400

    if not isinstance(ciphertext, str):
        return jsonify({"error": "ciphertext must be a string"}), 400

    if len(ciphertext) > MAX_NOTE_LENGTH * 2:  # ciphertext is larger than plaintext
        return jsonify({"error": "Note content too large"}), 400

    cat_uuid, err = parse_uuid(category_id, "category_id")
    if err:
        return err

    category = db.session.get(Category, cat_uuid)
    if not category or category.user_id != current_user().id:
        return jsonify({"error": "Category not found"}), 404

    if category.archived:
        return jsonify({"error": "Cannot add notes to an archived category"}), 409

    note = Note(
        user_id     = current_user().id,
        category_id = category.id,
        content     = ciphertext,
        iv          = iv,
        salt        = salt,
        title       = title,
        version     = 1,
    )
    db.session.add(note)

    if (err := db_commit("create_note")):
        return err

    logger.info(f"Note created: {note.id} in category {category.id}")
    return jsonify({"id": str(note.id), "version": note.version}), 201


@app.route("/notes", methods=["GET"])
@require_login
def get_notes():
    notes  = Note.query.filter_by(user_id=current_user().id).all()
    result = []

    for n in notes:
        result.append({
            "id":          str(n.id),
            "title":       n.title,
            "ciphertext":  n.content,
            "iv":          n.iv,
            "salt":        n.salt,
            "category_id": str(n.category_id) if n.category_id else None,
            "archived":    n.archived,
            "version":     n.version,
            "created_at":  n.created_at.isoformat(),
            "updated_at":  n.updated_at.isoformat(),
        })

    return jsonify(result)


@app.route("/notes/<note_id>", methods=["GET"])
@require_login
def get_note(note_id):
    note_uuid, err = parse_uuid(note_id, "note_id")
    if err:
        return err

    note = db.session.get(Note, note_uuid)
    if not note or note.user_id != current_user().id:
        return jsonify({"error": "Note not found"}), 404

    return jsonify({
        "id":          str(note.id),
        "title":       note.title,
        "ciphertext":  note.content,
        "iv":          note.iv,
        "salt":        note.salt,
        "category_id": str(note.category_id) if note.category_id else None,
        "archived":    note.archived,
        "version":     note.version,
        "created_at":  note.created_at.isoformat(),
        "updated_at":  note.updated_at.isoformat(),
    })


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

    client_version = data.get("version")

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


if __name__ == "__main__":
    app.run(debug=True)