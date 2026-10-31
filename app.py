import os
import re
import secrets
import hashlib
import hmac
import threading
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory, abort
from flask_socketio import SocketIO, join_room, leave_room, emit
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime, timedelta
from seed_data import seed_100_students, seed_primary_college, PRIMARY_COLLEGE

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

# ---------- SESSION & COOKIE SECURITY ----------
app.secret_key = os.environ.get("SECRET_KEY", "queuex_secret_key_change_later")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# In production with HTTPS set SESSION_COOKIE_SECURE = True via env or Railway environment
app.config["SESSION_COOKIE_SECURE"] = os.environ.get(
    "SESSION_COOKIE_SECURE",
    "true" if os.environ.get("RAILWAY_ENVIRONMENT") else "false"
).lower() == "true"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
app.config["DEBUG"] = os.environ.get("FLASK_DEBUG", "0") == "1"

# Production Socket.IO setup with optional Redis message queue
_redis_url = os.environ.get("REDIS_URL")
if _redis_url:
    socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*", message_queue=_redis_url)
else:
    socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# ---------- RATE LIMITER ----------
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],           # No global limit; apply per-route only
    storage_uri="memory://",
)

import db

APP_START_TIME = datetime.now()


def resolve_database_path():
    """Determine the database path or URL."""
    return db.resolve_sqlite_path()


DB_NAME = db.DB_NAME
_token_generation_lock = threading.Lock()

# ---------- CONFIG ----------
MINUTES_PER_TOKEN = 2

OPERATOR_USERNAME = os.environ.get("OPERATOR_USERNAME", "operator")
OPERATOR_PASSWORD = os.environ.get("OPERATOR_PASSWORD", "operator123")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "superadmin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "super123")

DEFAULT_COUNTERS = [
    {
        "name": "Examination Cell",
        "slug": "examination-cell",
        "location": "Admin Block, 1st Floor",
        "hours": "09:00 AM - 04:30 PM",
        "minutes": 3,
        "description": "Grade cards, hall tickets, transcript verification, and no-dues clearance."
    },
    {
        "name": "Accounts Office",
        "slug": "accounts-office",
        "location": "Main Building, Ground Floor",
        "hours": "09:30 AM - 04:00 PM",
        "minutes": 2,
        "description": "Fee payments, scholarship forms, fee receipt duplicates, and refund processing."
    },
    {
        "name": "Library",
        "slug": "library",
        "location": "Knowledge Centre, 2nd Floor",
        "hours": "08:30 AM - 07:00 PM",
        "minutes": 2,
        "description": "Book checkouts & returns, membership card activation, and digital research clearance."
    },
    {
        "name": "Cafeteria",
        "slug": "cafeteria",
        "location": "Student Activity Centre",
        "hours": "08:00 AM - 08:00 PM",
        "minutes": 1,
        "description": "Meal coupon issuance, prepaid cafeteria card recharges, and mess clearance."
    },
    {
        "name": "Admission Office",
        "slug": "admission-office",
        "location": "Welcome Hall, Ground Floor",
        "hours": "09:00 AM - 05:00 PM",
        "minutes": 4,
        "description": "Original certificate verification, migration certificates, and bonafide requests."
    },
    {
        "name": "Stationery Shop",
        "slug": "stationery-shop",
        "location": "Campus Arcade, Shop #4",
        "hours": "08:30 AM - 06:30 PM",
        "minutes": 1,
        "description": "Lab record notebooks, assignment sheets, engineering drawing tools, and calculators."
    },
    {
        "name": "Printing & Photocopy",
        "slug": "printing-photocopy",
        "location": "Academic Complex, West Wing",
        "hours": "08:00 AM - 07:00 PM",
        "minutes": 2,
        "description": "Thesis printing, spiral binding, color plotters, document scanning, and bulk copying."
    }
]

COUNTERS = DEFAULT_COUNTERS


# ---------- DATABASE SETUP ----------
class DB:
    """Simple context manager for SQLite operations.
    Commits on success, rolls back on exception, and always closes the connection.
    Usage:
        with DB() as cur:
            cur.execute(...)
    """
    def __enter__(self):
        self.conn = sqlite3.connect(DB_NAME)
        self.conn.row_factory = sqlite3.Row
        self.cur = self.conn.cursor()
        return self.cur
    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.conn.close()

# Backward‑compatible database helper
def get_db():
    db.DB_NAME = DB_NAME
    return db.get_db()


def is_postgres():
    return db.is_postgres()


def _column_exists(c, table, column):
    return db._column_exists(c, table, column)


def _add_column_if_missing(c, table, column, coltype):
    return db._add_column_if_missing(c, table, column, coltype)


def init_db():
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("PRAGMA journal_mode = WAL")
    except Exception:
        pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS colleges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            domain TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS counters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            current_token INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_number INTEGER NOT NULL,
            counter_slug TEXT NOT NULL,
            student_name TEXT,
            roll_no TEXT,
            father_name TEXT,
            phone TEXT,
            status TEXT DEFAULT 'waiting',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            served_at TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE,
            phone TEXT,
            password_hash TEXT,
            role TEXT NOT NULL DEFAULT 'student',
            roll_no TEXT,
            department TEXT,
            semester TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS operators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            employee_id TEXT,
            assigned_counter_id INTEGER,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (assigned_counter_id) REFERENCES counters(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS counter_services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            counter_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            estimated_duration INTEGER DEFAULT 5,
            instructions TEXT,
            active INTEGER DEFAULT 1,
            FOREIGN KEY (counter_id) REFERENCES counters(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS service_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER NOT NULL,
            document_name TEXT NOT NULL,
            mandatory INTEGER DEFAULT 1,
            description TEXT,
            FOREIGN KEY (service_id) REFERENCES counter_services(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS queue_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_id INTEGER,
            counter_id INTEGER,
            operator_id INTEGER,
            event_type TEXT,
            metadata TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            action TEXT,
            target_type TEXT,
            target_id INTEGER,
            description TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            message TEXT,
            type TEXT,
            read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            student_name TEXT NOT NULL,
            roll_no TEXT,
            email TEXT,
            counter_slug TEXT,
            category TEXT NOT NULL,
            subject TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            admin_reply TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            counter_id INTEGER,
            session_id TEXT,
            user_message TEXT,
            ai_response TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    _add_column_if_missing(c, "counters", "description", "TEXT")
    _add_column_if_missing(c, "counters", "location", "TEXT")
    _add_column_if_missing(c, "counters", "operating_hours", "TEXT")
    _add_column_if_missing(c, "counters", "status", "TEXT DEFAULT 'open'")
    _add_column_if_missing(c, "counters", "estimated_service_minutes", "INTEGER DEFAULT 2")
    _add_column_if_missing(c, "counters", "max_queue_size", "INTEGER DEFAULT 100")
    _add_column_if_missing(c, "counters", "priority_enabled", "INTEGER DEFAULT 0")
    _add_column_if_missing(c, "counters", "ai_enabled", "INTEGER DEFAULT 1")
    _add_column_if_missing(c, "counters", "college_id", "INTEGER")

    _add_column_if_missing(c, "users", "college_id", "INTEGER")
    _add_column_if_missing(c, "users", "student_uid", "TEXT")

    _add_column_if_missing(c, "tokens", "user_id", "INTEGER")
    _add_column_if_missing(c, "tokens", "college_id", "INTEGER")
    _add_column_if_missing(c, "tokens", "student_uid", "TEXT")
    _add_column_if_missing(c, "tokens", "priority", "INTEGER DEFAULT 0")
    _add_column_if_missing(c, "tokens", "service_id", "INTEGER")
    _add_column_if_missing(c, "tokens", "reason", "TEXT")
    _add_column_if_missing(c, "tokens", "called_at", "TIMESTAMP")
    _add_column_if_missing(c, "tokens", "skipped_at", "TIMESTAMP")
    _add_column_if_missing(c, "tokens", "cancelled_at", "TIMESTAMP")
    _add_column_if_missing(c, "tokens", "completed_by", "INTEGER")
    _add_column_if_missing(c, "tokens", "notes", "TEXT")

    # ---------- Seed default operator account from env vars ----------
    # We store the operator in `users` (role='operator') and link to `operators`.
    # On startup we upsert so the password stays in sync with the env var.
    op_email = f"{OPERATOR_USERNAME}@queuex.internal"
    op_hash = generate_password_hash(OPERATOR_PASSWORD)

    c.execute("SELECT id FROM users WHERE email = ? AND role = 'operator'", (op_email,))
    op_user = c.fetchone()
    if op_user:
        # Keep password hash in sync with current env var value
        c.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (op_hash, datetime.now().isoformat(timespec="seconds"), op_user["id"])
        )
        op_user_id = op_user["id"]
    else:
        c.execute(
            """INSERT INTO users (full_name, email, password_hash, role, status)
               VALUES (?, ?, ?, 'operator', 'active')""",
            ("Default Operator", op_email, op_hash)
        )
        op_user_id = c.lastrowid

    # Ensure there is exactly one operators row for this user
    c.execute("SELECT id FROM operators WHERE user_id = ?", (op_user_id,))
    if not c.fetchone():
        c.execute(
            "INSERT INTO operators (user_id, employee_id, active) VALUES (?, ?, 1)",
            (op_user_id, OPERATOR_USERNAME)
        )

    # Seed default superadmin account in users table
    admin_email = f"{ADMIN_USERNAME}@queuex.internal"
    admin_hash = generate_password_hash(ADMIN_PASSWORD)
    c.execute("SELECT id FROM users WHERE email = ? AND role = 'admin'", (admin_email,))
    adm_user = c.fetchone()
    if adm_user:
        c.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (admin_hash, datetime.now().isoformat(timespec="seconds"), adm_user["id"])
        )
    else:
        c.execute(
            """INSERT INTO users (full_name, email, password_hash, role, status)
               VALUES (?, ?, ?, 'admin', 'active')""",
            ("Super Administrator", admin_email, admin_hash)
        )

    for cdata in DEFAULT_COUNTERS:
        c.execute("SELECT id FROM counters WHERE slug = ?", (cdata["slug"],))
        existing = c.fetchone()
        if not existing:
            c.execute(
                """INSERT INTO counters
                   (name, slug, current_token, location, description, operating_hours, estimated_service_minutes, status)
                   VALUES (?, ?, 0, ?, ?, ?, ?, 'open')""",
                (cdata["name"], cdata["slug"], cdata.get("location", ""), cdata.get("description", ""),
                 cdata.get("hours", "09:00 AM - 05:00 PM"), cdata.get("minutes", 2))
            )
        else:
            c.execute(
                """UPDATE counters SET
                   location = coalesce(location, ?),
                   description = coalesce(description, ?),
                   operating_hours = coalesce(operating_hours, ?)
                   WHERE slug = ?""",
                (cdata.get("location", ""), cdata.get("description", ""),
                 cdata.get("hours", "09:00 AM - 05:00 PM"), cdata["slug"])
            )

    # Seed verified services and document checklists if empty
    c.execute("SELECT COUNT(*) as cnt FROM counter_services")
    if c.fetchone()["cnt"] == 0:
        services_seed = [
            ("examination-cell", "Hall Ticket Collection", "Collect semester end hall ticket & exam schedule slip", 3, [
                ("Valid Student ID Card", 1, "Original physical college identity card with visible barcode"),
                ("Fee Clearance Slip / No-Dues Receipt", 1, "Printout or receipt proving semester dues cleared")
            ]),
            ("examination-cell", "Transcripts & Grade Sheets", "Official authenticated transcripts and marksheets", 5, [
                ("Student ID Card", 1, "Original identity card"),
                ("Transcript Application Form", 1, "Duly signed by Academic Head"),
                ("Previous Semester Grade Cards", 0, "Photocopy of previous grade sheets")
            ]),
            ("examination-cell", "Degree / Provisional Certificate", "Degree certificate verification and issuance", 5, [
                ("Provisional Certificate / Admit Card", 1, "Original Provisional certificate"),
                ("Government Photo ID (Aadhaar/Passport)", 1, "Identity proof")
            ]),
            ("accounts-office", "Tuition & Examination Fee Payment", "Pay academic fees or submit bank deposit slips", 3, [
                ("Student ID Card", 1, "Identity proof"),
                ("Fee Challan / Payment Voucher", 1, "Generated payment slip from portal")
            ]),
            ("accounts-office", "Scholarship & Freeship Verification", "Verification for government & merit scholarships", 4, [
                ("Income Certificate", 1, "Latest official family income certificate"),
                ("Caste / Category Certificate", 0, "If applicable for category scholarship"),
                ("Bank Account Passbook Copy", 1, "Active bank account in student's name")
            ]),
            ("accounts-office", "No-Dues Clearance Certificate", "Financial clearance for final year or transfer", 3, [
                ("Clearance Form", 1, "Standard institute no-dues clearance form"),
                ("Original Fee Receipts", 0, "Copies of semester fee receipts")
            ]),
            ("library", "Book Borrow & Return", "Checkout books, return books, or renew loans", 2, [
                ("Library Membership Card / Student ID", 1, "Physical barcode card for scanner check-in"),
                ("Issued Books", 1, "Books to be returned in good condition")
            ]),
            ("library", "Library No-Dues Clearance", "Final library clearance certificate", 3, [
                ("All Borrowed Books Cleared", 1, "No outstanding overdue fines or books"),
                ("Library Borrower Card", 1, "To be deposited back")
            ]),
            ("admission-office", "Original Document Verification", "Verification of academic records for enrolled students", 5, [
                ("10th & 12th Original Marksheets", 1, "Originals plus 2 self-attested photocopies"),
                ("Transfer & Migration Certificate", 1, "Original from previous institution"),
                ("Admission Allotment Letter", 1, "Official college seat allotment letter")
            ]),
            ("admission-office", "Bonafide & Character Certificate", "Official student bonafide certificate issuance", 3, [
                ("Application Form", 1, "Request form stating reason (bank, passport, visa)"),
                ("Student ID Card", 1, "Original identity card")
            ]),
            ("stationery-shop", "Lab Record Manuals & Files", "Purchase university prescribed lab record files", 1, [
                ("Student ID Card", 1, "For student discount pricing"),
                ("Course Code Details", 0, "Specific department lab requirements")
            ]),
            ("printing-photocopy", "Thesis & Project Spiral Binding", "High-volume printing, plotting, and binding", 3, [
                ("Softcopy PDF / Document Drive", 1, "Print-ready PDF on USB drive or portal upload"),
                ("Guide Approval Signature Page", 0, "Required for final thesis submission")
            ]),
            ("cafeteria", "Meal Token & Dining Balance Recharge", "Cafeteria coupons, balance reload & mess pass", 1, [
                ("Cafeteria Card / Student ID", 1, "Campus card for wallet recharge")
            ])
        ]

        for counter_slug, s_name, s_desc, s_dur, docs in services_seed:
            c.execute("SELECT id FROM counters WHERE slug = ?", (counter_slug,))
            crow = c.fetchone()
            if crow:
                cid = crow["id"]
                c.execute(
                    "INSERT INTO counter_services (counter_id, name, description, estimated_duration, active) VALUES (?, ?, ?, ?, 1)",
                    (cid, s_name, s_desc, s_dur)
                )
                sid = c.lastrowid
                for d_name, d_mand, d_desc in docs:
                    c.execute(
                        "INSERT INTO service_documents (service_id, document_name, mandatory, description) VALUES (?, ?, ?, ?)",
                        (sid, d_name, d_mand, d_desc)
                    )

    # Seed 100 students for Apex Institute of Technology
    try:
        seed_100_students(conn)
    except Exception as e:
        print(f"Student seeding warning: {e}")

    conn.commit()
    conn.close()




def get_all_counters(include_deactivated=False):
    try:
        conn = get_db()
        c = conn.cursor()
        if include_deactivated:
            c.execute("SELECT * FROM counters WHERE status != 'deleted' ORDER BY id ASC")
        else:
            c.execute("SELECT * FROM counters WHERE status != 'deleted' AND status != 'deactivated' ORDER BY id ASC")
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        if rows:
            return rows
    except Exception:
        pass
    return DEFAULT_COUNTERS


def get_counter_by_slug(slug):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM counters WHERE slug = ? AND status != 'deleted'", (slug,))
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
    except Exception:
        pass
    for cdata in DEFAULT_COUNTERS:
        if cdata["slug"] == slug:
            return cdata
    return None


def get_counter_name(slug):
    cdata = get_counter_by_slug(slug)
    return cdata["name"] if cdata else slug.replace("-", " ").title()


def is_valid_counter(slug):
    return get_counter_by_slug(slug) is not None


def create_notification(user_id, title, message, notif_type="info"):
    if not user_id:
        return
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO notifications (user_id, title, message, type, read) VALUES (?, ?, ?, ?, 0)",
            (user_id, title, message, notif_type)
        )
        conn.commit()
        conn.close()
        socketio.emit("notification_new", {"user_id": user_id, "title": title, "message": message}, room=f"user_{user_id}")
    except Exception:
        pass


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.socket.io https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: https:; "
        "connect-src 'self' ws: wss:;"
    )
    return response


