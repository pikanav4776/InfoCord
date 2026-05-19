import os
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy.dialects.postgresql import UUID
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash

from dotenv import load_dotenv

# ── Import encryption helpers ─────────────────────────────────────────────────
from crypto_utils import encrypt_note, decrypt_note

load_dotenv()

DB_PORT = os.getenv("DB_PORT")
DB_username = os.getenv("DB_username")
DB_password = os.getenv("DB_password")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")

MAX_NOTE_LENGTH = 10000
MAX_CATEGORY_NAME = 120

app = Flask(__name__)

app.config['SECRET_KEY'] = FLASK_SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'TEST_DATABASE_URI',
    f'postgresql+psycopg2://{DB_username}:{DB_password}@localhost:{DB_PORT}/infocord_mvp'
)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = os.getenv("FLASK_ENV") == "production"
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config["RATELIMIT_ENABLED"] = False

db = SQLAlchemy()
migrate = Migrate()

db.init_app(app)
migrate.init_app(app, db)

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://"
)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def is_valid_email(email: str) -> bool:
    return "@" in email and "." in email.split("@")[-1]


def require_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return wrapper


def current_user():
    return db.session.get(User, uuid.UUID(session["user_id"]))


# ─────────────────────────────────────────────
# ROOT
# ─────────────────────────────────────────────

@app.route("/")
def home():
    return {"message": "InfoCord API running"}


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

@app.route("/auth/signup", methods=["POST"])
@limiter.limit("10 per hour")
def signup():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    name = data.get("name", "").strip()

    if not email or not password or not name:
        return jsonify({"error": "email, password, and name are required"}), 400

    if not is_valid_email(email):
        return jsonify({"error": "Invalid email format"}), 400

    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    if len(name) > 100:
        return jsonify({"error": "Name too long"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already exists"}), 409

    user = User(
        email=email,
        password_hash=generate_password_hash(password),
        name=name
    )

    db.session.add(user)
    db.session.commit()

    return jsonify({
        "message": "Account created successfully",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name
        }
    }), 201


@app.route("/auth/login", methods=["POST"])
@limiter.limit("20 per hour; 5 per minute")
def login():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "email and password required"}), 400

    user = User.query.filter_by(email=email).first()

    if user and user.locked_until and datetime.now() < user.locked_until:
        return jsonify({"error": "Account temporarily locked"}), 423

    if not user or not check_password_hash(user.password_hash, password):
        if user:
            user.failed_login_attempts += 1

            if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = datetime.now() + timedelta(
                    minutes=LOCKOUT_DURATION_MINUTES
                )
                user.failed_login_attempts = 0

            db.session.commit()

        return jsonify({"error": "Invalid email or password"}), 401

    user.failed_login_attempts = 0
    user.locked_until = None
    db.session.commit()

    session.permanent = True
    session["logged_in"] = True
    session["user_id"] = str(user.id)

    return jsonify({
        "message": "Login successful",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name
        }
    }), 200


@app.route("/auth/logout", methods=["POST"])
@require_login
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200


@app.route("/auth/me", methods=["GET"])
@require_login
def me():
    user = current_user()

    if not user:
        session.clear()
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "id": str(user.id),
        "email": user.email,
        "name": user.name
    })


# ─────────────────────────────────────────────
# CATEGORY CRUD
# ─────────────────────────────────────────────

@app.route("/categories", methods=["POST"])
@require_login
def create_category():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "JSON required"}), 400

    name = data.get("name", "").strip()
    color = data.get("color", "").strip()

    if not name or not color:
        return jsonify({"error": "name and color required"}), 400

    if len(name) > MAX_CATEGORY_NAME:
        return jsonify({"error": "Category name too long"}), 400

    category = Category(
        user_id=current_user().id,
        name=name,
        color=color
    )

    db.session.add(category)
    db.session.commit()

    return jsonify({
        "id": str(category.id),
        "name": category.name,
        "color": category.color
    }), 201


@app.route("/categories", methods=["GET"])
@require_login
def get_categories():
    categories = Category.query.filter_by(
        user_id=current_user().id
    ).all()

    return jsonify([
        {
            "id": str(c.id),
            "name": c.name,
            "color": c.color,
            "archived": c.archived
        }
        for c in categories
    ])


@app.route("/categories/<category_id>", methods=["PUT"])
@require_login
def update_category(category_id):
    category = db.session.get(Category, uuid.UUID(category_id))

    if not category or category.user_id != current_user().id:
        return jsonify({"error": "Category not found"}), 404

    data = request.get_json(silent=True)

    if "name" in data:
        category.name = data["name"]

    if "color" in data:
        category.color = data["color"]

    db.session.commit()

    return jsonify({"message": "Category updated"})


@app.route("/categories/<category_id>/archive", methods=["PATCH"])
@require_login
def archive_category(category_id):
    category = db.session.get(Category, uuid.UUID(category_id))

    if not category or category.user_id != current_user().id:
        return jsonify({"error": "Category not found"}), 404

    category.archived = True
    db.session.commit()

    return jsonify({"message": "Category archived"})


