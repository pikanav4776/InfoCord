import os
import uuid
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import UUID
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash

from dotenv import load_dotenv

load_dotenv()

DB_PORT = os.getenv("DB_PORT")
DB_username = os.getenv("DB_username")
DB_password = os.getenv("DB_password")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")

app = Flask(__name__)

app.config['SECRET_KEY'] = FLASK_SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'TEST_DATABASE_URI',
    f'postgresql+psycopg2://{DB_username}:{DB_password}@localhost:{DB_PORT}/infocord_mvp'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
# NOTE: Set to False in development/testing so cookies work over plain HTTP (localhost).
#       Switch back to True when deploying behind HTTPS.
app.config['SESSION_COOKIE_SECURE'] = os.getenv("FLASK_ENV") == "production"
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

db = SQLAlchemy()
migrate = Migrate()

db.init_app(app)
migrate.init_app(app, db)

# ── Rate Limiter ───────────────────────────────────────────────────────────────

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],          # No global default; we set per-route
    storage_uri="memory://"     # Swap for Redis URI in production
)

# ── Constants ──────────────────────────────────────────────────────────────────

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15


# ── Helpers ────────────────────────────────────────────────────────────────────

def is_valid_email(email: str) -> bool:
    """Minimal email sanity check — no external dependency needed for MVP."""
    return "@" in email and "." in email.split("@")[-1]


def require_login(f):
    """Decorator that rejects unauthenticated requests with 401."""
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return wrapper


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    user = User.query.first()
    if not user:
        return {"message": "No users in database yet"}
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name
    }


@app.route("/auth/signup", methods=["POST"])
@limiter.limit("10 per hour")
def signup():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    name = data.get("name", "").strip()

    # ── Validation ──────────────────────────────────────────────────────────────
    if not email or not password or not name:
        return jsonify({"error": "email, password, and name are required"}), 400

    if not is_valid_email(email):
        return jsonify({"error": "Invalid email format"}), 400

    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    if len(name) > 100:
        return jsonify({"error": "Name must be 100 characters or fewer"}), 400

    # ── Uniqueness check ────────────────────────────────────────────────────────
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with that email already exists"}), 409

    # ── Create user ─────────────────────────────────────────────────────────────
    new_user = User(
        email=email,
        password_hash=generate_password_hash(password),
        name=name
    )
    db.session.add(new_user)
    db.session.commit()

    return jsonify({
        "message": "Account created successfully",
        "user": {
            "id": str(new_user.id),
            "email": new_user.email,
            "name": new_user.name
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
        return jsonify({"error": "email and password are required"}), 400

    user = User.query.filter_by(email=email).first()

    # ── Account lockout check ───────────────────────────────────────────────────
    if user and user.locked_until and datetime.now() < user.locked_until:
        remaining = int((user.locked_until - datetime.now()).total_seconds() / 60) + 1
        return jsonify({
            "error": f"Account temporarily locked. Try again in {remaining} minute(s)."
        }), 423

    # ── Verify credentials ──────────────────────────────────────────────────────
    if not user or not check_password_hash(user.password_hash, password):
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = datetime.now() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                user.failed_login_attempts = 0
            db.session.commit()

        return jsonify({"error": "Invalid email or password"}), 401

    # ── Successful login — reset lockout state & create session ─────────────────
    user.failed_login_attempts = 0
    user.locked_until = None
    db.session.commit()

    session.permanent = True
    session["user_id"] = str(user.id)
    session["logged_in"] = True

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
    """Returns the currently authenticated user. Useful for frontend session checks."""
    # db.session.get() is the modern replacement for the deprecated Query.get()
    user = db.session.get(User, uuid.UUID(session["user_id"]))
    if not user:
        session.clear()
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "id": str(user.id),
        "email": user.email,
        "name": user.name
    }), 200


# ── Models ─────────────────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    # ── Lockout fields (Phase 2) ─────────────────────────────────────────────
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)


class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    color = db.Column(db.String(6), nullable=False)
    archived = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)


class Note(db.Model):
    __tablename__ = 'notes'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    category_id = db.Column(UUID(as_uuid=True), db.ForeignKey('categories.id'), nullable=False)
    content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    archived = db.Column(db.Boolean, default=False)
    last_modified = db.Column(db.DateTime, default=datetime.now)


if __name__ == "__main__":
    app.run(debug=True)