@app.errorhandler(400)
def handle_bad_request(e):
    if request.is_json or request.path.startswith("/api/"):
        desc = getattr(e, "description", "Bad Request")
        return jsonify({"error": desc if isinstance(desc, str) else "Bad Request"}), 400
    return render_template("error.html", code=400, title="Bad Request", message="The request could not be processed due to invalid syntax or parameters."), 400


@app.errorhandler(401)
def handle_unauthorized(e):
    if request.is_json or request.path.startswith("/api/"):
        return jsonify({"error": "unauthorized"}), 401
    return redirect(url_for("student_login"))


@app.errorhandler(403)
def handle_forbidden(e):
    if request.is_json or request.path.startswith("/api/"):
        desc = getattr(e, "description", "Forbidden")
        return jsonify({"error": desc if isinstance(desc, str) else "Forbidden"}), 403
    return render_template("error.html", code=403, title="Access Denied", message="You do not have permission to access this resource."), 403


@app.errorhandler(404)
def handle_not_found(e):
    if request.is_json or request.path.startswith("/api/"):
        return jsonify({"error": "Resource not found"}), 404
    return render_template("error.html", code=404, title="Page Not Found", message="The requested terminal or record could not be found."), 404


@app.errorhandler(500)
def handle_server_error(e):
    if request.is_json or request.path.startswith("/api/"):
        return jsonify({"error": "Internal server error"}), 500
    return render_template("error.html", code=500, title="Server Error", message="An unexpected server error occurred. Please try again shortly."), 500


@app.route("/health")
@app.route("/api/health")
def health_check():
    """Production health-check endpoint for Railway container monitoring."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT 1")
        conn.close()
        db_status = "connected"
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 503

    uptime_sec = round((datetime.now() - APP_START_TIME).total_seconds())

    return jsonify({
        "status": "healthy",
        "database": db_status,
        "environment": os.environ.get("RAILWAY_ENVIRONMENT", "production" if os.environ.get("FLASK_ENV") == "production" else "development"),
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": uptime_sec,
        "database_path": DB_NAME
    }), 200


def parse_token(value):
    try:
        token = int(value)
    except (TypeError, ValueError):
        return None
    return token if token > 0 else None


def current_student():
    if session.get("role") != "student" or not session.get("user_id"):
        return None
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ? AND role = 'student'", (session["user_id"],))
    row = c.fetchone()
    conn.close()
    return row


def is_operator():
    """Return True only when session holds a valid, active operator."""
    if session.get("role") != "operator" or not session.get("operator_id"):
        return False
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """SELECT op.id FROM operators op
           JOIN users u ON u.id = op.user_id
           WHERE op.id = ? AND op.active = 1 AND u.status = 'active' AND u.role = 'operator'""",
        (session["operator_id"],)
    )
    row = c.fetchone()
    conn.close()
    return row is not None


def is_admin():
    """Return True only when session role is 'admin'."""
    return session.get("role") == "admin"


# ---------- CSRF PROTECTION ----------
# Lightweight HMAC-based CSRF token — no external library needed.
# Token = HMAC-SHA256(secret_key, session_csrf_seed) encoded as hex.
# The seed is generated once per session and stored server-side in the session.

def _get_csrf_seed():
    """Return (or create) the per-session random seed."""
    if "csrf_seed" not in session:
        session["csrf_seed"] = secrets.token_hex(32)
    return session["csrf_seed"]


def generate_csrf_token():
    """Return the CSRF token string for the current session."""
    seed = _get_csrf_seed()
    return hmac.new(
        app.secret_key.encode() if isinstance(app.secret_key, str) else app.secret_key,
        seed.encode(),
        hashlib.sha256
    ).hexdigest()


def validate_csrf():
    """
    Validate the CSRF token submitted in a POST/PUT/PATCH/DELETE request.
    Raises 403 if the token is absent or invalid.
    Socket.IO POSTs, JSON requests with X-CSRFToken, and testing mode are handled appropriately.
    """
    if request.path.startswith("/socket.io"):
        return
    if app.config.get("TESTING") and not app.config.get("CSRF_ENABLED", False):
        return
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return

    token = (
        request.form.get("csrf_token")
        or request.headers.get("X-CSRFToken")
        or request.headers.get("X-CSRF-Token")
    )
    if not token and request.is_json:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            token = payload.get("csrf_token")

    expected = generate_csrf_token()
    if not token or not hmac.compare_digest(str(token), str(expected)):
        abort(403)


@app.before_request
def csrf_protect():
    validate_csrf()


# Expose csrf_token() inside every Jinja template automatically
@app.context_processor
def inject_csrf():
    return {"csrf_token": generate_csrf_token}


# ---------- INPUT VALIDATION HELPERS ----------

_PHONE_RE = re.compile(r"^\d{10}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLUG_RE  = re.compile(r"^[a-z0-9\-]{1,64}$")


def sanitize_text(value, max_len=200):
    """Strip leading/trailing whitespace and truncate to max_len."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_len]


def valid_phone(value):
    return bool(_PHONE_RE.match(value))


def valid_email(value):
    return bool(_EMAIL_RE.match(value)) and len(value) <= 254


def valid_slug(value):
    return bool(_SLUG_RE.match(value)) if value else False


def get_counter_status(slug):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT status FROM counters WHERE slug = ?", (slug,))
    row = c.fetchone()
    conn.close()
    return row["status"] if row and row["status"] else "open"


# ---------- REALTIME HELPER ----------
def broadcast_queue_update(slug):
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT current_token, status FROM counters WHERE slug = ?", (slug,))
    row = c.fetchone()
    current_token = row["current_token"] if row else 0
    counter_status = row["status"] if row and row["status"] else "open"

    c.execute(
        """SELECT token_number, student_name, roll_no FROM tokens
           WHERE counter_slug = ? AND token_number > ? AND status = 'waiting'
           ORDER BY token_number ASC""",
        (slug, current_token)
    )
    waiting = [dict(r) for r in c.fetchall()]
    conn.close()

    socketio.emit("queue_update", {
        "counter_slug": slug,
        "current_token": current_token,
        "waiting_count": len(waiting),
        "queue": waiting,
        "counter_status": counter_status
    }, room=slug)

    socketio.emit("admin_refresh", {"counter_slug": slug}, room="admin_global")


# ---------- STUDENT AUTH ROUTES ----------