# ─────────────────────────────────────────────
# NOTE CRUD
# ─────────────────────────────────────────────

@app.route("/notes", methods=["POST"])
@require_login
def create_note():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "JSON required"}), 400

    category_id = data.get("category_id")
    content = data.get("content", "")

    if not category_id:
        return jsonify({"error": "category_id required"}), 400

    if len(content) > MAX_NOTE_LENGTH:
        return jsonify({"error": "Note exceeds 10,000 characters"}), 400

    category = db.session.get(Category, uuid.UUID(category_id))

    if not category or category.user_id != current_user().id:
        return jsonify({"error": "Invalid category"}), 404

    # ── Encrypt before saving — plaintext never touches the DB ────────────────
    try:
        ciphertext, iv = encrypt_note(content)
    except EnvironmentError:
        return jsonify({"error": "Encryption configuration error"}), 500

    note = Note(
        user_id=current_user().id,
        category_id=category.id,
        content=ciphertext,   # base64 ciphertext
        iv=iv                 # base64 IV/nonce
    )

    db.session.add(note)
    db.session.commit()

    return jsonify({
        "id": str(note.id),
        # Return the original plaintext back to the caller (they just sent it)
        "content": content,
        "version": note.version
    }), 201


@app.route("/notes", methods=["GET"])
@require_login
def get_notes():
    notes = Note.query.filter_by(user_id=current_user().id).all()

    result = []
    for n in notes:
        # ── Decrypt each note before returning ────────────────────────────────
        try:
            plaintext = decrypt_note(n.content, n.iv)
        except (ValueError, EnvironmentError):
            # A single corrupted/tampered note should not crash the whole list.
            # Log server-side; return a safe sentinel to the client.
            app.logger.error(
                f"Failed to decrypt note {n.id} for user {n.user_id}. "
                "Possible tampering or key mismatch."
            )
            plaintext = "[Note could not be decrypted]"

        result.append({
            "id": str(n.id),
            "content": plaintext,       # decrypted plaintext
            "category_id": str(n.category_id),
            "archived": n.archived,
            "version": n.version
        })

    return jsonify(result)


@app.route("/notes/<note_id>", methods=["PUT"])
@require_login
def update_note(note_id):
    note = db.session.get(Note, uuid.UUID(note_id))

    if not note or note.user_id != current_user().id:
        return jsonify({"error": "Note not found"}), 404

    data = request.get_json(silent=True)
    content = data.get("content", "")

    if len(content) > MAX_NOTE_LENGTH:
        return jsonify({"error": "Note exceeds 10,000 characters"}), 400

    # ── Phase 5: Version conflict detection ───────────────────────────────────
    # The client must send the version it last saw. If another update has
    # landed since then, the server's version will be higher — reject with 409
    # so the client can fetch the latest content and resolve the conflict.
    client_version = data.get("version")

    if client_version is None:
        return jsonify({"error": "version is required"}), 400

    if not isinstance(client_version, int):
        return jsonify({"error": "version must be an integer"}), 400

    if client_version != note.version:
        return jsonify({
            "error": "Version conflict",
            "detail": "This note was modified elsewhere. Fetch the latest version and retry.",
            "server_version": note.version
        }), 409

    # ── Re-encrypt with a fresh IV on every update ────────────────────────────
    try:
        ciphertext, iv = encrypt_note(content)
    except EnvironmentError:
        return jsonify({"error": "Encryption configuration error"}), 500

    note.content = ciphertext
    note.iv = iv
    note.last_modified = datetime.now()
    note.version += 1          # increment — next update must send this new value

    db.session.commit()

    return jsonify({"message": "Note updated", "version": note.version})


@app.route("/notes/<note_id>/archive", methods=["PATCH"])
@require_login
def archive_note(note_id):
    note = db.session.get(Note, uuid.UUID(note_id))

    if not note or note.user_id != current_user().id:
        return jsonify({"error": "Note not found"}), 404

    note.archived = True
    db.session.commit()

    return jsonify({"message": "Note archived"})


# ─────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)


class Category(db.Model):
    __tablename__ = 'categories'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'))
    name = db.Column(db.String(120), nullable=False)
    color = db.Column(db.String(6), nullable=False)
    archived = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)


class Note(db.Model):
    __tablename__ = 'notes'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'))
    category_id = db.Column(UUID(as_uuid=True), db.ForeignKey('categories.id'))
    content = db.Column(db.Text)          # stores base64 ciphertext (never plaintext)
    iv = db.Column(db.String(64))         # stores base64 IV/nonce
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.now,
        onupdate=datetime.now
    )
    archived = db.Column(db.Boolean, default=False)
    last_modified = db.Column(db.DateTime, default=datetime.now)
    version = db.Column(db.Integer, default=1, nullable=False)
    # version increments on every successful update.
    # Clients must send back the version they last saw; if it doesn't match
    # the server's current version, the update is rejected (HTTP 409 Conflict).


if __name__ == "__main__":
    app.run(debug=True)