@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        roll_no = request.form.get("roll_no", "").strip()
        department = request.form.get("department", "").strip()
        semester = request.form.get("semester", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # Clean digits from phone
        clean_phone = re.sub(r"\D", "", phone) if phone else ""

        if not full_name:
            error = "Please provide your full name."
        elif not email and not clean_phone:
            error = "Please provide either an email address or mobile number."
        elif email and ("@" not in email or "." not in email):
            error = "Please enter a valid email address."
        elif clean_phone and len(clean_phone) != 10:
            error = "Mobile number must be exactly 10 digits."
        elif not password or not confirm_password:
            error = "Please enter and confirm your password."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            conn = get_db()
            c = conn.cursor()

            # Check email uniqueness if email provided
            if email:
                c.execute("SELECT id FROM users WHERE LOWER(email) = ?", (email,))
                if c.fetchone():
                    conn.close()
                    return render_template("register.html", error="An account with this email already exists.")

            # Check phone uniqueness if phone provided
            if clean_phone:
                c.execute("SELECT id FROM users WHERE phone = ?", (clean_phone,))
                if c.fetchone():
                    conn.close()
                    return render_template("register.html", error="An account with this mobile number already exists.")

            # Check roll_no uniqueness if roll_no provided
            if roll_no:
                c.execute("SELECT id FROM users WHERE LOWER(roll_no) = ? AND role = 'student'", (roll_no.lower(),))
                if c.fetchone():
                    conn.close()
                    return render_template("register.html", error="An account with this roll number already exists.")

            db_email = email if email else None
            db_phone = clean_phone if clean_phone else None

            c.execute(
                """INSERT INTO users
                   (full_name, email, phone, password_hash, role, roll_no, department, semester, status)
                   VALUES (?, ?, ?, ?, 'student', ?, ?, ?, 'active')""",
                (full_name, db_email, db_phone, generate_password_hash(password), roll_no, department, semester)
            )
            conn.commit()
            new_id = c.lastrowid
            conn.close()

            session["user_id"] = new_id
            session["role"] = "student"
            return redirect(url_for("student"))

    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def student_login():
    error = None
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")

        clean_phone = re.sub(r"\D", "", identifier)
        clean_uid = identifier.upper()

        conn = get_db()
        c = conn.cursor()
        c.execute(
            """SELECT * FROM users 
               WHERE role = 'student' 
                 AND (
                     LOWER(email) = ? 
                     OR (phone = ? AND ? != '') 
                     OR LOWER(roll_no) = ?
                     OR UPPER(student_uid) = ?
                 )""",
            (identifier.lower(), clean_phone, clean_phone, identifier.lower(), clean_uid)
        )
        row = c.fetchone()

        if row and row["password_hash"] and check_password_hash(row["password_hash"], password):
            if row["status"] != "active":
                error = "This account is deactivated. Contact admin."
            else:
                c.execute("UPDATE users SET last_login = ? WHERE id = ?",
                          (datetime.now().isoformat(timespec="seconds"), row["id"]))
                conn.commit()
                session.clear()
                session["user_id"] = row["id"]
                session["role"] = "student"
                conn.close()
                return redirect(url_for("student"))
        else:
            error = "Invalid email, mobile number, roll number, or password."
        conn.close()

    return render_template("student_login.html", error=error)


@app.route("/student/logout")
def student_logout():
    # Clear all student session data unconditionally
    session.pop("user_id", None)
    session.pop("role", None)
    return redirect(url_for("index"))


# ---------- STUDENT ROUTES ----------

@app.route("/")
def index():
    return render_template("index.html", counters=COUNTERS)


@app.route("/sw.js")
def service_worker():
    return send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")


@app.route("/offline")
def offline():
    return render_template("offline.html")


@app.route("/student")
def student():
    student_user = current_student()
    return render_template("student.html", counters=COUNTERS, student_user=student_user)


@app.route("/get-token", methods=["POST"])
def get_token():
    slug = request.form.get("counter")
    if not is_valid_counter(slug):
        return jsonify({"error": "invalid counter"}), 400

    if get_counter_status(slug) != "open":
        return jsonify({"error": "This counter is currently not accepting tokens"}), 400

    student_user = current_student()

    if student_user:
        student_name = student_user["full_name"]
        roll_no = student_user["roll_no"] or ""
        father_name = request.form.get("father_name", "").strip() or "Parent / Guardian"
        phone = student_user["phone"] or ""
        user_uid = student_user["student_uid"] if "student_uid" in student_user.keys() else None
        user_cid = student_user["college_id"] if "college_id" in student_user.keys() and student_user["college_id"] else 1
        user_id = student_user["id"]
    else:
        student_name = request.form.get("student_name", "").strip()
        roll_no = request.form.get("roll_no", "").strip()
        father_name = request.form.get("father_name", "").strip() or "Parent / Guardian"
        phone = request.form.get("phone", "").strip()

        if not student_name or not roll_no:
            return jsonify({"error": "student name and roll number are required"}), 400

        clean_phone = re.sub(r"\D", "", phone) if phone else ""
        if phone and len(clean_phone) != 10:
            return jsonify({"error": "phone must be 10 digits"}), 400
        phone = clean_phone

        # Validate that student is enrolled in the college database
        conn_check = get_db()
        c_check = conn_check.cursor()
        c_check.execute(
            """SELECT * FROM users WHERE role = 'student' AND (
                LOWER(roll_no) = ? OR UPPER(student_uid) = ? OR (phone = ? AND ? != '')
            )""",
            (roll_no.lower(), roll_no.upper(), clean_phone, clean_phone)
        )
        enrolled = c_check.fetchone()
        conn_check.close()

        if not enrolled and not app.config.get("TESTING"):
            return jsonify({
                "error": f"Student with Roll No / ID '{roll_no}' is not enrolled in the college database. Only enrolled students are permitted to take tokens. Please contact Admin."
            }), 403

        if enrolled:
            student_name = enrolled["full_name"]
            roll_no = enrolled["roll_no"] or roll_no
            phone = enrolled["phone"] or phone
            user_uid = enrolled["student_uid"]
            user_cid = enrolled["college_id"] or 1
            user_id = enrolled["id"]
        else:
            user_uid = None
            user_cid = 1
            user_id = None

    student_name = sanitize_text(student_name, 100)
    roll_no = sanitize_text(roll_no, 40)
    father_name = sanitize_text(father_name, 100)

    with _token_generation_lock:
        conn = get_db()
        # Serialise token allocation with process lock & exclusive/serializable transaction
        if not is_postgres():
            conn.isolation_level = None          # manual transaction control
            c = conn.cursor()
            c.execute("BEGIN EXCLUSIVE")
        else:
            c = conn.cursor()

        try:
            c.execute(
                "SELECT MAX(token_number) as max_token FROM tokens WHERE counter_slug = ?",
                (slug,)
            )
            row = c.fetchone()
            new_token = (row["max_token"] or 0) + 1

            c.execute(
                """INSERT INTO tokens
                   (token_number, counter_slug, student_name, roll_no, father_name, phone, status, user_id, student_uid, college_id)
                   VALUES (?, ?, ?, ?, ?, ?, 'waiting', ?, ?, ?)""",
                (new_token, slug, student_name, roll_no, father_name, phone,
                 user_id, user_uid, user_cid)
            )
            new_token_id = c.lastrowid
            if not is_postgres():
                c.execute("COMMIT")
            else:
                conn.commit()
        except Exception:
            if not is_postgres():
                c.execute("ROLLBACK")
            else:
                conn.rollback()
            conn.close()
            return jsonify({"error": "Could not allocate token, please try again"}), 500
        conn.close()

    # Track issued token in student session for authorization and history
    issued = session.get("issued_tokens", [])
    if not isinstance(issued, list):
        issued = []
    issued.append({
        "id": new_token_id,
        "counter": slug,
        "token": new_token,
        "created_at": datetime.now().isoformat(timespec="seconds")
    })
    session["issued_tokens"] = issued[-25:]
    session.modified = True

    broadcast_queue_update(slug)

    return redirect(url_for("status", counter=slug, token=new_token))


def check_token_authorization(token_row):
    """Check if the current session or user is authorized to manage this token."""
    if not token_row:
        return False
    if is_admin() or is_operator():
        return True

    token_keys = token_row.keys() if hasattr(token_row, "keys") else []
    token_user_id = token_row["user_id"] if "user_id" in token_keys else None
    token_slug = token_row["counter_slug"] if "counter_slug" in token_keys else None
    token_num = token_row["token_number"] if "token_number" in token_keys else None
    token_id = token_row["id"] if "id" in token_keys else None

    student_user = current_student()
    if student_user and token_user_id and token_user_id == student_user["id"]:
        return True

    issued = session.get("issued_tokens", [])
    if isinstance(issued, list):
        for item in issued:
            if isinstance(item, dict):
                if token_slug and token_num and item.get("counter") == token_slug and item.get("token") == token_num:
                    return True
                if token_id and item.get("id") == token_id:
                    return True
    return False


@app.route("/cancel-token", methods=["POST"])
@app.route("/api/student/cancel-token", methods=["POST"])
def cancel_token():
    payload = request.get_json(silent=True) or request.form
    slug = payload.get("counter")
    token = parse_token(payload.get("token"))
    token_id = payload.get("token_id")

    conn = get_db()
    c = conn.cursor()

    if token_id:
        c.execute("SELECT * FROM tokens WHERE id = ?", (token_id,))
    elif slug and token is not None:
        c.execute("SELECT * FROM tokens WHERE counter_slug = ? AND token_number = ?", (slug, token))
    else:
        conn.close()
        return jsonify({"error": "Missing counter and token parameters"}), 400

    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Token not found"}), 404

    # 1. Authorization check: only authorized student/session or staff
    if not check_token_authorization(row):
        conn.close()
        return jsonify({"error": "Unauthorized: You can only cancel tokens issued from your account or session."}), 403

    # 2. Status check: only waiting tokens can be cancelled
    if row["status"] != "waiting":
        conn.close()
        return jsonify({
            "error": f"Cannot cancel token #{row['token_number']}. It is already {row['status']}."
        }), 400

    now_iso = datetime.now().isoformat(timespec="seconds")
    c.execute(
        "UPDATE tokens SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
        (now_iso, row["id"])
    )
    conn.commit()
    conn.close()

    broadcast_queue_update(row["counter_slug"])

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.path.startswith("/api/"):
        return jsonify({
            "success": True,
            "message": f"Token #{row['token_number']} has been successfully cancelled.",
            "status": "cancelled",
            "token": row["token_number"],
            "counter": row["counter_slug"]
        })

    return redirect(url_for("status", counter=row["counter_slug"], token=row["token_number"]))


@app.route("/my-tokens")
def my_tokens():
    student_user = current_student()
    if not student_user:
        return redirect(url_for("student_login"))

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM tokens WHERE user_id = ? ORDER BY created_at DESC",
        (student_user["id"],)
    )
    rows = c.fetchall()
    conn.close()

    tokens = []
    for r in rows:
        t = dict(r)
        t["counter_name"] = get_counter_name(t["counter_slug"])
        tokens.append(t)

    return render_template("my_tokens.html", tokens=tokens, student_user=student_user)


@app.route("/status")
def status():
    slug = request.args.get("counter")
    token = parse_token(request.args.get("token"))

    if not is_valid_counter(slug) or token is None:
        return redirect(url_for("student"))

    student_user = current_student()

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM tokens WHERE counter_slug = ? AND token_number = ?",
        (slug, token)
    )
    row = c.fetchone()
    conn.close()

    is_owner = check_token_authorization(row) if row else False
    token_status = row["status"] if row else "waiting"

    return render_template(
        "status.html",
        counter_slug=slug,
        counter_name=get_counter_name(slug),
        token=token,
        token_id=row["id"] if row else None,
        token_status=token_status,
        is_owner=is_owner,
        student_name=row["student_name"] if (row and (is_owner or is_operator() or is_admin())) else (row["student_name"] if row else ""),
        roll_no=row["roll_no"] if (row and (is_owner or is_operator() or is_admin())) else (row["roll_no"] if row else ""),
        student_user=student_user
    )


@app.route("/api/status")
def api_status():
    slug = request.args.get("counter")
    token = parse_token(request.args.get("token"))

    if not is_valid_counter(slug) or token is None:
        return jsonify({"error": "invalid counter or token"}), 400

    conn = get_db()
    c = conn.cursor()

    # Fetch the real status of this specific token row
    c.execute(
        "SELECT * FROM tokens WHERE counter_slug = ? AND token_number = ?",
        (slug, token)
    )
    token_row = c.fetchone()

    c.execute("SELECT current_token, estimated_service_minutes FROM counters WHERE slug = ?", (slug,))
    counter_row = c.fetchone()
    current_token = counter_row["current_token"] if counter_row else 0
    service_minutes = counter_row["estimated_service_minutes"] if counter_row and counter_row["estimated_service_minutes"] else MINUTES_PER_TOKEN
    conn.close()

    # Determine student-facing status from the token's actual DB status
    if token_row is None:
        # Token doesn't exist at all
        student_status = "waiting"
    elif token_row["status"] == "served":
        student_status = "served"
    elif token_row["status"] == "skipped":
        student_status = "skipped"
    elif token_row["status"] == "cancelled":
        student_status = "cancelled"
    else:
        student_status = "waiting"

    if student_status in ("served", "skipped", "cancelled"):
        people_ahead = 0
        estimated_wait = 0
    else:
        people_ahead = max(token - current_token - 1, 0)
        estimated_wait = people_ahead * service_minutes

    is_owner = check_token_authorization(token_row) if token_row else False

    return jsonify({
        "your_token": token,
        "currently_serving": current_token,
        "people_ahead": people_ahead,
        "estimated_wait": estimated_wait,
        "status": student_status,
        "is_owner": is_owner,
        "counter_slug": slug
    })


@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    student_user = current_student()
    error = None
    success = None

    if request.method == "POST":
        full_name = request.form.get("student_name", "").strip()
        roll_no = request.form.get("roll_no", "").strip()
        email = request.form.get("email", "").strip()
        counter_slug = request.form.get("counter", "").strip() or None
        category = request.form.get("category", "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()

        if student_user:
            full_name = full_name or student_user["full_name"]
            roll_no = roll_no or student_user["roll_no"] or ""
            email = email or student_user["email"] or ""
            user_id = student_user["id"]
        else:
            user_id = None

        if not full_name:
            error = "Please provide your name."
        elif not category:
            error = "Please select a feedback category."
        elif not subject:
            error = "Please provide a subject."
        elif not message or len(message) < 5:
            error = "Please provide a detailed message (minimum 5 characters)."
        else:
            conn = get_db()
            c = conn.cursor()
            c.execute(
                """INSERT INTO complaints
                   (user_id, student_name, roll_no, email, counter_slug, category, subject, message, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (user_id, sanitize_text(full_name), sanitize_text(roll_no, 50),
                 sanitize_text(email, 120), counter_slug,
                 sanitize_text(category, 60), sanitize_text(subject, 150),
                 sanitize_text(message, 1000))
            )
            conn.commit()
            conn.close()
            success = "Your feedback has been submitted successfully. The campus administration will review it promptly."

    recent_complaints = []
    if student_user:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM complaints WHERE user_id = ? ORDER BY created_at DESC LIMIT 5", (student_user["id"],))
        recent_complaints = [dict(r) for r in c.fetchall()]
        conn.close()

    default_counter = request.args.get("counter", "")
    return render_template(
        "feedback.html",
        counters=COUNTERS,
        student_user=student_user,
        default_counter=default_counter,
        error=error,
        success=success,
        recent_complaints=recent_complaints
    )


@app.route("/api/feedback", methods=["POST"])
@app.route("/api/student/complaints", methods=["POST"])
def api_feedback():
    data = request.get_json(silent=True) or request.form
    full_name = (data.get("student_name") or "").strip()
    roll_no = (data.get("roll_no") or "").strip()
    email = (data.get("email") or "").strip()
    counter_slug = (data.get("counter") or "").strip() or None
    category = (data.get("category") or "").strip()
    subject = (data.get("subject") or "").strip()
    message = (data.get("message") or "").strip()

    student_user = current_student()
    if student_user:
        full_name = full_name or student_user["full_name"]
        roll_no = roll_no or student_user["roll_no"] or ""
        email = email or student_user["email"] or ""
        user_id = student_user["id"]
    else:
        user_id = None

    if not full_name or not category or not subject or not message:
        return jsonify({"error": "Full name, category, subject, and message are required."}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute(
        """INSERT INTO complaints
           (user_id, student_name, roll_no, email, counter_slug, category, subject, message, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (user_id, sanitize_text(full_name), sanitize_text(roll_no, 50),
         sanitize_text(email, 120), counter_slug,
         sanitize_text(category, 60), sanitize_text(subject, 150),
         sanitize_text(message, 1000))
    )
    conn.commit()
    new_id = c.lastrowid
    conn.close()

    return jsonify({
        "success": True,
        "message": "Feedback submitted successfully.",
        "complaint_id": new_id
    })


# ---------- OPERATOR ROUTES ----------

@app.route("/operator/register", methods=["GET", "POST"])
def operator_register():
    error = None
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        employee_id = request.form.get("employee_id", "").strip()
        assigned_counter = request.form.get("assigned_counter", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        clean_phone = re.sub(r"\D", "", phone) if phone else ""

        if not full_name:
            error = "Please provide operator full name."
        elif not email and not clean_phone:
            error = "Please provide either an Email address or Mobile Number."
        elif email and ("@" not in email or "." not in email):
            error = "Please enter a valid email address."
        elif clean_phone and len(clean_phone) != 10:
            error = "Mobile number must be 10 digits."
        elif not password or not confirm_password:
            error = "Please enter and confirm your password."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            conn = get_db()
            c = conn.cursor()

            if email:
                c.execute("SELECT id FROM users WHERE LOWER(email) = ?", (email,))
                if c.fetchone():
                    conn.close()
                    return render_template("operator_register.html", error="An account with this email already exists.", counters=COUNTERS)

            if clean_phone:
                c.execute("SELECT id FROM users WHERE phone = ?", (clean_phone,))
                if c.fetchone():
                    conn.close()
                    return render_template("operator_register.html", error="An account with this mobile number already exists.", counters=COUNTERS)

            emp_code = employee_id if employee_id else f"OP-{secrets.token_hex(2).upper()}"
            if employee_id:
                c.execute("SELECT id FROM operators WHERE LOWER(employee_id) = ?", (employee_id.lower(),))
                if c.fetchone():
                    conn.close()
                    return render_template("operator_register.html", error="An operator with this Employee ID already exists.", counters=COUNTERS)

            counter_id = None
            if assigned_counter:
                c.execute("SELECT id FROM counters WHERE slug = ?", (assigned_counter,))
                crow = c.fetchone()
                if crow:
                    counter_id = crow["id"]

            db_email = email if email else None
            db_phone = clean_phone if clean_phone else None

            c.execute(
                """INSERT INTO users
                   (full_name, email, phone, password_hash, role, roll_no, status)
                   VALUES (?, ?, ?, ?, 'operator', ?, 'active')""",
                (full_name, db_email, db_phone, generate_password_hash(password), emp_code)
            )
            new_user_id = c.lastrowid

            c.execute(
                """INSERT INTO operators
                   (user_id, employee_id, assigned_counter_id, active)
                   VALUES (?, ?, ?, 1)""",
                (new_user_id, emp_code, counter_id)
            )
            conn.commit()
            new_op_id = c.lastrowid
            conn.close()

            session["role"] = "operator"
            session["operator_id"] = new_op_id
            session["user_id"] = new_user_id
            return redirect(url_for("operator_dashboard"))

    return render_template("operator_register.html", error=error, counters=COUNTERS)


@app.route("/operator/login", methods=["GET", "POST"])
def operator_login():
    error = None
    if request.method == "POST":
        identifier = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # 1. Fallback for default env credentials
        if identifier == OPERATOR_USERNAME and password == OPERATOR_PASSWORD:
            conn = get_db()
            c = conn.cursor()
            op_email = f"{OPERATOR_USERNAME}@queuex.internal"
            c.execute(
                """SELECT u.id, op.id as operator_id FROM users u
                   JOIN operators op ON op.user_id = u.id
                   WHERE u.email = ? AND u.role = 'operator' AND op.active = 1""",
                (op_email,)
            )
            row = c.fetchone()
            conn.close()
            if row:
                session.clear()
                session["role"] = "operator"
                session["operator_id"] = row["operator_id"]
                session["user_id"] = row["id"]
                return redirect(url_for("operator_dashboard"))

        # 2. Database lookup by Email, Mobile Number, Employee ID, or Username
        clean_phone = re.sub(r"\D", "", identifier) if identifier else ""
        op_email = f"{identifier}@queuex.internal"
        conn = get_db()
        c = conn.cursor()
        c.execute(
            """SELECT u.id, u.password_hash, u.status, op.id as operator_id
               FROM users u
               JOIN operators op ON op.user_id = u.id
               WHERE u.role = 'operator' AND op.active = 1
                 AND (
                     LOWER(u.email) = ?
                     OR LOWER(u.email) = ?
                     OR (u.phone = ? AND ? != '')
                     OR LOWER(op.employee_id) = ?
                     OR LOWER(u.roll_no) = ?
                 )""",
            (identifier.lower(), op_email.lower(), clean_phone, clean_phone, identifier.lower(), identifier.lower())
        )
        row = c.fetchone()
        conn.close()

        if row and row["password_hash"] and check_password_hash(row["password_hash"], password):
            if row["status"] != "active":
                error = "This operator account is deactivated. Contact admin."
            else:
                session.clear()
                session["role"] = "operator"
                session["operator_id"] = row["operator_id"]
                session["user_id"] = row["id"]
                return redirect(url_for("operator_dashboard"))
        else:
            error = "Invalid username, email, phone number, or password."
    return render_template("operator_login.html", error=error)


def current_operator():
    """Return dictionary of current authenticated operator and assigned counter details."""
    if session.get("role") != "operator" or not session.get("operator_id"):
        return None
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """SELECT op.id as operator_id, op.employee_id, op.assigned_counter_id,
                  co.slug as assigned_slug, co.name as assigned_name,
                  u.id as user_id, u.full_name, u.email, u.phone
           FROM operators op
           JOIN users u ON u.id = op.user_id
           LEFT JOIN counters co ON co.id = op.assigned_counter_id
           WHERE op.id = ? AND op.active = 1 AND u.status = 'active' AND u.role = 'operator'""",
        (session["operator_id"],)
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def operator_can_manage_counter(counter_slug):
    """Ensure operators can only manage their assigned counters.
    Operators without an assigned counter (e.g. float operators) can manage any counter.
    """
    op = current_operator()
    if not op:
        return False
    # If operator has an assigned counter, they must match
    if op.get("assigned_slug") and op["assigned_slug"] != counter_slug:
        return False
    return True


@app.route("/operator/logout")
def operator_logout():
    session.pop("role", None)
    session.pop("operator_id", None)
    session.pop("user_id", None)
    return redirect(url_for("operator_login"))


@app.route("/operator")
def operator_dashboard():
    if not is_operator():
        return redirect(url_for("operator_login"))
    op = current_operator()
    assigned_counter = None
    if op and op.get("assigned_slug"):
        assigned_counter = get_counter_by_slug(op["assigned_slug"])
    return render_template(
        "operator_dashboard.html",
        counters=COUNTERS,
        assigned_counter=assigned_counter,
        operator_info=op
    )


@app.route("/api/operator/queue")
def api_operator_queue():
    if not is_operator():
        return jsonify({"error": "unauthorized"}), 401

    slug = request.args.get("counter")
    if not is_valid_counter(slug):
        return jsonify({"error": "invalid counter"}), 400

    op = current_operator()
    if not operator_can_manage_counter(slug):
        return jsonify({
            "error": f"Unauthorized: You are assigned to '{op['assigned_name']}' and cannot view or manage '{get_counter_name(slug)}'."
        }), 403

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT current_token, status, estimated_service_minutes FROM counters WHERE slug = ?", (slug,))
    row = c.fetchone()
    current_token = row["current_token"] if row else 0
    counter_status = row["status"] if row and row["status"] else "open"

    # Fetch currently serving token details
    serving_student = None
    if current_token > 0:
        c.execute(
            """SELECT id, token_number, student_name, roll_no, phone, father_name, created_at, called_at, student_uid
               FROM tokens
               WHERE counter_slug = ? AND token_number = ? AND status = 'served'""",
            (slug, current_token)
        )
        s_row = c.fetchone()
        if s_row:
            serving_student = dict(s_row)

    # Fetch all waiting tokens with full student details
    c.execute(
        """SELECT id, token_number, student_name, roll_no, phone, father_name, created_at, student_uid, priority
           FROM tokens
           WHERE counter_slug = ? AND status = 'waiting'
           ORDER BY priority DESC, token_number ASC""",
        (slug,)
    )
    waiting = [dict(r) for r in c.fetchall()]

    c.execute(
        "SELECT COUNT(*) as cnt FROM tokens WHERE counter_slug = ? AND status = 'served' AND date(created_at) = date('now')",
        (slug,)
    )
    served_today = c.fetchone()["cnt"]

    conn.close()

    return jsonify({
        "current_token": current_token,
        "serving_student": serving_student,
        "waiting_count": len(waiting),
        "queue": waiting,
        "counter_status": counter_status,
        "served_today": served_today,
        "counter_name": get_counter_name(slug),
        "assigned_slug": op.get("assigned_slug") if op else None
    })


@app.route("/api/operator/call-next", methods=["POST"])
def call_next():
    if not is_operator():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or request.form
    slug = payload.get("counter")
    if not is_valid_counter(slug):
        return jsonify({"error": "invalid counter"}), 400

    op = current_operator()
    if not operator_can_manage_counter(slug):
        return jsonify({
            "error": f"Unauthorized: You are assigned to '{op['assigned_name']}' and cannot manage '{get_counter_name(slug)}'."
        }), 403

    conn = get_db()
    # Serialise with an EXCLUSIVE transaction to prevent duplicate token serving & race conditions
    conn.isolation_level = None
    c = conn.cursor()
    c.execute("BEGIN EXCLUSIVE")
    try:
        c.execute("SELECT current_token FROM counters WHERE slug = ?", (slug,))
        row = c.fetchone()
        current_token = row["current_token"] if row else 0

        # Select the next waiting token in order
        c.execute(
            """SELECT id, token_number, student_name, roll_no, phone, father_name
               FROM tokens
               WHERE counter_slug = ? AND status = 'waiting'
               ORDER BY priority DESC, token_number ASC LIMIT 1""",
            (slug,)
        )
        next_row = c.fetchone()
        if not next_row:
            c.execute("COMMIT")
            conn.close()
            return jsonify({"error": "queue is empty", "current_token": current_token}), 400

        new_current = next_row["token_number"]
        token_id = next_row["id"]
        now_iso = datetime.now().isoformat(timespec="seconds")
        op_user_id = session.get("user_id")

        # Advance counter and mark token as served atomically
        c.execute("UPDATE counters SET current_token = ? WHERE slug = ?", (new_current, slug))
        c.execute(
            """UPDATE tokens
               SET status = 'served', served_at = ?, called_at = ?, completed_by = ?
               WHERE id = ? AND status = 'waiting'""",
            (now_iso, now_iso, op_user_id, token_id)
        )
        if c.rowcount == 0:
            # Another concurrent request already served this token
            c.execute("ROLLBACK")
            conn.close()
            return jsonify({"error": "Token was claimed by another request, please try again"}), 409

        c.execute("COMMIT")
    except Exception as e:
        c.execute("ROLLBACK")
        conn.close()
        return jsonify({"error": "Could not advance queue, please try again"}), 500
    conn.close()

    broadcast_queue_update(slug)
    return jsonify({
        "current_token": new_current,
        "token_number": new_current,
        "student_name": next_row["student_name"],
        "roll_no": next_row["roll_no"]
    })


@app.route("/api/operator/recall", methods=["POST"])
def recall_token():
    """Re-announce the currently serving token without advancing the queue."""
    if not is_operator():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or request.form
    slug = payload.get("counter")
    if not is_valid_counter(slug):
        return jsonify({"error": "invalid counter"}), 400

    op = current_operator()
    if not operator_can_manage_counter(slug):
        return jsonify({
            "error": f"Unauthorized: You are assigned to '{op['assigned_name']}' and cannot manage '{get_counter_name(slug)}'."
        }), 403

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT current_token FROM counters WHERE slug = ?", (slug,))
    row = c.fetchone()
    current_token = row["current_token"] if row else 0

    # Fetch details of recalled token
    c.execute(
        """SELECT student_name, roll_no FROM tokens
           WHERE counter_slug = ? AND token_number = ? AND status = 'served'""",
        (slug, current_token)
    )
    tok_row = c.fetchone()
    conn.close()

    socketio.emit("token_recalled", {
        "counter_slug": slug,
        "current_token": current_token,
        "student_name": tok_row["student_name"] if tok_row else ""
    }, room=slug)

    return jsonify({
        "current_token": current_token,
        "student_name": tok_row["student_name"] if tok_row else "",
        "message": f"Token #{current_token} recalled."
    })


@app.route("/api/operator/skip", methods=["POST"])
def skip_token():
    if not is_operator():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or request.form
    slug = payload.get("counter")
    if not is_valid_counter(slug):
        return jsonify({"error": "invalid counter"}), 400

    op = current_operator()
    if not operator_can_manage_counter(slug):
        return jsonify({
            "error": f"Unauthorized: You are assigned to '{op['assigned_name']}' and cannot manage '{get_counter_name(slug)}'."
        }), 403

    conn = get_db()
    conn.isolation_level = None
    c = conn.cursor()
    c.execute("BEGIN EXCLUSIVE")
    try:
        c.execute("SELECT current_token FROM counters WHERE slug = ?", (slug,))
        row = c.fetchone()
        current_token = row["current_token"] if row else 0

        c.execute(
            """SELECT id, token_number FROM tokens
               WHERE counter_slug = ? AND status = 'waiting'
               ORDER BY priority DESC, token_number ASC LIMIT 1""",
            (slug,)
        )
        next_row = c.fetchone()
        if not next_row:
            c.execute("COMMIT")
            conn.close()
            return jsonify({"error": "queue is empty", "current_token": current_token}), 400

        new_current = next_row["token_number"]
        token_id = next_row["id"]
        now_iso = datetime.now().isoformat(timespec="seconds")

        c.execute("UPDATE counters SET current_token = ? WHERE slug = ?", (new_current, slug))
        c.execute(
            "UPDATE tokens SET status = 'skipped', skipped_at = ? WHERE id = ? AND status = 'waiting'",
            (now_iso, token_id)
        )
        if c.rowcount == 0:
            c.execute("ROLLBACK")
            conn.close()
            return jsonify({"error": "Token state changed, please retry"}), 409

        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        conn.close()
        return jsonify({"error": "Could not skip token, please try again"}), 500
    conn.close()

    broadcast_queue_update(slug)
    return jsonify({"current_token": new_current, "skipped_token": new_current})


@app.route("/api/operator/reset", methods=["POST"])
def reset_queue():
    if not is_operator():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or request.form
    slug = payload.get("counter")
    if not is_valid_counter(slug):
        return jsonify({"error": "invalid counter"}), 400

    op = current_operator()
    if not operator_can_manage_counter(slug):
        return jsonify({
            "error": f"Unauthorized: You are assigned to '{op['assigned_name']}' and cannot manage '{get_counter_name(slug)}'."
        }), 403

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE counters SET current_token = 0 WHERE slug = ?", (slug,))
    c.execute("DELETE FROM tokens WHERE counter_slug = ?", (slug,))
    conn.commit()
    conn.close()

    broadcast_queue_update(slug)
    return jsonify({"message": "reset done", "current_token": 0})


@app.route("/api/operator/set-status", methods=["POST"])
def set_counter_status():
    """Pause / Resume / Open / Close a counter station."""
    if not is_operator():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or request.form
    slug = payload.get("counter")
    new_status = payload.get("status")

    if not is_valid_counter(slug):
        return jsonify({"error": "invalid counter"}), 400

    op = current_operator()
    if not operator_can_manage_counter(slug):
        return jsonify({
            "error": f"Unauthorized: You are assigned to '{op['assigned_name']}' and cannot manage '{get_counter_name(slug)}'."
        }), 403

    if new_status not in ("open", "paused", "closed"):
        return jsonify({"error": "invalid status"}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE counters SET status = ? WHERE slug = ?", (new_status, slug))
    conn.commit()
    conn.close()

    broadcast_queue_update(slug)
    return jsonify({"status": new_status, "counter_slug": slug})


# ---------- SUPER ADMIN ROUTES ----------

ADMIN_REGISTRATION_KEY = os.environ.get("ADMIN_REGISTRATION_KEY", ADMIN_PASSWORD)

@app.route("/admin/register", methods=["GET", "POST"])
def admin_register():
    error = None
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        department = request.form.get("department", "").strip()
        admin_key = request.form.get("admin_key", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        clean_phone = re.sub(r"\D", "", phone) if phone else ""

        if not full_name:
            error = "Please provide administrator full name."
        elif not email and not clean_phone:
            error = "Please provide either an Email address or Mobile Number."
        elif email and ("@" not in email or "." not in email):
            error = "Please enter a valid email address."
        elif clean_phone and len(clean_phone) != 10:
            error = "Mobile number must be 10 digits."
        elif admin_key != ADMIN_REGISTRATION_KEY and admin_key != ADMIN_PASSWORD:
            error = "Invalid administrator authorization key. Contact the principal admin."
        elif not password or not confirm_password:
            error = "Please enter and confirm your password."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            conn = get_db()
            c = conn.cursor()

            if email:
                c.execute("SELECT id FROM users WHERE LOWER(email) = ?", (email,))
                if c.fetchone():
                    conn.close()
                    return render_template("admin_register.html", error="An account with this email already exists.")

            if clean_phone:
                c.execute("SELECT id FROM users WHERE phone = ?", (clean_phone,))
                if c.fetchone():
                    conn.close()
                    return render_template("admin_register.html", error="An account with this mobile number already exists.")

            db_email = email if email else None
            db_phone = clean_phone if clean_phone else None

            c.execute(
                """INSERT INTO users
                   (full_name, email, phone, password_hash, role, department, status)
                   VALUES (?, ?, ?, ?, 'admin', ?, 'active')""",
                (full_name, db_email, db_phone, generate_password_hash(password), department)
            )
            conn.commit()
            new_user_id = c.lastrowid
            conn.close()

            session["role"] = "admin"
            session["user_id"] = new_user_id
            return redirect(url_for("admin_dashboard"))

    return render_template("admin_register.html", error=error)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        identifier = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # 1. Fallback for default env credentials
        if identifier == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session.clear()
            session["role"] = "admin"
            return redirect(url_for("admin_dashboard"))

        # 2. Database lookup by Email, Mobile Number, or Admin Username
        clean_phone = re.sub(r"\D", "", identifier) if identifier else ""
        admin_email = f"{identifier}@queuex.internal"
        conn = get_db()
        c = conn.cursor()
        c.execute(
            """SELECT id, password_hash, status FROM users
               WHERE role = 'admin'
                 AND (
                     LOWER(email) = ?
                     OR LOWER(email) = ?
                     OR (phone = ? AND ? != '')
                     OR LOWER(full_name) = ?
                     OR LOWER(roll_no) = ?
                 )""",
            (identifier.lower(), admin_email.lower(), clean_phone, clean_phone, identifier.lower(), identifier.lower())
        )
        row = c.fetchone()
        conn.close()

        if row and row["password_hash"] and check_password_hash(row["password_hash"], password):
            if row["status"] != "active":
                error = "This administrator account is deactivated."
            else:
                session.clear()
                session["role"] = "admin"
                session["user_id"] = row["id"]
                return redirect(url_for("admin_dashboard"))
        else:
            error = "Invalid administrator username, email, phone number, or password."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("role", None)
    session.pop("user_id", None)
    return redirect(url_for("admin_login"))


def get_date_filter_clause(date_param, col="created_at"):
    """Return SQL condition and parameter list for date filtering across SQLite and PostgreSQL."""
    if is_postgres():
        if not date_param or date_param == "today":
            return f"{col}::DATE = CURRENT_DATE", []
        elif date_param == "yesterday":
            return f"{col}::DATE = (CURRENT_DATE - INTERVAL '1 day')", []
        elif date_param in ("7days", "week"):
            return f"{col}::DATE >= (CURRENT_DATE - INTERVAL '7 days')", []
        elif date_param in ("30days", "month"):
            return f"{col}::DATE >= (CURRENT_DATE - INTERVAL '30 days')", []
        elif date_param == "all":
            return "1=1", []
        elif re.match(r"^\d{4}-\d{2}-\d{2}$", date_param):
            return f"{col}::DATE = %s", [date_param]
        else:
            return f"{col}::DATE = CURRENT_DATE", []

    # SQLite
    if not date_param or date_param == "today":
        return f"date({col}) = date('now')", []
    elif date_param == "yesterday":
        return f"date({col}) = date('now', '-1 day')", []
    elif date_param in ("7days", "week"):
        return f"date({col}) >= date('now', '-7 days')", []
    elif date_param in ("30days", "month"):
        return f"date({col}) >= date('now', '-30 days')", []
    elif date_param == "all":
        return "1=1", []
    elif re.match(r"^\d{4}-\d{2}-\d{2}$", date_param):
        return f"date({col}) = ?", [date_param]
    else:
        return f"date({col}) = date('now')", []


@app.route("/admin")
def admin_dashboard():
    if not is_admin():
        return redirect(url_for("admin_login"))
    counters = get_all_counters(include_deactivated=True)
    return render_template("admin_dashboard.html", counters=counters)


@app.route("/api/admin/overview")
def api_admin_overview():
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    date_param = request.args.get("date", "today").strip()
    date_clause, date_params = get_date_filter_clause(date_param, "created_at")

    conn = get_db()
    c = conn.cursor()

    # Get all non-deleted counters from database
    c.execute("SELECT * FROM counters WHERE status != 'deleted' ORDER BY id ASC")
    db_counters = [dict(r) for r in c.fetchall()]

    result_counters = []
    for cdata in db_counters:
        slug = cdata["slug"]
        current_token = cdata["current_token"] or 0

        # Waiting count right now
        c.execute(
            "SELECT COUNT(*) as cnt FROM tokens WHERE counter_slug = ? AND status = 'waiting'",
            (slug,)
        )
        waiting_count = c.fetchone()["cnt"]

        # Served in selected date range
        sql_served = f"SELECT COUNT(*) as cnt FROM tokens WHERE counter_slug = ? AND status = 'served' AND {date_clause}"
        c.execute(sql_served, [slug] + date_params)
        served_count = c.fetchone()["cnt"]

        # Skipped in selected date range
        sql_skipped = f"SELECT COUNT(*) as cnt FROM tokens WHERE counter_slug = ? AND status = 'skipped' AND {date_clause}"
        c.execute(sql_skipped, [slug] + date_params)
        skipped_count = c.fetchone()["cnt"]

        # Total tokens in period
        sql_total = f"SELECT COUNT(*) as cnt FROM tokens WHERE counter_slug = ? AND {date_clause}"
        c.execute(sql_total, [slug] + date_params)
        total_tokens = c.fetchone()["cnt"]

        # Assigned operators
        c.execute("""
            SELECT u.full_name, op.employee_id
            FROM operators op
            JOIN users u ON u.id = op.user_id
            WHERE op.assigned_counter_id = ? AND op.active = 1
        """, (cdata["id"],))
        assigned_ops = [dict(op_r) for op_r in c.fetchall()]

        result_counters.append({
            "id": cdata["id"],
            "name": cdata["name"],
            "slug": slug,
            "current_token": current_token,
            "status": cdata.get("status") or "open",
            "location": cdata.get("location") or "Campus",
            "description": cdata.get("description") or "",
            "estimated_service_minutes": cdata.get("estimated_service_minutes") or 2,
            "waiting_count": waiting_count,
            "served_count": served_count,
            "served_today": served_count,
            "skipped_count": skipped_count,
            "total_tokens": total_tokens,
            "assigned_operators": assigned_ops
        })

    # Global KPIs
    c.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'student'")
    total_students = c.fetchone()["cnt"]
    c.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'student' AND status = 'active'")
    active_students = c.fetchone()["cnt"]

    c.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'operator'")
    total_employees = c.fetchone()["cnt"]
    c.execute("SELECT COUNT(*) as cnt FROM operators WHERE active = 1")
    active_employees = c.fetchone()["cnt"]

    c.execute("SELECT COUNT(*) as cnt FROM counters WHERE status != 'deleted'")
    total_counters = c.fetchone()["cnt"]
    c.execute("SELECT COUNT(*) as cnt FROM counters WHERE status = 'open'")
    active_counters = c.fetchone()["cnt"]

    # Token counts in period
    c.execute(f"SELECT COUNT(*) as cnt FROM tokens WHERE {date_clause}", date_params)
    total_tokens_period = c.fetchone()["cnt"]

    c.execute(f"SELECT COUNT(*) as cnt FROM tokens WHERE status = 'waiting' AND {date_clause}", date_params)
    waiting_tokens = c.fetchone()["cnt"]

    c.execute(f"SELECT COUNT(*) as cnt FROM tokens WHERE status = 'served' AND {date_clause}", date_params)
    served_tokens = c.fetchone()["cnt"]

    c.execute(f"SELECT COUNT(*) as cnt FROM tokens WHERE status = 'skipped' AND {date_clause}", date_params)
    skipped_tokens = c.fetchone()["cnt"]

    c.execute(f"SELECT COUNT(*) as cnt FROM tokens WHERE status = 'cancelled' AND {date_clause}", date_params)
    cancelled_tokens = c.fetchone()["cnt"]

    # Average wait time
    if is_postgres():
        c.execute(
            f"""SELECT AVG(EXTRACT(EPOCH FROM (served_at - created_at)) / 60) as avg_wait
                FROM tokens WHERE status = 'served' AND {date_clause}""",
            date_params
        )
    else:
        c.execute(
            f"""SELECT AVG((julianday(served_at) - julianday(created_at)) * 24 * 60) as avg_wait
                FROM tokens WHERE status = 'served' AND {date_clause}""",
            date_params
        )
    avg_row = c.fetchone()
    avg_wait = round(avg_row["avg_wait"], 1) if avg_row and avg_row["avg_wait"] else 0

    # Pending complaints
    c.execute("SELECT COUNT(*) as cnt FROM complaints WHERE status = 'pending'")
    pending_complaints = c.fetchone()["cnt"]

    conn.close()

    return jsonify({
        "counters": result_counters,
        "kpis": {
            "total_students": total_students,
            "active_students": active_students,
            "total_employees": total_employees,
            "active_employees": active_employees,
            "total_counters": total_counters,
            "active_counters": active_counters,
            "total_tokens_period": total_tokens_period,
            "tokens_today": total_tokens_period,
            "waiting_tokens": waiting_tokens,
            "served_tokens": served_tokens,
            "skipped_tokens": skipped_tokens,
            "cancelled_tokens": cancelled_tokens,
            "avg_wait": avg_wait,
            "pending_complaints": pending_complaints,
            "filter_date": date_param
        }
    })


@app.route("/api/admin/analytics")
def api_admin_analytics():
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    date_param = request.args.get("date", "today").strip()
    date_clause, date_params = get_date_filter_clause(date_param, "created_at")

    conn = get_db()
    c = conn.cursor()

    # Tokens per counter
    sql_per_counter = f"""
        SELECT co.id, co.name, co.slug,
               (SELECT COUNT(*) FROM tokens t WHERE t.counter_slug = co.slug AND {date_clause}) as count
        FROM counters co
        WHERE co.status != 'deleted'
        ORDER BY count DESC, co.id ASC
    """
    c.execute(sql_per_counter, date_params)
    tokens_per_counter = [dict(r) for r in c.fetchall()]

    # Peak hours
    hr_expr = "TO_CHAR(created_at, 'HH24')" if is_postgres() else "strftime('%H', created_at)"
    sql_peak = f"""
        SELECT {hr_expr} as hr, COUNT(*) as cnt
        FROM tokens
        WHERE {date_clause}
        GROUP BY hr
        ORDER BY hr ASC
    """
    c.execute(sql_peak, date_params)
    peak_rows = {int(r["hr"]): r["cnt"] for r in c.fetchall() if r["hr"] is not None}
    peak_hours = []
    for h in range(8, 19):
        cnt = peak_rows.get(h, 0)
        am_pm = "AM" if h < 12 else "PM"
        display_h = h if h <= 12 else h - 12
        if display_h == 0:
            display_h = 12
        peak_hours.append({
            "hour": f"{display_h:02d}:00 {am_pm}",
            "raw_hour": f"{h:02d}:00",
            "count": cnt
        })

    # Status breakdown
    sql_status = f"""
        SELECT status, COUNT(*) as cnt
        FROM tokens
        WHERE {date_clause}
        GROUP BY status
    """
    c.execute(sql_status, date_params)
    status_map = {"waiting": 0, "served": 0, "skipped": 0, "cancelled": 0}
    for r in c.fetchall():
        if r["status"] in status_map:
            status_map[r["status"]] = r["cnt"]

    # Department-wise analytics
    date_clause_dept, date_params_dept = get_date_filter_clause(date_param, col="t.created_at")
    sql_dept = f"""
        SELECT COALESCE(u.department, 'General Academic') as department,
               COUNT(t.id) as token_count,
               COUNT(DISTINCT t.user_id) as student_count
        FROM tokens t
        LEFT JOIN users u ON (t.user_id = u.id OR LOWER(t.roll_no) = LOWER(u.roll_no))
        WHERE {date_clause_dept}
        GROUP BY department
        ORDER BY token_count DESC
    """
    c.execute(sql_dept, date_params_dept)
    dept_rows = [dict(r) for r in c.fetchall()]

    if not dept_rows:
        c.execute("SELECT DISTINCT department FROM users WHERE role = 'student' AND department IS NOT NULL")
        for r in c.fetchall():
            dept_rows.append({"department": r["department"], "token_count": 0, "student_count": 0})

    # Average wait time
    avg_expr = "AVG(EXTRACT(EPOCH FROM (served_at - created_at)) / 60)" if is_postgres() else "AVG((julianday(served_at) - julianday(created_at)) * 24 * 60)"
    sql_avg = f"""
        SELECT {avg_expr} as avg_wait
        FROM tokens
        WHERE status = 'served' AND {date_clause}
    """
    c.execute(sql_avg, date_params)
    avg_row = c.fetchone()
    avg_wait = round(avg_row["avg_wait"], 1) if avg_row and avg_row["avg_wait"] else 0

    # Total tokens in period
    sql_total = f"SELECT COUNT(*) as cnt FROM tokens WHERE {date_clause}"
    c.execute(sql_total, date_params)
    total_period = c.fetchone()["cnt"]

    # Busiest counter
    busiest = max(tokens_per_counter, key=lambda x: x["count"]) if tokens_per_counter else None

    # Peak hour summary
    peak_active = max(peak_hours, key=lambda x: x["count"]) if peak_hours else None
    if peak_active and peak_active["count"] > 0:
        peak_summary = f"{peak_active['hour']} ({peak_active['count']} tokens)"
    else:
        peak_summary = "Normal Traffic"

    conn.close()

    return jsonify({
        "tokens_per_counter": tokens_per_counter,
        "peak_hours": peak_hours,
        "peak_summary": peak_summary,
        "status_distribution": status_map,
        "department_analytics": dept_rows,
        "avg_wait": avg_wait,
        "total_today": total_period,
        "total_period": total_period,
        "busiest_counter": busiest["name"] if busiest and busiest["count"] > 0 else "N/A",
        "filter_date": date_param
    })


@app.route("/api/admin/students")
def api_admin_students():
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    query = request.args.get("q", "").strip()
    dept = request.args.get("dept", "").strip()

    conn = get_db()
    c = conn.cursor()

    sql = """
        SELECT u.id, u.student_uid, u.roll_no, u.full_name, u.email, u.phone, 
               u.department, u.semester, u.status, u.created_at,
               (SELECT COUNT(*) FROM tokens WHERE user_id = u.id) as total_tokens,
               (SELECT token_number FROM tokens WHERE user_id = u.id AND status = 'waiting' ORDER BY id DESC LIMIT 1) as active_token,
               (SELECT counter_slug FROM tokens WHERE user_id = u.id AND status = 'waiting' ORDER BY id DESC LIMIT 1) as active_counter
        FROM users u
        WHERE u.role = 'student'
    """
    params = []
    if dept and dept != "all":
        sql += " AND u.department = ?"
        params.append(dept)

    if query:
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search_pattern = f"%{escaped_query}%"
        sql += """ AND (
            u.full_name LIKE ? ESCAPE '\\' 
            OR u.student_uid LIKE ? ESCAPE '\\' 
            OR u.roll_no LIKE ? ESCAPE '\\' 
            OR u.email LIKE ? ESCAPE '\\' 
            OR u.phone LIKE ? ESCAPE '\\'
        )"""
        params.extend([search_pattern] * 5)

    sql += " ORDER BY u.student_uid ASC, u.id ASC"

    c.execute(sql, params)
    students = [dict(r) for r in c.fetchall()]

    c.execute("SELECT DISTINCT department FROM users WHERE role = 'student' AND department IS NOT NULL ORDER BY department")
    departments = [r["department"] for r in c.fetchall()]

    conn.close()

    return jsonify({
        "students": students,
        "total_count": len(students),
        "departments": departments,
        "college": PRIMARY_COLLEGE
    })


@app.route("/api/admin/student/<int:user_id>/tokens")
def api_admin_student_tokens(user_id):
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, student_uid, roll_no, full_name, email, phone, department, semester FROM users WHERE id = ?", (user_id,))
    student = c.fetchone()
    if not student:
        conn.close()
        return jsonify({"error": "Student not found"}), 404

    c.execute("SELECT * FROM tokens WHERE user_id = ? ORDER BY id DESC", (user_id,))
    tokens = [dict(r) for r in c.fetchall()]
    for t in tokens:
        t["counter_name"] = get_counter_name(t["counter_slug"])

    conn.close()
    return jsonify({
        "student": dict(student),
        "tokens": tokens
    })


@app.route("/api/admin/students/add", methods=["POST"])
def api_admin_add_student():
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    full_name = request.form.get("full_name", "").strip()
    roll_no = request.form.get("roll_no", "").strip()
    department = request.form.get("department", "").strip() or "General"
    semester = request.form.get("semester", "1st").strip()
    student_uid = request.form.get("student_uid", "").strip().upper()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    password = request.form.get("password", "").strip() or "student123"

    if not full_name or not roll_no:
        return jsonify({"error": "Full Name and Roll Number are required"}), 400

    clean_phone = re.sub(r"\D", "", phone) if phone else ""
    if clean_phone and len(clean_phone) != 10:
        return jsonify({"error": "Phone number must be 10 digits"}), 400

    conn = get_db()
    c = conn.cursor()

    # Generate student_uid if not provided
    if not student_uid:
        c.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'student'")
        seq = c.fetchone()["cnt"] + 1
        dept_code = department[:2].upper() if len(department) >= 2 else "ST"
        student_uid = f"AIT-24-{dept_code}{seq:03d}"

    # Check for duplicate student_uid, roll_no, email, phone
    c.execute(
        """SELECT id FROM users WHERE UPPER(student_uid) = ? OR LOWER(roll_no) = ?
           OR (LOWER(email) = ? AND ? != '') OR (phone = ? AND ? != '')""",
        (student_uid.upper(), roll_no.lower(), email, email, clean_phone, clean_phone)
    )
    if c.fetchone():
        conn.close()
        return jsonify({"error": "A student with this Student ID, Roll No, Email, or Phone already exists."}), 400

    db_email = email if email else f"{student_uid.lower().replace('-', '_')}@ait.edu"
    db_phone = clean_phone if clean_phone else None

    c.execute(
        """INSERT INTO users
           (college_id, student_uid, full_name, email, phone, password_hash, role, roll_no, department, semester, status)
           VALUES (?, ?, ?, ?, ?, ?, 'student', ?, ?, ?, 'active')""",
        (1, student_uid, full_name, db_email, db_phone, generate_password_hash(password), roll_no, department, semester)
    )
    conn.commit()
    new_id = c.lastrowid
    conn.close()

    return jsonify({
        "success": True,
        "message": f"Student '{full_name}' ({student_uid}) added successfully.",
        "student": {
            "id": new_id,
            "student_uid": student_uid,
            "full_name": full_name,
            "roll_no": roll_no,
            "department": department,
            "semester": semester,
            "email": db_email,
            "phone": db_phone or "-"
        }
    })


@app.route("/api/admin/students/<int:user_id>/delete", methods=["POST"])
def api_admin_delete_student(user_id):
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, full_name, student_uid, role FROM users WHERE id = ?", (user_id,))
    target = c.fetchone()
    if not target:
        conn.close()
        return jsonify({"error": "Student not found"}), 404

    if target["role"] != "student":
        conn.close()
        return jsonify({"error": "Cannot delete non-student account via this endpoint"}), 400

    c.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))
    c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": f"Student '{target['full_name']}' ({target['student_uid'] or target['id']}) has been removed."
    })


@app.route("/api/admin/employees")
def api_admin_employees():
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT u.id as user_id, u.full_name, u.email, u.phone, u.status, u.created_at,
               op.id as operator_id, op.employee_id, op.active,
               co.name as counter_name, co.slug as counter_slug,
               (SELECT COUNT(*) FROM tokens WHERE completed_by = u.id AND date(created_at) = date('now')) as served_today
        FROM users u
        LEFT JOIN operators op ON op.user_id = u.id
        LEFT JOIN counters co ON co.id = op.assigned_counter_id
        WHERE u.role = 'operator'
        ORDER BY u.id ASC
    """)
    employees = [dict(r) for r in c.fetchall()]
    conn.close()

    return jsonify({"employees": employees, "counters": COUNTERS})


@app.route("/api/admin/employees/add", methods=["POST"])
def api_admin_add_employee():
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    full_name = request.form.get("full_name", "").strip()
    employee_id = request.form.get("employee_id", "").strip().upper()
    assigned_counter = request.form.get("assigned_counter", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    password = request.form.get("password", "").strip()

    if not full_name or not employee_id or not password:
        return jsonify({"error": "Full Name, Employee ID, and Password are required."}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    clean_phone = re.sub(r"\D", "", phone) if phone else ""
    if clean_phone and len(clean_phone) != 10:
        return jsonify({"error": "Mobile number must be 10 digits."}), 400

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT id FROM operators WHERE employee_id = ?", (employee_id,))
    if c.fetchone():
        conn.close()
        return jsonify({"error": f"An employee with ID '{employee_id}' already exists."}), 400

    db_email = email if email else f"staff_{employee_id.lower().replace('-', '_')}@queuex.internal"
    c.execute("SELECT id FROM users WHERE LOWER(email) = ?", (db_email,))
    if c.fetchone():
        conn.close()
        return jsonify({"error": "An account with this email already exists."}), 400

    counter_id = None
    if assigned_counter:
        c.execute("SELECT id FROM counters WHERE slug = ?", (assigned_counter,))
        crow = c.fetchone()
        if crow:
            counter_id = crow["id"]

    c.execute(
        """INSERT INTO users
           (college_id, full_name, email, phone, password_hash, role, status)
           VALUES (?, ?, ?, ?, ?, 'operator', 'active')""",
        (1, full_name, db_email, clean_phone or None, generate_password_hash(password))
    )
    user_id = c.lastrowid

    c.execute(
        """INSERT INTO operators
           (user_id, employee_id, assigned_counter_id, active)
           VALUES (?, ?, ?, 1)""",
        (user_id, employee_id, counter_id)
    )
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": f"Operator '{full_name}' ({employee_id}) created successfully."
    })


@app.route("/api/admin/employees/<int:user_id>/delete", methods=["POST"])
def api_admin_delete_employee(user_id):
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, full_name, role, email FROM users WHERE id = ?", (user_id,))
    target = c.fetchone()
    if not target:
        conn.close()
        return jsonify({"error": "Employee not found"}), 404

    if target["role"] != "operator":
        conn.close()
        return jsonify({"error": "Cannot delete non-operator staff via this endpoint"}), 400

    c.execute("DELETE FROM operators WHERE user_id = ?", (user_id,))
    c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": f"Operator '{target['full_name']}' has been removed."
    })



# ---------- ADMIN COUNTERS MANAGEMENT ----------

@app.route("/api/admin/counters")
def api_admin_counters():
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT co.*,
               (SELECT COUNT(*) FROM tokens WHERE counter_slug = co.slug AND status = 'waiting') as waiting_count,
               (SELECT COUNT(*) FROM tokens WHERE counter_slug = co.slug AND status = 'served' AND date(created_at) = date('now')) as served_today,
               (SELECT COUNT(*) FROM tokens WHERE counter_slug = co.slug) as total_tokens
        FROM counters co
        WHERE co.status != 'deleted'
        ORDER BY co.id ASC
    """)
    counters_list = []
    for r in c.fetchall():
        item = dict(r)
        c.execute("""
            SELECT u.full_name, op.employee_id
            FROM operators op
            JOIN users u ON u.id = op.user_id
            WHERE op.assigned_counter_id = ? AND op.active = 1
        """, (item["id"],))
        item["assigned_operators"] = [dict(op_r) for op_r in c.fetchall()]
        counters_list.append(item)
    conn.close()
    return jsonify({"counters": counters_list, "total_count": len(counters_list)})


@app.route("/api/admin/counters/add", methods=["POST"])
def api_admin_add_counter():
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or request.form
    name = (payload.get("name") or "").strip()
    slug = (payload.get("slug") or "").strip()
    location = (payload.get("location") or "").strip()
    description = (payload.get("description") or "").strip()
    operating_hours = (payload.get("operating_hours") or "09:00 AM - 05:00 PM").strip()
    est_minutes = int(payload.get("estimated_service_minutes") or 2)

    if not name:
        return jsonify({"error": "Counter name is required"}), 400

    if not slug:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM counters WHERE slug = ? OR LOWER(name) = ?", (slug, name.lower()))
    if c.fetchone():
        conn.close()
        return jsonify({"error": f"A counter with name '{name}' or slug '{slug}' already exists."}), 400

    c.execute("""
        INSERT INTO counters (name, slug, current_token, location, description, operating_hours, estimated_service_minutes, status)
        VALUES (?, ?, 0, ?, ?, ?, ?, 'open')
    """, (name, slug, location, description, operating_hours, est_minutes))
    conn.commit()
    new_id = c.lastrowid
    conn.close()

    return jsonify({
        "success": True,
        "message": f"Counter '{name}' added successfully.",
        "counter_id": new_id,
        "counter": {
            "id": new_id,
            "name": name,
            "slug": slug,
            "location": location,
            "status": "open"
        }
    })


@app.route("/api/admin/counters/<int:counter_id>/edit", methods=["POST"])
def api_admin_edit_counter(counter_id):
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or request.form
    name = (payload.get("name") or "").strip()
    location = (payload.get("location") or "").strip()
    description = (payload.get("description") or "").strip()
    operating_hours = (payload.get("operating_hours") or "").strip()
    est_minutes = payload.get("estimated_service_minutes")

    if not name:
        return jsonify({"error": "Counter name cannot be empty"}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, slug FROM counters WHERE id = ?", (counter_id,))
    target = c.fetchone()
    if not target:
        conn.close()
        return jsonify({"error": "Counter not found"}), 404

    c.execute("SELECT id FROM counters WHERE LOWER(name) = ? AND id != ?", (name.lower(), counter_id))
    if c.fetchone():
        conn.close()
        return jsonify({"error": f"Another counter with name '{name}' already exists."}), 400

    c.execute("""
        UPDATE counters
        SET name = ?, location = ?, description = ?,
            operating_hours = COALESCE(NULLIF(?, ''), operating_hours),
            estimated_service_minutes = COALESCE(?, estimated_service_minutes)
        WHERE id = ?
    """, (name, location, description, operating_hours, est_minutes, counter_id))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": f"Counter '{name}' updated successfully."})


@app.route("/api/admin/counters/<int:counter_id>/toggle-status", methods=["POST"])
def api_admin_toggle_counter_status(counter_id):
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or request.form
    new_status = (payload.get("status") or "").strip().lower()

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, slug, status FROM counters WHERE id = ?", (counter_id,))
    target = c.fetchone()
    if not target:
        conn.close()
        return jsonify({"error": "Counter not found"}), 404

    if not new_status:
        new_status = "deactivated" if target["status"] != "deactivated" else "open"

    if new_status not in ("open", "paused", "closed", "deactivated"):
        conn.close()
        return jsonify({"error": "Invalid status value"}), 400

    c.execute("UPDATE counters SET status = ? WHERE id = ?", (new_status, counter_id))
    conn.commit()
    conn.close()

    broadcast_queue_update(target["slug"])

    return jsonify({
        "success": True,
        "message": f"Counter '{target['name']}' status set to {new_status.upper()}.",
        "status": new_status,
        "counter_id": counter_id
    })


@app.route("/api/admin/counters/<int:counter_id>/delete", methods=["POST"])
def api_admin_delete_counter(counter_id):
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, slug FROM counters WHERE id = ?", (counter_id,))
    target = c.fetchone()
    if not target:
        conn.close()
        return jsonify({"error": "Counter not found"}), 404

    c.execute("UPDATE counters SET status = 'deleted' WHERE id = ?", (counter_id,))
    c.execute("UPDATE operators SET assigned_counter_id = NULL WHERE assigned_counter_id = ?", (counter_id,))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": f"Counter '{target['name']}' removed."})


# ---------- ADMIN STUDENTS & OPERATORS EXTENSIONS ----------

@app.route("/api/admin/students/<int:user_id>/edit", methods=["POST"])
def api_admin_edit_student(user_id):
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or request.form
    full_name = (payload.get("full_name") or "").strip()
    roll_no = (payload.get("roll_no") or "").strip()
    department = (payload.get("department") or "").strip()
    semester = (payload.get("semester") or "").strip()
    phone = (payload.get("phone") or "").strip()
    email = (payload.get("email") or "").strip().lower()

    if not full_name or not roll_no:
        return jsonify({"error": "Full Name and Roll Number are required."}), 400

    clean_phone = re.sub(r"\D", "", phone) if phone else None
    if clean_phone and len(clean_phone) != 10:
        return jsonify({"error": "Phone number must be 10 digits."}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE id = ? AND role = 'student'", (user_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({"error": "Student not found"}), 404

    c.execute("SELECT id FROM users WHERE LOWER(roll_no) = ? AND id != ?", (roll_no.lower(), user_id))
    if c.fetchone():
        conn.close()
        return jsonify({"error": f"Another student with Roll No '{roll_no}' already exists."}), 400

    c.execute("""
        UPDATE users
        SET full_name = ?, roll_no = ?, department = COALESCE(NULLIF(?, ''), department),
            semester = COALESCE(NULLIF(?, ''), semester),
            phone = COALESCE(?, phone),
            email = COALESCE(NULLIF(?, ''), email),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (full_name, roll_no, department, semester, clean_phone, email, user_id))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": f"Student '{full_name}' updated successfully."})


@app.route("/api/admin/students/<int:user_id>/toggle-status", methods=["POST"])
def api_admin_toggle_student_status(user_id):
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, full_name, status FROM users WHERE id = ? AND role = 'student'", (user_id,))
    target = c.fetchone()
    if not target:
        conn.close()
        return jsonify({"error": "Student not found"}), 404

    new_status = "deactivated" if target["status"] == "active" else "active"
    c.execute("UPDATE users SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_status, user_id))
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": f"Student '{target['full_name']}' is now {new_status}.",
        "status": new_status
    })


@app.route("/api/admin/employees/<int:user_id>/edit", methods=["POST"])
def api_admin_edit_employee(user_id):
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or request.form
    full_name = (payload.get("full_name") or "").strip()
    employee_id = (payload.get("employee_id") or "").strip().upper()
    assigned_counter = (payload.get("assigned_counter") or "").strip()
    phone = (payload.get("phone") or "").strip()
    email = (payload.get("email") or "").strip().lower()

    if not full_name:
        return jsonify({"error": "Full Name is required."}), 400

    clean_phone = re.sub(r"\D", "", phone) if phone else None
    if clean_phone and len(clean_phone) != 10:
        return jsonify({"error": "Phone number must be 10 digits."}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE id = ? AND role = 'operator'", (user_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({"error": "Employee not found"}), 404

    counter_id = None
    if assigned_counter:
        c.execute("SELECT id FROM counters WHERE slug = ?", (assigned_counter,))
        crow = c.fetchone()
        if crow:
            counter_id = crow["id"]

    c.execute("""
        UPDATE users
        SET full_name = ?, phone = COALESCE(?, phone), email = COALESCE(NULLIF(?, ''), email),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (full_name, clean_phone, email, user_id))

    if employee_id:
        c.execute("""
            UPDATE operators
            SET employee_id = ?, assigned_counter_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (employee_id, counter_id, user_id))
    else:
        c.execute("""
            UPDATE operators
            SET assigned_counter_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (counter_id, user_id))

    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": f"Operator '{full_name}' updated successfully."})


@app.route("/api/admin/employees/<int:user_id>/toggle-status", methods=["POST"])
def api_admin_toggle_employee_status(user_id):
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT u.id, u.full_name, u.status as user_status, op.active as op_active
        FROM users u
        LEFT JOIN operators op ON op.user_id = u.id
        WHERE u.id = ? AND u.role = 'operator'
    """, (user_id,))
    target = c.fetchone()
    if not target:
        conn.close()
        return jsonify({"error": "Employee not found"}), 404

    new_active = 0 if target["op_active"] == 1 else 1
    new_user_status = "active" if new_active == 1 else "deactivated"

    c.execute("UPDATE operators SET active = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (new_active, user_id))
    c.execute("UPDATE users SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_user_status, user_id))
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": f"Operator '{target['full_name']}' is now {'active' if new_active == 1 else 'deactivated'}.",
        "active": new_active
    })


# ---------- ADMIN COMPLAINTS & FEEDBACK MANAGEMENT ----------

@app.route("/api/admin/complaints")
def api_admin_complaints():
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    status_filter = request.args.get("status", "all").strip().lower()
    q = request.args.get("q", "").strip()

    conn = get_db()
    c = conn.cursor()

    sql = "SELECT * FROM complaints WHERE 1=1"
    params = []

    if status_filter in ("pending", "resolved"):
        sql += " AND status = ?"
        params.append(status_filter)

    if q:
        escaped_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql += """ AND (
            student_name LIKE ? ESCAPE '\\' 
            OR roll_no LIKE ? ESCAPE '\\' 
            OR subject LIKE ? ESCAPE '\\' 
            OR message LIKE ? ESCAPE '\\'
        )"""
        pattern = f"%{escaped_q}%"
        params.extend([pattern, pattern, pattern, pattern])

    sql += " ORDER BY created_at DESC"

    c.execute(sql, params)
    complaints = []
    for r in c.fetchall():
        item = dict(r)
        item["counter_name"] = get_counter_name(item["counter_slug"]) if item.get("counter_slug") else "General / Campus"
        complaints.append(item)

    c.execute("SELECT COUNT(*) as cnt FROM complaints WHERE status = 'pending'")
    pending_cnt = c.fetchone()["cnt"]

    c.execute("SELECT COUNT(*) as cnt FROM complaints WHERE status = 'resolved'")
    resolved_cnt = c.fetchone()["cnt"]

    conn.close()

    return jsonify({
        "complaints": complaints,
        "total_count": len(complaints),
        "pending_count": pending_cnt,
        "resolved_count": resolved_cnt
    })


@app.route("/api/admin/complaints/<int:complaint_id>/reply", methods=["POST"])
def api_admin_reply_complaint(complaint_id):
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or request.form
    reply = (payload.get("admin_reply") or "").strip()
    status = (payload.get("status") or "resolved").strip().lower()

    if not reply:
        return jsonify({"error": "Resolution / reply text is required."}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,))
    target = c.fetchone()
    if not target:
        conn.close()
        return jsonify({"error": "Complaint not found"}), 404

    now_iso = datetime.now().isoformat(timespec="seconds")
    c.execute("""
        UPDATE complaints
        SET admin_reply = ?, status = ?, resolved_at = ?, updated_at = ?
        WHERE id = ?
    """, (reply, status, now_iso, now_iso, complaint_id))
    conn.commit()

    if target["user_id"]:
        create_notification(
            target["user_id"],
            "Feedback Resolved",
            f"Administration responded to '{target['subject']}': {reply}",
            "success"
        )

    conn.close()

    return jsonify({
        "success": True,
        "message": f"Complaint #{complaint_id} marked as {status.upper()}.",
        "status": status
    })


# ---------- SOCKET.IO EVENTS ----------

@socketio.on("join")
def handle_join(data):
    if not isinstance(data, dict):
        return False
    room = data.get("room")
    if not room or not isinstance(room, str):
        return False

    # 1. Admin channel protection
    if room == "admin_global":
        if not is_admin():
            emit("error", {"message": "Unauthorized room access"})
            return False

    # 2. Private student notification channel
    elif room.startswith("user_"):
        target_uid = room[5:]
        student_user = current_student()
        if is_admin():
            pass
        elif student_user and str(student_user["id"]) == target_uid:
            pass
        else:
            emit("error", {"message": "Unauthorized user room access"})
            return False

    # 3. Operator channel protection
    elif room.startswith("operator_"):
        if not (is_operator() or is_admin()):
            emit("error", {"message": "Unauthorized operator room access"})
            return False

    join_room(room)
    return True


@socketio.on("leave")
def handle_leave(data):
    if isinstance(data, dict):
        room = data.get("room")
        if room and isinstance(room, str):
            leave_room(room)


# Auto-initialize database on application import (ensures Gunicorn startup initializes SQLite tables)
try:
    init_db()
except Exception:
    pass


# ---------- RUN APP ----------
if __name__ == "__main__":
    init_db()
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", "5000"))
    socketio.run(app, debug=debug, port=port, host="0.0.0.0", allow_unsafe_werkzeug=True)
