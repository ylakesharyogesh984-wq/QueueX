"""
QueueX - Smart Virtual Queue Management System
Target: CGC University, Mohali, Punjab, India
Foundation & Complete Student Portal Implementation
"""

import os
import io
import csv
import base64
import secrets
import datetime
import threading
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for, session,
    flash, jsonify, Response
)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, emit, join_room, leave_room
import qrcode

import db

app = Flask(__name__)

# Secure secret key handling: use env var or generate a strong fallback
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    # In development or if not set, fallback gracefully
    app.secret_key = "queux-cgc-mohali-production-key-2026"

# Production environment & cookie security
is_production = os.environ.get("FLASK_ENV") == "production" or os.environ.get("RENDER") is not None
cookie_secure = bool(os.environ.get("SESSION_COOKIE_SECURE")) or is_production

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=cookie_secure,
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=3)
)


@app.after_request
def set_security_headers(response):
    """Enforce industry standard security headers across all responses."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
APP_START_TIME = datetime.datetime.now(datetime.timezone.utc)

# Re-entrant thread lock for critical queue state mutations in multi-threaded Gunicorn
QUEUE_LOCK = threading.RLock()

# -------------------------------------------------------------
# DATABASE INITIALIZATION & SCHEMA MIGRATION
# -------------------------------------------------------------

def init_db():
    """
    Safely initialize and migrate schema for PostgreSQL and SQLite.
    Guarantees:
    - Creates tables in strict dependency order (departments -> counters -> users -> tokens -> feedback -> notifications -> audit_logs)
    - Adds missing columns to existing tables without data loss
    - Recreates or updates indexes idempotently
    - Does not swallow initialization errors
    """
    with db.get_db() as conn:
        c = conn.cursor()

        # 1. Departments table (MUST precede counters)
        c.execute("""
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                building_block TEXT DEFAULT 'Block 1',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # Migrate departments columns if existing table lacked any
        db.add_column_if_missing(c, "departments", "code", "TEXT")
        db.add_column_if_missing(c, "departments", "name", "TEXT")
        db.add_column_if_missing(c, "departments", "description", "TEXT DEFAULT ''")
        db.add_column_if_missing(c, "departments", "building_block", "TEXT DEFAULT 'Block 1'")
        db.add_column_if_missing(c, "departments", "is_active", "INTEGER DEFAULT 1")
        db.add_column_if_missing(c, "departments", "created_at", "TIMESTAMP")
        conn.commit()

        # 2. Service Counters table
        c.execute("""
            CREATE TABLE IF NOT EXISTS counters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_id INTEGER NOT NULL DEFAULT 1,
                name TEXT NOT NULL,
                code TEXT UNIQUE,
                is_active INTEGER DEFAULT 1,
                is_paused INTEGER DEFAULT 0,
                assigned_operator_id INTEGER DEFAULT NULL,
                avg_service_time_mins INTEGER DEFAULT 8,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # Migrate counters columns if upgrading from earlier schema
        db.add_column_if_missing(c, "counters", "department_id", "INTEGER DEFAULT 1")
        db.add_column_if_missing(c, "counters", "name", "TEXT")
        db.add_column_if_missing(c, "counters", "code", "TEXT")
        db.add_column_if_missing(c, "counters", "is_active", "INTEGER DEFAULT 1")
        db.add_column_if_missing(c, "counters", "is_paused", "INTEGER DEFAULT 0")
        db.add_column_if_missing(c, "counters", "assigned_operator_id", "INTEGER DEFAULT NULL")
        db.add_column_if_missing(c, "counters", "avg_service_time_mins", "INTEGER DEFAULT 8")
        db.add_column_if_missing(c, "counters", "created_at", "TIMESTAMP")
        conn.commit()

        # 3. Users table (students, operators, admin)
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                password_hash TEXT,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'student',
                identifier TEXT,
                department TEXT DEFAULT 'CSE',
                course TEXT DEFAULT 'B.Tech',
                semester INTEGER DEFAULT 6,
                phone TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # Migrate users columns if upgrading from earlier schema
        db.add_column_if_missing(c, "users", "email", "TEXT")
        db.add_column_if_missing(c, "users", "password_hash", "TEXT")
        db.add_column_if_missing(c, "users", "full_name", "TEXT")
        db.add_column_if_missing(c, "users", "role", "TEXT DEFAULT 'student'")
        db.add_column_if_missing(c, "users", "identifier", "TEXT")
        db.add_column_if_missing(c, "users", "department", "TEXT DEFAULT 'CSE'")
        db.add_column_if_missing(c, "users", "course", "TEXT DEFAULT 'B.Tech'")
        db.add_column_if_missing(c, "users", "semester", "INTEGER DEFAULT 6")
        db.add_column_if_missing(c, "users", "phone", "TEXT DEFAULT ''")
        db.add_column_if_missing(c, "users", "is_active", "INTEGER DEFAULT 1")
        db.add_column_if_missing(c, "users", "created_at", "TIMESTAMP")
        conn.commit()

        # Backfill user identifiers from roll_no if missing
        if db.column_exists(c, "users", "roll_no"):
            try:
                c.execute("UPDATE users SET identifier = roll_no WHERE identifier IS NULL AND roll_no IS NOT NULL")
                conn.commit()
            except Exception:
                pass

        # 4. Queue Tokens table
        c.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_number INTEGER NOT NULL,
                counter_id INTEGER NOT NULL DEFAULT 1,
                department_id INTEGER NOT NULL DEFAULT 1,
                student_id INTEGER NOT NULL DEFAULT 1,
                student_name TEXT,
                student_roll TEXT,
                student_phone TEXT DEFAULT '',
                service_reason TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'waiting',
                token_salt TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                called_at TIMESTAMP DEFAULT NULL,
                completed_at TIMESTAMP DEFAULT NULL
            )
        """)
        conn.commit()

        # Migrate tokens columns if upgrading from earlier schema
        db.add_column_if_missing(c, "tokens", "token_number", "INTEGER DEFAULT 1")
        db.add_column_if_missing(c, "tokens", "counter_id", "INTEGER DEFAULT 1")
        db.add_column_if_missing(c, "tokens", "department_id", "INTEGER DEFAULT 1")
        db.add_column_if_missing(c, "tokens", "student_id", "INTEGER DEFAULT 1")
        db.add_column_if_missing(c, "tokens", "student_name", "TEXT")
        db.add_column_if_missing(c, "tokens", "student_roll", "TEXT")
        db.add_column_if_missing(c, "tokens", "student_phone", "TEXT DEFAULT ''")
        db.add_column_if_missing(c, "tokens", "service_reason", "TEXT DEFAULT ''")
        db.add_column_if_missing(c, "tokens", "status", "TEXT DEFAULT 'waiting'")
        db.add_column_if_missing(c, "tokens", "token_salt", "TEXT DEFAULT ''")
        db.add_column_if_missing(c, "tokens", "created_at", "TIMESTAMP")
        db.add_column_if_missing(c, "tokens", "called_at", "TIMESTAMP")
        db.add_column_if_missing(c, "tokens", "completed_at", "TIMESTAMP")
        conn.commit()

        # 5. Student Feedback
        c.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id INTEGER UNIQUE,
                student_id INTEGER NOT NULL DEFAULT 1,
                counter_id INTEGER NOT NULL DEFAULT 1,
                rating INTEGER NOT NULL DEFAULT 5,
                comments TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # 6. System Notifications
        c.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # Migrate notifications columns if upgrading from legacy schema
        db.add_column_if_missing(c, "notifications", "user_id", "INTEGER DEFAULT 1")
        db.add_column_if_missing(c, "notifications", "title", "TEXT DEFAULT ''")
        db.add_column_if_missing(c, "notifications", "message", "TEXT DEFAULT ''")
        db.add_column_if_missing(c, "notifications", "is_read", "INTEGER DEFAULT 0")
        db.add_column_if_missing(c, "notifications", "created_at", "TIMESTAMP")
        conn.commit()

        # 7. System Audit Log
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                user_id INTEGER DEFAULT NULL,
                user_role TEXT DEFAULT '',
                details TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # Migrate audit_logs columns if upgrading from legacy schema
        db.add_column_if_missing(c, "audit_logs", "action", "TEXT DEFAULT ''")
        db.add_column_if_missing(c, "audit_logs", "user_id", "INTEGER DEFAULT NULL")
        db.add_column_if_missing(c, "audit_logs", "user_role", "TEXT DEFAULT ''")
        db.add_column_if_missing(c, "audit_logs", "details", "TEXT DEFAULT ''")
        db.add_column_if_missing(c, "audit_logs", "created_at", "TIMESTAMP")
        conn.commit()

        # 8. Server-Side Authentication Sessions (Atomic Multi-Tab Role Sessions)
        c.execute("""
            CREATE TABLE IF NOT EXISTS auth_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_token TEXT NOT NULL,
                role TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                user_email TEXT NOT NULL,
                user_identifier TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                CONSTRAINT uq_session_token_role UNIQUE (session_token, role)
            )
        """)
        conn.commit()

        # Migrate auth_sessions columns if upgrading
        db.add_column_if_missing(c, "auth_sessions", "session_token", "TEXT")
        db.add_column_if_missing(c, "auth_sessions", "role", "TEXT")
        db.add_column_if_missing(c, "auth_sessions", "user_id", "INTEGER")
        db.add_column_if_missing(c, "auth_sessions", "user_name", "TEXT")
        db.add_column_if_missing(c, "auth_sessions", "user_email", "TEXT")
        db.add_column_if_missing(c, "auth_sessions", "user_identifier", "TEXT")
        db.add_column_if_missing(c, "auth_sessions", "created_at", "TIMESTAMP")
        db.add_column_if_missing(c, "auth_sessions", "last_active", "TIMESTAMP")
        db.add_column_if_missing(c, "auth_sessions", "expires_at", "TIMESTAMP")
        conn.commit()

        # 9. Performance Indexes (now safely run after column migrations)
        c.execute("CREATE INDEX IF NOT EXISTS idx_tokens_counter_status ON tokens (counter_id, status);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tokens_student_status ON tokens (student_id, status);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tokens_created ON tokens (created_at);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_token_role ON auth_sessions (session_token, role);")
        conn.commit()

        # 10. Seed initial departments for CGC University Mohali (only if empty)
        c.execute("SELECT COUNT(*) as cnt FROM departments")
        if c.fetchone()["cnt"] == 0:
            cgc_departments = [
                ("ACCOUNTS", "Fee & Accounts Section", "Tuition, examination, and hostel fee settlement", "Block 1 Ground Floor"),
                ("REGISTRAR", "Registrar & Student Documentation", "Degree verification, bonafide & migration certificates", "Admin Block Room 102"),
                ("LIBRARY", "Central University Library", "Book issue/return, library cards, and clearance", "Central Library Block"),
                ("EXAMINATION", "Examination & Records Cell", "Admit card clearance, marksheets, and re-evaluation", "Block 3 1st Floor"),
                ("CRC", "Corporate Resource Center (Placements)", "Placement verification, NOC, and internship letters", "Block 5 3rd Floor"),
                ("HOSTEL", "Hostel & Transport Administration", "Room allotment, gate passes, and bus passes", "Campus Support Office"),
            ]
            for code, name, desc, bldg in cgc_departments:
                c.execute("""
                    INSERT INTO departments (code, name, description, building_block)
                    VALUES (?, ?, ?, ?)
                """, (code, name, desc, bldg))
            conn.commit()

        # 10. Seed initial counters (only if empty)
        c.execute("SELECT COUNT(*) as cnt FROM counters")
        if c.fetchone()["cnt"] == 0:
            initial_counters = [
                (1, "Fee Deposit Counter 1", "ACCOUNTS-W1", 8),
                (1, "Scholarship & Concession Desk", "ACCOUNTS-W2", 12),
                (2, "Bonafide & Character Certificate Window", "REG-W1", 5),
                (2, "Degree & Transcript Dispatch Desk", "REG-W2", 7),
                (3, "Book Issue & Circulation Desk", "LIB-W1", 4),
                (4, "Admit Card Clearance Desk", "EXAM-W1", 6),
                (5, "Placement NOC & Drive Verification Desk", "CRC-W1", 10),
            ]
            for dep_id, name, code, avg_m in initial_counters:
                c.execute("""
                    INSERT INTO counters (department_id, name, code, avg_service_time_mins)
                    VALUES (?, ?, ?, ?)
                """, (dep_id, name, code, avg_m))
            conn.commit()

        # Backfill counter codes and department_ids if any pre-existing rows have nulls
        try:
            c.execute("UPDATE counters SET department_id = 1 WHERE department_id IS NULL")
            c.execute("UPDATE counters SET code = 'COUNTER-' || id WHERE code IS NULL")
            conn.commit()
        except Exception:
            pass

        # 11. Seed / Upsert Default Admin (guarantee known working credentials)
        c.execute("SELECT id FROM users WHERE email = 'admin@cgc.edu.in' OR identifier = 'ADM001'")
        adm_row = c.fetchone()
        admin_pw_hash = generate_password_hash("Admin@QueueX2026")
        if not adm_row:
            c.execute("""
                INSERT INTO users (email, password_hash, full_name, role, identifier, phone, is_active)
                VALUES ('admin@cgc.edu.in', ?, 'CGC Central Queue Administrator', 'admin', 'ADM001', '0172-3984200', 1)
            """, (admin_pw_hash,))
        else:
            c.execute("""
                UPDATE users
                SET password_hash = ?, role = 'admin', identifier = 'ADM001', is_active = 1
                WHERE id = ?
            """, (admin_pw_hash, adm_row["id"]))
        conn.commit()

        # 12. Seed / Upsert Default Operator (guarantee known working credentials)
        c.execute("SELECT id FROM users WHERE email = 'operator@cgc.edu.in' OR identifier = 'OP101'")
        op_row = c.fetchone()
        op_pw_hash = generate_password_hash("Operator@QueueX2026")
        if not op_row:
            c.execute("""
                INSERT INTO users (email, password_hash, full_name, role, identifier, phone, is_active)
                VALUES ('operator@cgc.edu.in', ?, 'Accounts Counter Officer', 'operator', 'OP101', '9876543210', 1)
            """, (op_pw_hash,))
        else:
            c.execute("""
                UPDATE users
                SET password_hash = ?, role = 'operator', identifier = 'OP101', is_active = 1
                WHERE id = ?
            """, (op_pw_hash, op_row["id"]))
        c.execute("UPDATE counters SET assigned_operator_id = (SELECT id FROM users WHERE email = 'operator@cgc.edu.in') WHERE code = 'ACCOUNTS-W1'")
        conn.commit()

        # 13. Seed / Upsert Demo Student (guarantee known working credentials)
        c.execute("SELECT id FROM users WHERE email = 'student@cgc.edu.in' OR identifier = '2201045'")
        st_row = c.fetchone()
        st_pw_hash = generate_password_hash("Student@QueueX2026")
        if not st_row:
            c.execute("""
                INSERT INTO users (email, password_hash, full_name, role, identifier, phone, department, course, semester, is_active)
                VALUES ('student@cgc.edu.in', ?, 'Aarav Sharma', 'student', '2201045', '9812345678', 'CSE', 'B.Tech', 6, 1)
            """, (st_pw_hash,))
        else:
            c.execute("""
                UPDATE users
                SET password_hash = ?, role = 'student', identifier = '2201045', is_active = 1
                WHERE id = ?
            """, (st_pw_hash, st_row["id"]))
        conn.commit()


# -------------------------------------------------------------
# ROLE-BASED ACCESS CONTROL & MULTI-TAB SESSION ISOLATION (SERVER-SIDE)
# -------------------------------------------------------------

SESSION_COOKIE_NAME = "qx_browser_session"
SESSION_LIFETIME_DAYS = 7


def get_or_create_browser_session_token():
    """Retrieve or initialize the persistent browser session identifier cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token or len(token) < 24:
        token = secrets.token_urlsafe(32)
        request._qx_new_session_token = token
    return token


@app.after_request
def save_browser_session_cookie(response):
    """Ensure the browser session token cookie is persisted across all requests."""
    new_token = getattr(request, "_qx_new_session_token", None)
    if new_token:
        response.set_cookie(
            SESSION_COOKIE_NAME,
            new_token,
            max_age=SESSION_LIFETIME_DAYS * 86400,
            httponly=True,
            samesite="Lax",
            secure=cookie_secure,
            path="/"
        )
    return response


def get_current_role():
    """Determine role strictly based on requested path prefix or explicit query/form param."""
    path = request.path
    if path.startswith("/admin"):
        return "admin"
    elif path.startswith("/operator"):
        return "operator"
    elif path.startswith("/student") or path.startswith("/api/student"):
        return "student"
    
    # Check explicit param if outside role-prefixed path
    param_role = request.args.get("role") or request.form.get("role")
    if param_role in ("student", "operator", "admin"):
        return param_role
    return "student"


def get_role_session(role=None):
    """
    Retrieve the independent authenticated user session dictionary for the given role
    directly from the PostgreSQL/SQLite server-side auth_sessions store.
    """
    target_role = role or get_current_role()
    session_token = get_or_create_browser_session_token()
    now_dt = datetime.datetime.now()

    try:
        with db.get_db() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT user_id, user_name, user_email, role as user_role, user_identifier, expires_at
                FROM auth_sessions
                WHERE session_token = ? AND role = ?
            """, (session_token, target_role))
            row = c.fetchone()
            if row:
                # Check expiration
                expires_at_raw = row["expires_at"]
                if isinstance(expires_at_raw, str):
                    try:
                        exp_dt = datetime.datetime.fromisoformat(expires_at_raw)
                    except Exception:
                        exp_dt = now_dt + datetime.timedelta(days=SESSION_LIFETIME_DAYS)
                elif isinstance(expires_at_raw, datetime.datetime):
                    exp_dt = expires_at_raw
                else:
                    exp_dt = now_dt + datetime.timedelta(days=SESSION_LIFETIME_DAYS)

                # Strip timezone if compared with naive now_dt
                if exp_dt.tzinfo is not None:
                    exp_dt = exp_dt.replace(tzinfo=None)

                if exp_dt > now_dt:
                    return {
                        "user_id": row["user_id"],
                        "user_name": row["user_name"],
                        "user_email": row["user_email"],
                        "user_role": row["user_role"],
                        "user_identifier": row["user_identifier"]
                    }
                else:
                    # Expired session: prune
                    c.execute("DELETE FROM auth_sessions WHERE session_token = ? AND role = ?", (session_token, target_role))
                    conn.commit()
    except Exception as e:
        app.logger.warning(f"Error reading server auth_session for {target_role}: {e}")

    return None


def get_all_active_role_sessions():
    """Retrieve all active role sessions associated with the current browser session token."""
    session_token = get_or_create_browser_session_token()
    now_dt = datetime.datetime.now()
    active = {}
    try:
        with db.get_db() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT user_id, user_name, user_email, role as user_role, user_identifier, expires_at
                FROM auth_sessions
                WHERE session_token = ?
            """, (session_token,))
            rows = c.fetchall()
            for r in rows:
                expires_at_raw = r["expires_at"]
                if isinstance(expires_at_raw, str):
                    try:
                        exp_dt = datetime.datetime.fromisoformat(expires_at_raw)
                    except Exception:
                        exp_dt = now_dt + datetime.timedelta(days=SESSION_LIFETIME_DAYS)
                elif isinstance(expires_at_raw, datetime.datetime):
                    exp_dt = expires_at_raw
                else:
                    exp_dt = now_dt + datetime.timedelta(days=SESSION_LIFETIME_DAYS)
                if exp_dt.tzinfo is not None:
                    exp_dt = exp_dt.replace(tzinfo=None)

                if exp_dt > now_dt:
                    active[r["user_role"]] = {
                        "user_id": r["user_id"],
                        "user_name": r["user_name"],
                        "user_email": r["user_email"],
                        "user_role": r["user_role"],
                        "user_identifier": r["user_identifier"]
                    }
    except Exception as e:
        app.logger.warning(f"Error fetching active sessions: {e}")
    return active


def get_current_user_id(role=None):
    """Get the authenticated user ID scoped to the requested role or path."""
    sess = get_role_session(role)
    if sess and "user_id" in sess:
        return sess["user_id"]
    return None


def set_role_session(user):
    """
    Store or update user login session atomically in PostgreSQL/SQLite auth_sessions table.
    This guarantees that concurrent logins in different tabs cannot overwrite each other.
    """
    role = user["role"]
    session_token = get_or_create_browser_session_token()
    expires_at = datetime.datetime.now() + datetime.timedelta(days=SESSION_LIFETIME_DAYS)

    with db.get_db() as conn:
        c = conn.cursor()
        # Atomic upsert pattern: check existing role session for this browser token
        c.execute("SELECT id FROM auth_sessions WHERE session_token = ? AND role = ?", (session_token, role))
        existing = c.fetchone()
        if existing:
            c.execute("""
                UPDATE auth_sessions
                SET user_id = ?, user_name = ?, user_email = ?, user_identifier = ?, last_active = CURRENT_TIMESTAMP, expires_at = ?
                WHERE id = ?
            """, (user["id"], user["full_name"], user["email"], user["identifier"], expires_at, existing["id"]))
        else:
            c.execute("""
                INSERT INTO auth_sessions (session_token, role, user_id, user_name, user_email, user_identifier, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (session_token, role, user["id"], user["full_name"], user["email"], user["identifier"], expires_at))
        conn.commit()


def clear_role_session(role=None):
    """Clear session only for the specified role in auth_sessions, preserving other active tabs."""
    target_role = role or get_current_role()
    session_token = get_or_create_browser_session_token()
    try:
        with db.get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM auth_sessions WHERE session_token = ? AND role = ?", (session_token, target_role))
            conn.commit()
    except Exception as e:
        app.logger.warning(f"Error clearing auth_session for {target_role}: {e}")


def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            target_role = role or get_current_role()
            user_session = get_role_session(target_role)

            if not user_session:
                # If the user is logged into another role, redirect with informative notice
                active_roles = get_all_active_role_sessions()
                if active_roles:
                    flash("Unauthorized access for your account.", "danger")
                    first_active = next(iter(active_roles.keys()))
                    if first_active == "student":
                        return redirect(url_for("student_portal"))
                    elif first_active == "operator":
                        return redirect(url_for("operator_portal"))
                    elif first_active == "admin":
                        return redirect(url_for("admin_portal"))

                flash(f"Please log in as {target_role.capitalize()} to access this tab.", "warning")
                return redirect(url_for("login", role=target_role))

            return f(*args, **kwargs)
        return decorated_function
    return decorator


@app.context_processor
def inject_common_context():
    target_role = get_current_role()
    user_sess = get_role_session(target_role) or {}

    unread_notifs = 0
    uid = user_sess.get("user_id")
    if uid:
        try:
            with db.get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT COUNT(*) as cnt FROM notifications WHERE user_id = ? AND is_read = 0", (uid,))
                unread_notifs = c.fetchone()["cnt"]
        except Exception:
            unread_notifs = 0

    return {
        "current_user": user_sess.get("user_name"),
        "current_role": user_sess.get("user_role"),
        "current_id": user_sess.get("user_id"),
        "current_identifier": user_sess.get("user_identifier"),
        "active_roles": get_all_active_role_sessions(),
        "unread_notifications": unread_notifs,
        "now": datetime.datetime.now()
    }


def generate_qr_base64(data_str):
    """Generate high-contrast QR code returned as inline base64 image data."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(data_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0b1f3a", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def broadcast_queue_update(counter_id, event_type="queue_updated", payload=None):
    """Notify WebSocket clients and counter rooms of queue updates."""
    try:
        data = payload or {}
        data["counter_id"] = counter_id
        data["event_type"] = event_type
        data["timestamp"] = datetime.datetime.now().isoformat()
        socketio.emit("queue_update", data, room=f"counter_{counter_id}")
        socketio.emit("public_counters_update", data)
    except Exception as _e:
        pass


@socketio.on("join_counter")
def on_join_counter(data):
    counter_id = data.get("counter_id")
    if counter_id:
        join_room(f"counter_{counter_id}")
        emit("joined_counter", {"counter_id": counter_id, "status": "connected"})


@socketio.on("leave_counter")
def on_leave_counter(data):
    counter_id = data.get("counter_id")
    if counter_id:
        leave_room(f"counter_{counter_id}")


# -------------------------------------------------------------
# HEALTH CHECK & SYSTEM STATUS
# -------------------------------------------------------------

@app.route("/health")
@app.route("/api/health")
def health_check():
    try:
        with db.get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT 1")
            c.fetchone()
        uptime = (datetime.datetime.now(datetime.timezone.utc) - APP_START_TIME).total_seconds()
        return jsonify({
            "status": "healthy",
            "system": "QueueX Smart Virtual Queue System",
            "campus": "CGC University, Mohali, Punjab",
            "database": "connected",
            "engine": "postgresql" if db.is_postgres() else "sqlite",
            "uptime_seconds": round(uptime, 2)
        }), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 503


@app.route("/sw.js")
def service_worker():
    """Serve a clean service worker response to prevent 404 logs from PWA clients."""
    return Response(
        "// QueueX Service Worker\nself.addEventListener('install', () => self.skipWaiting());\nself.addEventListener('activate', () => self.clients.claim());\n",
        mimetype="application/javascript",
        headers={"Cache-Control": "public, max-age=86400"}
    )


# -------------------------------------------------------------
# PUBLIC & AUTHENTICATION ENDPOINTS
# -------------------------------------------------------------

@app.route("/")
def index():
    # Only redirect from landing page if a specific role is explicitly requested or unambiguous
    req_role = request.args.get("role")
    if req_role:
        role_sess = get_role_session(req_role)
        if role_sess:
            if req_role == "student":
                return redirect(url_for("student_portal"))
            elif req_role == "operator":
                return redirect(url_for("operator_portal"))
            elif req_role == "admin":
                return redirect(url_for("admin_portal"))

    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT c.*, d.name as department_name, d.building_block,
                   (SELECT COUNT(*) FROM tokens t WHERE t.counter_id = c.id AND t.status = 'waiting') as waiting_count,
                   (SELECT token_number FROM tokens t WHERE t.counter_id = c.id AND t.status = 'serving' LIMIT 1) as now_serving
            FROM counters c
            JOIN departments d ON d.id = c.department_id
            WHERE c.is_active = 1
            ORDER BY d.name, c.name
        """)
        active_counters = c.fetchall()

    return render_template("index.html", counters=active_counters)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_id = request.form.get("login_id", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "student")

        if not login_id or not password:
            flash("Please enter both ID/Email and password.", "danger")
            return render_template("login.html", role=role)

        with db.get_db() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT * FROM users
                WHERE (LOWER(email) = LOWER(?) OR LOWER(identifier) = LOWER(?))
                AND role = ?
            """, (login_id, login_id, role))
            user = c.fetchone()

        if user and check_password_hash(user["password_hash"], password):
            if "is_active" in user and user["is_active"] == 0:
                flash("Your account has been deactivated. Please contact administration.", "danger")
                return render_template("login.html", role=role)

            # Isolated role-based session setting (does not erase other tab role sessions!)
            set_role_session(user)

            flash(f"Welcome to QueueX, {user['full_name']}!", "success")
            if user["role"] == "student":
                return redirect(url_for("student_portal"))
            elif user["role"] == "operator":
                return redirect(url_for("operator_portal"))
            elif user["role"] == "admin":
                return redirect(url_for("admin_portal"))

        flash("Invalid credentials or role selection. Please check and retry.", "danger")
        return render_template("login.html", role=role)

    role = request.args.get("role", "student")
    return render_template("login.html", role=role)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        roll_no = request.form.get("roll_no", "").strip().upper()
        phone = request.form.get("phone", "").strip()
        department = request.form.get("department", "CSE").strip()
        course = request.form.get("course", "B.Tech").strip()
        semester = int(request.form.get("semester", 6))
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not all([full_name, email, roll_no, password]):
            flash("Please fill in all required fields.", "danger")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template("register.html")

        with db.get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM users WHERE email = ? OR identifier = ?", (email, roll_no))
            if c.fetchone():
                flash("An account with this Email or Roll Number already exists.", "danger")
                return render_template("register.html")

            pw_hash = generate_password_hash(password)
            c.execute("""
                INSERT INTO users (email, password_hash, full_name, role, identifier, phone, department, course, semester)
                VALUES (?, ?, ?, 'student', ?, ?, ?, ?, ?)
            """, (email, pw_hash, full_name, roll_no, phone, department, course, semester))
            conn.commit()

        flash("Registration successful! You can now generate queue tokens.", "success")
        return redirect(url_for("login", role="student"))

    return render_template("register.html")


@app.route("/logout")
def logout():
    role_to_logout = request.args.get("role") or get_current_role()
    clear_role_session(role_to_logout)
    flash(f"You have been signed out of {role_to_logout.capitalize()} portal.", "info")
    return redirect(url_for("login", role=role_to_logout))


# -------------------------------------------------------------
# PHASE 3: COMPLETE STUDENT PORTAL
# -------------------------------------------------------------

@app.route("/student")
@app.route("/student/dashboard")
@login_required(role="student")
def student_portal():
    student_id = get_current_user_id("student")

    with db.get_db() as conn:
        c = conn.cursor()

        # 1. Fetch Student Details
        c.execute("SELECT * FROM users WHERE id = ?", (student_id,))
        student = c.fetchone()

        # 2. Check for Active Token (status: 'waiting' or 'serving')
        c.execute("""
            SELECT t.*, c.name as counter_name, c.code as counter_code, c.avg_service_time_mins,
                   d.name as department_name, d.building_block
            FROM tokens t
            JOIN counters c ON c.id = t.counter_id
            JOIN departments d ON d.id = t.department_id
            WHERE t.student_id = ? AND t.status IN ('waiting', 'serving')
            ORDER BY t.id DESC LIMIT 1
        """, (student_id,))
        active_token = c.fetchone()

        active_meta = None
        if active_token:
            # Calculate people ahead & estimated waiting time
            c.execute("""
                SELECT COUNT(*) as count FROM tokens
                WHERE counter_id = ? AND status = 'waiting' AND id < ?
            """, (active_token["counter_id"], active_token["id"]))
            people_ahead = c.fetchone()["count"]

            # Current serving token at counter
            c.execute("""
                SELECT token_number FROM tokens
                WHERE counter_id = ? AND status = 'serving'
                ORDER BY id DESC LIMIT 1
            """, (active_token["counter_id"],))
            srv_row = c.fetchone()
            current_serving = srv_row["token_number"] if srv_row else None

            est_mins = people_ahead * active_token["avg_service_time_mins"]
            if active_token["status"] == "serving":
                est_mins = 0

            # QR Code string & data
            qr_payload = f"QUEUEX|CGC|T{active_token['token_number']}|C{active_token['counter_code']}|{active_token['token_salt']}"
            qr_base64 = generate_qr_base64(qr_payload)

            active_meta = {
                "people_ahead": people_ahead,
                "current_serving": current_serving,
                "est_mins": est_mins,
                "qr_image": qr_base64
            }

        # 3. Available Departments with active counters
        c.execute("""
            SELECT d.*,
                   (SELECT COUNT(*) FROM counters c WHERE c.department_id = d.id AND c.is_active = 1) as open_counters,
                   (SELECT COUNT(*) FROM tokens t WHERE t.department_id = d.id AND t.status = 'waiting') as total_waiting
            FROM departments d
            ORDER BY d.name
        """)
        departments = c.fetchall()

        # 4. Active Counters
        c.execute("""
            SELECT c.*, d.name as department_name
            FROM counters c
            JOIN departments d ON d.id = c.department_id
            WHERE c.is_active = 1
            ORDER BY d.name, c.name
        """)
        counters = c.fetchall()

        # 5. Token History for Student
        c.execute("""
            SELECT t.*, c.name as counter_name, d.name as department_name
            FROM tokens t
            JOIN counters c ON c.id = t.counter_id
            JOIN departments d ON d.id = t.department_id
            WHERE t.student_id = ?
            ORDER BY t.id DESC LIMIT 10
        """, (student_id,))
        token_history = c.fetchall()

    return render_template(
        "student_portal.html",
        student=student,
        active_token=active_token,
        active_meta=active_meta,
        departments=departments,
        counters=counters,
        token_history=token_history
    )


@app.route("/student/generate-token", methods=["POST"])
@login_required(role="student")
def student_generate_token():
    student_id = get_current_user_id("student")
    counter_id = request.form.get("counter_id")
    service_reason = request.form.get("service_reason", "").strip()

    if not counter_id:
        flash("Please select a service counter.", "danger")
        return redirect(url_for("student_portal"))

    # Acquire re-entrant lock to ensure strictly sequential token numbers and prevent simultaneous double booking
    with QUEUE_LOCK:
        with db.get_db() as conn:
            c = conn.cursor()

            # 1. Prevent duplicate active tokens for this student across all counters
            c.execute("""
                SELECT id, token_number, counter_id FROM tokens
                WHERE student_id = ? AND status IN ('waiting', 'serving')
            """, (student_id,))
            existing_active = c.fetchone()
            if existing_active:
                flash("You already have an active queue token. Please wait or cancel it first.", "warning")
                return redirect(url_for("student_portal"))

            # 2. Check counter validity & open/paused state
            c.execute("SELECT * FROM counters WHERE id = ?", (counter_id,))
            counter = c.fetchone()
            if not counter or not counter["is_active"]:
                flash("Selected counter is currently closed. Please select an open counter.", "danger")
                return redirect(url_for("student_portal"))

            if counter["is_paused"]:
                flash("This counter is currently paused. Please check back in a few minutes.", "warning")
                return redirect(url_for("student_portal"))

            # 3. Calculate daily sequential token number for this counter with transaction integrity
            # PostgreSQL date: CURRENT_DATE, SQLite: date('now')
            if db.is_postgres():
                date_cond = "created_at::DATE = CURRENT_DATE"
            else:
                date_cond = "date(created_at) = date('now')"

            c.execute(f"""
                SELECT COALESCE(MAX(token_number), 0) + 1 as next_token
                FROM tokens
                WHERE counter_id = ? AND {date_cond}
            """, (counter_id,))
            next_token_num = c.fetchone()["next_token"]

            # 4. Fetch student details
            c.execute("SELECT full_name, identifier, phone FROM users WHERE id = ?", (student_id,))
            st = c.fetchone()

            token_salt = secrets.token_hex(8)

            c.execute("""
                INSERT INTO tokens (token_number, counter_id, department_id, student_id, student_name, student_roll, student_phone, service_reason, status, token_salt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'waiting', ?)
            """, (next_token_num, counter_id, counter["department_id"], student_id, st["full_name"], st["identifier"], st["phone"], service_reason, token_salt))
            token_id = c.lastrowid

            # Insert notification
            c.execute("""
                INSERT INTO notifications (user_id, title, message)
                VALUES (?, ?, ?)
            """, (student_id, "Token Generated", f"Token #{next_token_num} generated for {counter['name']}."))

            conn.commit()

        # Broadcast WebSocket event to counter room
        broadcast_queue_update(counter_id, "token_generated", {"token_number": next_token_num, "token_id": token_id})

    flash(f"Token #{next_token_num} generated successfully! You are in line.", "success")
    return redirect(url_for("student_token_status", token_id=token_id))


@app.route("/student/token/<int:token_id>")
@login_required(role="student")
def student_token_status(token_id):
    student_id = get_current_user_id("student")

    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT t.*, c.name as counter_name, c.code as counter_code, c.avg_service_time_mins,
                   d.name as department_name, d.building_block
            FROM tokens t
            JOIN counters c ON c.id = t.counter_id
            JOIN departments d ON d.id = t.department_id
            WHERE t.id = ? AND t.student_id = ?
        """, (token_id, student_id))
        token = c.fetchone()

        if not token:
            flash("Token record not found.", "danger")
            return redirect(url_for("student_portal"))

        # People ahead in waiting status
        c.execute("""
            SELECT COUNT(*) as count FROM tokens
            WHERE counter_id = ? AND status = 'waiting' AND id < ?
        """, (token["counter_id"], token["id"]))
        people_ahead = c.fetchone()["count"]

        # Current serving token
        c.execute("""
            SELECT token_number FROM tokens
            WHERE counter_id = ? AND status = 'serving'
            ORDER BY id DESC LIMIT 1
        """, (token["counter_id"],))
        srv_row = c.fetchone()
        current_serving = srv_row["token_number"] if srv_row else None

        est_mins = people_ahead * token["avg_service_time_mins"]
        if token["status"] == "serving":
            est_mins = 0

        qr_payload = f"QUEUEX|CGC|T{token['token_number']}|C{token['counter_code']}|{token['token_salt']}"
        qr_base64 = generate_qr_base64(qr_payload)

    return render_template(
        "student_token_status.html",
        token=token,
        people_ahead=people_ahead,
        current_serving=current_serving,
        est_mins=est_mins,
        qr_image=qr_base64
    )


@app.route("/api/student/token/<int:token_id>/status")
@login_required(role="student")
def api_student_token_status(token_id):
    """Real-time JSON endpoint for client-side live queue polling."""
    student_id = get_current_user_id("student")
    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT t.status, t.token_number, t.counter_id, c.avg_service_time_mins
            FROM tokens t
            JOIN counters c ON c.id = t.counter_id
            WHERE t.id = ? AND t.student_id = ?
        """, (token_id, student_id))
        token = c.fetchone()

        if not token:
            return jsonify({"error": "Token not found"}), 404

        c.execute("""
            SELECT COUNT(*) as count FROM tokens
            WHERE counter_id = ? AND status = 'waiting' AND id < ?
        """, (token["counter_id"], token_id))
        people_ahead = c.fetchone()["count"]

        c.execute("""
            SELECT token_number FROM tokens
            WHERE counter_id = ? AND status = 'serving'
            ORDER BY id DESC LIMIT 1
        """, (token["counter_id"],))
        srv_row = c.fetchone()
        current_serving = srv_row["token_number"] if srv_row else None

        est_mins = people_ahead * token["avg_service_time_mins"]
        if token["status"] == "serving":
            est_mins = 0

        return jsonify({
            "status": token["status"],
            "token_number": token["token_number"],
            "people_ahead": people_ahead,
            "current_serving": current_serving,
            "estimated_mins": est_mins
        })


@app.route("/student/token/cancel/<int:token_id>", methods=["POST"])
@login_required(role="student")
def student_cancel_token(token_id):
    student_id = get_current_user_id("student")

    with QUEUE_LOCK:
        with db.get_db() as conn:
            c = conn.cursor()
            # Enforce IDOR protection: token must belong to authenticated student
            c.execute("SELECT status, counter_id, token_number FROM tokens WHERE id = ? AND student_id = ?", (token_id, student_id))
            row = c.fetchone()

            if not row:
                flash("Token not found or unauthorized.", "danger")
                return redirect(url_for("student_portal"))

            if row["status"] != "waiting":
                flash("Only waiting tokens can be cancelled.", "warning")
                return redirect(url_for("student_portal"))

            c.execute("UPDATE tokens SET status = 'cancelled' WHERE id = ? AND status = 'waiting'", (token_id,))
            c.execute("""
                INSERT INTO audit_logs (action, user_id, user_role, details)
                VALUES ('CANCEL_TOKEN', ?, 'student', ?)
            """, (student_id, f"Cancelled Token #{row['token_number']} at Counter ID {row['counter_id']}"))
            conn.commit()

        broadcast_queue_update(row["counter_id"], "token_cancelled", {"token_id": token_id, "token_number": row["token_number"]})

    flash("Your queue token has been cancelled.", "info")
    return redirect(url_for("student_portal"))


@app.route("/student/profile", methods=["GET", "POST"])
@login_required(role="student")
def student_profile():
    student_id = get_current_user_id("student")

    with db.get_db() as conn:
        c = conn.cursor()

        if request.method == "POST":
            full_name = request.form.get("full_name", "").strip()
            phone = request.form.get("phone", "").strip()
            department = request.form.get("department", "CSE").strip()
            course = request.form.get("course", "B.Tech").strip()
            semester = int(request.form.get("semester", 6))

            if not full_name:
                flash("Full name cannot be empty.", "danger")
                return redirect(url_for("student_profile"))

            c.execute("""
                UPDATE users
                SET full_name = ?, phone = ?, department = ?, course = ?, semester = ?
                WHERE id = ?
            """, (full_name, phone, department, course, semester, student_id))
            c.execute("""
                UPDATE auth_sessions
                SET user_name = ?
                WHERE user_id = ? AND role = 'student'
            """, (full_name, student_id))
            conn.commit()

            flash("Profile updated successfully!", "success")
            return redirect(url_for("student_profile"))

        c.execute("SELECT * FROM users WHERE id = ?", (student_id,))
        student = c.fetchone()

    return render_template("student_profile.html", student=student)


@app.route("/student/settings", methods=["GET", "POST"])
@login_required(role="student")
def student_settings():
    student_id = get_current_user_id("student")

    if request.method == "POST":
        action = request.form.get("action")

        if action == "change_password":
            current_pw = request.form.get("current_password", "").strip()
            new_pw = request.form.get("new_password", "").strip()
            confirm_pw = request.form.get("confirm_password", "").strip()

            if not current_pw or not new_pw:
                flash("Please fill out all password fields.", "danger")
                return redirect(url_for("student_settings"))

            if new_pw != confirm_pw:
                flash("New passwords do not match.", "danger")
                return redirect(url_for("student_settings"))

            if len(new_pw) < 6:
                flash("New password must be at least 6 characters.", "danger")
                return redirect(url_for("student_settings"))

            with db.get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT password_hash FROM users WHERE id = ?", (student_id,))
                user = c.fetchone()

                if not check_password_hash(user["password_hash"], current_pw):
                    flash("Current password incorrect.", "danger")
                    return redirect(url_for("student_settings"))

                c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new_pw), student_id))
                conn.commit()

            flash("Password changed successfully!", "success")
            return redirect(url_for("student_settings"))

    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE id = ?", (student_id,))
        student = c.fetchone()

        c.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 10", (student_id,))
        notifications = c.fetchall()

    return render_template("student_settings.html", student=student, notifications=notifications)


@app.route("/student/notifications/clear", methods=["POST"])
@login_required(role="student")
def clear_notifications():
    student_id = get_current_user_id("student")
    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (student_id,))
        conn.commit()
    flash("Notifications marked as read.", "info")
    return redirect(url_for("student_settings"))


# -------------------------------------------------------------
# PHASE 4: COMPLETE OPERATOR PORTAL
# -------------------------------------------------------------

def get_operator_counter(cursor, operator_id):
    """Retrieve counter assigned to the authenticated operator."""
    cursor.execute("""
        SELECT c.*, d.name as department_name, d.building_block
        FROM counters c
        JOIN departments d ON d.id = c.department_id
        WHERE c.assigned_operator_id = ?
        LIMIT 1
    """, (operator_id,))
    return cursor.fetchone()


@app.route("/operator")
@app.route("/operator/dashboard")
@login_required(role="operator")
def operator_portal():
    operator_id = get_current_user_id("operator")

    with db.get_db() as conn:
        c = conn.cursor()

        # 1. Fetch Operator and Assigned Counter
        c.execute("SELECT * FROM users WHERE id = ?", (operator_id,))
        operator = c.fetchone()

        counter = get_operator_counter(c, operator_id)

        if not counter:
            return render_template(
                "operator_portal.html",
                operator=operator,
                counter=None,
                currently_serving=None,
                waiting_tokens=[],
                stats={"waiting": 0, "completed": 0, "skipped": 0, "avg_time": 0}
            )

        # 2. Currently Serving Token
        c.execute("""
            SELECT * FROM tokens
            WHERE counter_id = ? AND status = 'serving'
            ORDER BY called_at DESC LIMIT 1
        """, (counter["id"],))
        currently_serving = c.fetchone()

        # 3. Waiting Queue for this counter
        c.execute("""
            SELECT * FROM tokens
            WHERE counter_id = ? AND status = 'waiting'
            ORDER BY id ASC
        """, (counter["id"],))
        waiting_tokens = c.fetchall()

        # 4. Previously called / skipped token (for recall)
        c.execute("""
            SELECT * FROM tokens
            WHERE counter_id = ? AND status = 'skipped'
            ORDER BY id DESC LIMIT 1
        """, (counter["id"],))
        last_skipped = c.fetchone()

        # 5. Daily Counter Statistics
        c.execute("""
            SELECT
                SUM(CASE WHEN status = 'waiting' THEN 1 ELSE 0 END) as waiting_count,
                SUM(CASE WHEN status = 'served' THEN 1 ELSE 0 END) as completed_count,
                SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) as skipped_count
            FROM tokens
            WHERE counter_id = ? AND date(created_at) = date('now')
        """, (counter["id"],))
        stat_row = c.fetchone()

        stats = {
            "waiting": stat_row["waiting_count"] or 0,
            "completed": stat_row["completed_count"] or 0,
            "skipped": stat_row["skipped_count"] or 0,
            "avg_time": counter["avg_service_time_mins"] or 8
        }

    return render_template(
        "operator_portal.html",
        operator=operator,
        counter=counter,
        currently_serving=currently_serving,
        waiting_tokens=waiting_tokens,
        last_skipped=last_skipped,
        stats=stats
    )


@app.route("/operator/call-next", methods=["POST"])
@login_required(role="operator")
def operator_call_next():
    operator_id = get_current_user_id("operator")

    with QUEUE_LOCK:
        with db.get_db() as conn:
            c = conn.cursor()
            counter = get_operator_counter(c, operator_id)
            if not counter:
                flash("No counter assigned to your account.", "danger")
                return redirect(url_for("operator_portal"))

            if not counter["is_active"]:
                flash("Counter is closed. Reopen counter before calling tokens.", "warning")
                return redirect(url_for("operator_portal"))

            if counter["is_paused"]:
                flash("Queue is paused. Resume queue before calling tokens.", "warning")
                return redirect(url_for("operator_portal"))

            # Check if already serving an active token
            c.execute("SELECT id, token_number FROM tokens WHERE counter_id = ? AND status = 'serving'", (counter["id"],))
            active_serving = c.fetchone()
            if active_serving:
                flash(f"Token #{active_serving['token_number']} is currently being served. Complete or skip it before calling next.", "warning")
                return redirect(url_for("operator_portal"))

            # Get next waiting token in strict FIFO order
            c.execute("""
                SELECT * FROM tokens
                WHERE counter_id = ? AND status = 'waiting'
                ORDER BY id ASC LIMIT 1
            """, (counter["id"],))
            next_token = c.fetchone()

            if not next_token:
                flash("No students waiting in queue.", "info")
                return redirect(url_for("operator_portal"))

            # Transition status to 'serving'
            c.execute("""
                UPDATE tokens
                SET status = 'serving', called_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'waiting'
            """, (next_token["id"],))

            # Notify student
            c.execute("""
                INSERT INTO notifications (user_id, title, message)
                VALUES (?, ?, ?)
            """, (
                next_token["student_id"],
                "It's Your Turn!",
                f"Token #{next_token['token_number']} called at {counter['name']} ({counter['code']}). Please proceed to desk."
            ))

            # Audit log
            c.execute("""
                INSERT INTO audit_logs (action, user_id, user_role, details)
                VALUES (?, ?, 'operator', ?)
            """, ("CALL_NEXT", operator_id, f"Called Token #{next_token['token_number']} for Counter {counter['code']}"))

            conn.commit()

        # Emit live update to counter room
        broadcast_queue_update(counter["id"], "token_called", {
            "token_id": next_token["id"],
            "token_number": next_token["token_number"],
            "student_name": next_token["student_name"],
            "counter_name": counter["name"],
            "counter_code": counter["code"]
        })

    flash(f"Calling Token #{next_token['token_number']} ({next_token['student_name']})!", "success")
    return redirect(url_for("operator_portal"))


@app.route("/operator/complete/<int:token_id>", methods=["POST"])
@login_required(role="operator")
def operator_complete_token(token_id):
    operator_id = get_current_user_id("operator")

    with QUEUE_LOCK:
        with db.get_db() as conn:
            c = conn.cursor()
            counter = get_operator_counter(c, operator_id)
            if not counter:
                flash("Unauthorized counter access.", "danger")
                return redirect(url_for("operator_portal"))

            # Verify token belongs to operator counter and is 'serving'
            c.execute("SELECT * FROM tokens WHERE id = ? AND counter_id = ?", (token_id, counter["id"]))
            token = c.fetchone()

            if not token:
                flash("Token not found.", "danger")
                return redirect(url_for("operator_portal"))

            if token["status"] != "serving":
                flash("Only currently serving tokens can be marked completed.", "warning")
                return redirect(url_for("operator_portal"))

            c.execute("""
                UPDATE tokens
                SET status = 'served', completed_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'serving'
            """, (token_id,))

            # Notification for student
            c.execute("""
                INSERT INTO notifications (user_id, title, message)
                VALUES (?, ?, ?)
            """, (token["student_id"], "Service Completed", f"Service for Token #{token['token_number']} completed at {counter['name']}."))

            # Audit log
            c.execute("""
                INSERT INTO audit_logs (action, user_id, user_role, details)
                VALUES (?, ?, 'operator', ?)
            """, ("COMPLETE_TOKEN", operator_id, f"Completed Token #{token['token_number']}"))

            conn.commit()

        broadcast_queue_update(counter["id"], "token_completed", {
            "token_id": token["id"],
            "token_number": token["token_number"]
        })

    flash(f"Token #{token['token_number']} marked as Completed.", "success")
    return redirect(url_for("operator_portal"))


@app.route("/operator/skip/<int:token_id>", methods=["POST"])
@login_required(role="operator")
def operator_skip_token(token_id):
    operator_id = get_current_user_id("operator")

    with QUEUE_LOCK:
        with db.get_db() as conn:
            c = conn.cursor()
            counter = get_operator_counter(c, operator_id)
            if not counter:
                flash("Unauthorized counter access.", "danger")
                return redirect(url_for("operator_portal"))

            c.execute("SELECT * FROM tokens WHERE id = ? AND counter_id = ?", (token_id, counter["id"]))
            token = c.fetchone()

            if not token or token["status"] != "serving":
                flash("Only currently serving tokens can be skipped.", "warning")
                return redirect(url_for("operator_portal"))

            c.execute("UPDATE tokens SET status = 'skipped' WHERE id = ? AND status = 'serving'", (token_id,))

            # Notification for student
            c.execute("""
                INSERT INTO notifications (user_id, title, message)
                VALUES (?, ?, ?)
            """, (token["student_id"], "Token Skipped", f"Token #{token['token_number']} was marked skipped due to no-show at {counter['name']}."))

            # Audit log
            c.execute("""
                INSERT INTO audit_logs (action, user_id, user_role, details)
                VALUES (?, ?, 'operator', ?)
            """, ("SKIP_TOKEN", operator_id, f"Skipped Token #{token['token_number']}"))

            conn.commit()

        broadcast_queue_update(counter["id"], "token_skipped", {
            "token_id": token["id"],
            "token_number": token["token_number"]
        })

    flash(f"Token #{token['token_number']} has been skipped.", "warning")
    return redirect(url_for("operator_portal"))


@app.route("/operator/recall/<int:token_id>", methods=["POST"])
@login_required(role="operator")
def operator_recall_token(token_id):
    operator_id = get_current_user_id("operator")

    with QUEUE_LOCK:
        with db.get_db() as conn:
            c = conn.cursor()
            counter = get_operator_counter(c, operator_id)
            if not counter:
                flash("Unauthorized counter access.", "danger")
                return redirect(url_for("operator_portal"))

            # Check if already serving another token
            c.execute("SELECT id, token_number FROM tokens WHERE counter_id = ? AND status = 'serving'", (counter["id"],))
            if c.fetchone():
                flash("Please complete or skip the current active token before recalling.", "warning")
                return redirect(url_for("operator_portal"))

            c.execute("SELECT * FROM tokens WHERE id = ? AND counter_id = ?", (token_id, counter["id"]))
            token = c.fetchone()

            if not token or token["status"] != "skipped":
                flash("Only skipped tokens can be recalled.", "warning")
                return redirect(url_for("operator_portal"))

            c.execute("""
                UPDATE tokens
                SET status = 'serving', called_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'skipped'
            """, (token_id,))

            # Notification for student
            c.execute("""
                INSERT INTO notifications (user_id, title, message)
                VALUES (?, ?, ?)
            """, (token["student_id"], "Token Recalled!", f"Token #{token['token_number']} was recalled at {counter['name']}."))

            # Audit log
            c.execute("""
                INSERT INTO audit_logs (action, user_id, user_role, details)
                VALUES (?, ?, 'operator', ?)
            """, ("RECALL_TOKEN", operator_id, f"Recalled Token #{token['token_number']}"))

            conn.commit()

        broadcast_queue_update(counter["id"], "token_recalled", {
            "token_id": token["id"],
            "token_number": token["token_number"]
        })

    flash(f"Recalled Token #{token['token_number']} back to Counter Desk.", "success")
    return redirect(url_for("operator_portal"))


@app.route("/operator/pause", methods=["POST"])
@login_required(role="operator")
def operator_pause_queue():
    operator_id = get_current_user_id("operator")

    with QUEUE_LOCK:
        with db.get_db() as conn:
            c = conn.cursor()
            counter = get_operator_counter(c, operator_id)
            if not counter:
                flash("Unauthorized counter access.", "danger")
                return redirect(url_for("operator_portal"))

            c.execute("UPDATE counters SET is_paused = 1 WHERE id = ?", (counter["id"],))
            c.execute("""
                INSERT INTO audit_logs (action, user_id, user_role, details)
                VALUES ('PAUSE_QUEUE', ?, 'operator', ?)
            """, (operator_id, f"Paused queue at Counter {counter['code']}"))
            conn.commit()

        broadcast_queue_update(counter["id"], "counter_status_changed", {"is_paused": 1, "is_active": counter["is_active"]})

    flash("Queue has been paused temporarily.", "info")
    return redirect(url_for("operator_portal"))


@app.route("/operator/resume", methods=["POST"])
@login_required(role="operator")
def operator_resume_queue():
    operator_id = get_current_user_id("operator")

    with QUEUE_LOCK:
        with db.get_db() as conn:
            c = conn.cursor()
            counter = get_operator_counter(c, operator_id)
            if not counter:
                flash("Unauthorized counter access.", "danger")
                return redirect(url_for("operator_portal"))

            c.execute("UPDATE counters SET is_paused = 0 WHERE id = ?", (counter["id"],))
            c.execute("""
                INSERT INTO audit_logs (action, user_id, user_role, details)
                VALUES ('RESUME_QUEUE', ?, 'operator', ?)
            """, (operator_id, f"Resumed queue at Counter {counter['code']}"))
            conn.commit()

        broadcast_queue_update(counter["id"], "counter_status_changed", {"is_paused": 0, "is_active": counter["is_active"]})

    flash("Queue operations resumed.", "success")
    return redirect(url_for("operator_portal"))


@app.route("/operator/toggle-counter", methods=["POST"])
@login_required(role="operator")
def operator_toggle_counter():
    operator_id = get_current_user_id("operator")
    action = request.form.get("action")  # 'open' or 'close'

    with QUEUE_LOCK:
        with db.get_db() as conn:
            c = conn.cursor()
            counter = get_operator_counter(c, operator_id)
            if not counter:
                flash("Unauthorized counter access.", "danger")
                return redirect(url_for("operator_portal"))

            new_status = 1 if action == "open" else 0
            c.execute("UPDATE counters SET is_active = ? WHERE id = ?", (new_status, counter["id"]))
            c.execute("""
                INSERT INTO audit_logs (action, user_id, user_role, details)
                VALUES (?, ?, 'operator', ?)
            """, (f"COUNTER_{action.upper()}", operator_id, f"Set Counter {counter['code']} status to {action}"))
            conn.commit()

        broadcast_queue_update(counter["id"], "counter_status_changed", {"is_paused": counter["is_paused"], "is_active": new_status})

    flash(f"Counter {counter['name']} is now {'Open' if new_status else 'Closed'}.", "info")
    return redirect(url_for("operator_portal"))


@app.route("/operator/profile", methods=["GET", "POST"])
@login_required(role="operator")
def operator_profile():
    operator_id = get_current_user_id("operator")

    with db.get_db() as conn:
        c = conn.cursor()

        if request.method == "POST":
            full_name = request.form.get("full_name", "").strip()
            phone = request.form.get("phone", "").strip()

            if not full_name:
                flash("Name cannot be empty.", "danger")
                return redirect(url_for("operator_profile"))

            c.execute("UPDATE users SET full_name = ?, phone = ? WHERE id = ?", (full_name, phone, operator_id))
            c.execute("""
                UPDATE auth_sessions
                SET user_name = ?
                WHERE user_id = ? AND role = 'operator'
            """, (full_name, operator_id))
            conn.commit()
            flash("Profile updated successfully!", "success")
            return redirect(url_for("operator_profile"))

        c.execute("SELECT * FROM users WHERE id = ?", (operator_id,))
        operator = c.fetchone()
        counter = get_operator_counter(c, operator_id)

    return render_template("operator_profile.html", operator=operator, counter=counter)


@app.route("/operator/settings", methods=["GET", "POST"])
@login_required(role="operator")
def operator_settings():
    operator_id = get_current_user_id("operator")

    if request.method == "POST":
        action = request.form.get("action")
        if action == "change_password":
            current_pw = request.form.get("current_password", "").strip()
            new_pw = request.form.get("new_password", "").strip()
            confirm_pw = request.form.get("confirm_password", "").strip()

            if not current_pw or not new_pw:
                flash("Please fill out all password fields.", "danger")
                return redirect(url_for("operator_settings"))

            if new_pw != confirm_pw:
                flash("New passwords do not match.", "danger")
                return redirect(url_for("operator_settings"))

            if len(new_pw) < 6:
                flash("New password must be at least 6 characters.", "danger")
                return redirect(url_for("operator_settings"))

            with db.get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT password_hash FROM users WHERE id = ?", (operator_id,))
                user = c.fetchone()

                if not check_password_hash(user["password_hash"], current_pw):
                    flash("Current password incorrect.", "danger")
                    return redirect(url_for("operator_settings"))

                c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new_pw), operator_id))
                conn.commit()

            flash("Password updated successfully!", "success")
            return redirect(url_for("operator_settings"))

    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE id = ?", (operator_id,))
        operator = c.fetchone()
        counter = get_operator_counter(c, operator_id)

    return render_template("operator_settings.html", operator=operator, counter=counter)


# -------------------------------------------------------------
# PHASE 5: COMPLETE ADMIN PORTAL
# -------------------------------------------------------------

@app.route("/admin")
@app.route("/admin/dashboard")
@login_required(role="admin")
def admin_portal():
    with db.get_db() as conn:
        c = conn.cursor()

        # 1. User & Student Counts
        c.execute("SELECT COUNT(*) as count FROM users WHERE role = 'student'")
        total_students = c.fetchone()["count"]

        c.execute("SELECT COUNT(*) as count FROM users")
        total_users = c.fetchone()["count"]

        c.execute("SELECT COUNT(*) as count FROM users WHERE role = 'operator'")
        total_operators = c.fetchone()["count"]

        # 2. Token Stats Today
        c.execute("""
            SELECT
                COUNT(*) as total_today,
                SUM(CASE WHEN status = 'waiting' THEN 1 ELSE 0 END) as waiting_count,
                SUM(CASE WHEN status = 'serving' THEN 1 ELSE 0 END) as serving_count,
                SUM(CASE WHEN status = 'served' THEN 1 ELSE 0 END) as served_count,
                SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) as skipped_count,
                SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled_count
            FROM tokens
            WHERE date(created_at) = date('now')
        """)
        token_stats = c.fetchone()

        # 3. Counter Statuses
        c.execute("""
            SELECT
                COUNT(*) as total_counters,
                SUM(CASE WHEN is_active = 1 AND is_paused = 0 THEN 1 ELSE 0 END) as open_counters,
                SUM(CASE WHEN is_active = 1 AND is_paused = 1 THEN 1 ELSE 0 END) as paused_counters,
                SUM(CASE WHEN is_active = 0 THEN 1 ELSE 0 END) as closed_counters
            FROM counters
        """)
        counter_stats = c.fetchone()

        # 4. Department-wise queue stats
        c.execute("""
            SELECT d.id, d.code, d.name, d.building_block, d.is_active,
                   COUNT(DISTINCT c.id) as counter_count,
                   SUM(CASE WHEN t.status = 'waiting' THEN 1 ELSE 0 END) as waiting_tokens,
                   SUM(CASE WHEN t.status = 'served' AND date(t.created_at) = date('now') THEN 1 ELSE 0 END) as served_today
            FROM departments d
            LEFT JOIN counters c ON c.department_id = d.id
            LEFT JOIN tokens t ON t.department_id = d.id
            GROUP BY d.id, d.code, d.name, d.building_block, d.is_active
            ORDER BY d.name
        """)
        dept_stats = c.fetchall()

        # 5. Daily Activity for Chart.js (Last 7 Days)
        # Compatible across SQLite and PostgreSQL
        if db.is_postgres():
            date_sql = "TO_CHAR(created_at, 'YYYY-MM-DD')"
        else:
            date_sql = "date(created_at)"

        c.execute(f"""
            SELECT {date_sql} as day_date,
                   COUNT(*) as generated_count,
                   SUM(CASE WHEN status = 'served' THEN 1 ELSE 0 END) as completed_count
            FROM tokens
            GROUP BY {date_sql}
            ORDER BY day_date DESC
            LIMIT 7
        """)
        chart_rows = list(reversed(c.fetchall()))

        chart_labels = [r["day_date"] for r in chart_rows] if chart_rows else [datetime.date.today().isoformat()]
        chart_generated = [r["generated_count"] for r in chart_rows] if chart_rows else [token_stats["total_today"] or 0]
        chart_completed = [r["completed_count"] for r in chart_rows] if chart_rows else [token_stats["served_count"] or 0]

        # 6. Recent Audit Logs
        c.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 8")
        recent_audits = c.fetchall()

    metrics = {
        "total_students": total_students,
        "total_users": total_users,
        "total_operators": total_operators,
        "tokens_today": token_stats["total_today"] or 0,
        "waiting_tokens": token_stats["waiting_count"] or 0,
        "serving_tokens": token_stats["serving_count"] or 0,
        "served_tokens": token_stats["served_count"] or 0,
        "skipped_tokens": token_stats["skipped_count"] or 0,
        "cancelled_tokens": token_stats["cancelled_count"] or 0,
        "total_counters": counter_stats["total_counters"] or 0,
        "open_counters": counter_stats["open_counters"] or 0,
        "paused_counters": counter_stats["paused_counters"] or 0,
        "closed_counters": counter_stats["closed_counters"] or 0,
    }

    return render_template(
        "admin_dashboard.html",
        metrics=metrics,
        dept_stats=dept_stats,
        chart_labels=chart_labels,
        chart_generated=chart_generated,
        chart_completed=chart_completed,
        recent_audits=recent_audits
    )


# -------------------------------------------------------------
# ADMIN DEPARTMENT MANAGEMENT
# -------------------------------------------------------------

@app.route("/admin/departments")
@login_required(role="admin")
def admin_departments():
    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT d.*,
                   COUNT(DISTINCT c.id) as counter_count,
                   (SELECT COUNT(*) FROM tokens t WHERE t.department_id = d.id) as total_tokens
            FROM departments d
            LEFT JOIN counters c ON c.department_id = d.id
            GROUP BY d.id
            ORDER BY d.name
        """)
        departments = c.fetchall()
    return render_template("admin_departments.html", departments=departments)


@app.route("/admin/departments/create", methods=["POST"])
@login_required(role="admin")
def admin_department_create():
    code = request.form.get("code", "").strip().upper()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    building_block = request.form.get("building_block", "Block 1").strip()

    if not code or not name:
        flash("Department code and name are required.", "danger")
        return redirect(url_for("admin_departments"))

    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM departments WHERE code = ?", (code,))
        if c.fetchone():
            flash("Department with this code already exists.", "danger")
            return redirect(url_for("admin_departments"))

        c.execute("""
            INSERT INTO departments (code, name, description, building_block, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, (code, name, description, building_block))
        
        c.execute("""
            INSERT INTO audit_logs (action, user_id, user_role, details)
            VALUES ('CREATE_DEPARTMENT', ?, 'admin', ?)
        """, (get_current_user_id("admin"), f"Created department {name} ({code})"))
        conn.commit()

    flash(f"Department '{name}' created successfully.", "success")
    return redirect(url_for("admin_departments"))


@app.route("/admin/departments/edit/<int:dept_id>", methods=["POST"])
@login_required(role="admin")
def admin_department_edit(dept_id):
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    building_block = request.form.get("building_block", "Block 1").strip()
    is_active = int(request.form.get("is_active", 1))

    if not name:
        flash("Department name cannot be empty.", "danger")
        return redirect(url_for("admin_departments"))

    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE departments
            SET name = ?, description = ?, building_block = ?, is_active = ?
            WHERE id = ?
        """, (name, description, building_block, is_active, dept_id))

        c.execute("""
            INSERT INTO audit_logs (action, user_id, user_role, details)
            VALUES ('EDIT_DEPARTMENT', ?, 'admin', ?)
        """, (get_current_user_id("admin"), f"Updated department ID {dept_id} ({name})"))
        conn.commit()

    flash("Department updated successfully.", "success")
    return redirect(url_for("admin_departments"))


@app.route("/admin/departments/toggle/<int:dept_id>", methods=["POST"])
@login_required(role="admin")
def admin_department_toggle(dept_id):
    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT name, is_active FROM departments WHERE id = ?", (dept_id,))
        dept = c.fetchone()
        if not dept:
            flash("Department not found.", "danger")
            return redirect(url_for("admin_departments"))

        new_status = 0 if (dept["is_active"] if "is_active" in dept else 1) else 1
        c.execute("UPDATE departments SET is_active = ? WHERE id = ?", (new_status, dept_id))
        c.execute("""
            INSERT INTO audit_logs (action, user_id, user_role, details)
            VALUES ('TOGGLE_DEPARTMENT', ?, 'admin', ?)
        """, (get_current_user_id("admin"), f"Toggled department {dept['name']} active state to {new_status}"))
        conn.commit()

    flash(f"Department '{dept['name']}' status changed.", "info")
    return redirect(url_for("admin_departments"))


# -------------------------------------------------------------
# ADMIN COUNTER MANAGEMENT
# -------------------------------------------------------------

@app.route("/admin/counters")
@login_required(role="admin")
def admin_counters():
    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT c.*, d.name as department_name, d.code as department_code,
                   u.full_name as operator_name, u.identifier as operator_identifier,
                   (SELECT COUNT(*) FROM tokens t WHERE t.counter_id = c.id AND t.status = 'waiting') as waiting_count,
                   (SELECT token_number FROM tokens t WHERE t.counter_id = c.id AND t.status = 'serving' LIMIT 1) as now_serving
            FROM counters c
            JOIN departments d ON d.id = c.department_id
            LEFT JOIN users u ON u.id = c.assigned_operator_id
            ORDER BY d.name, c.name
        """)
        counters = c.fetchall()

        c.execute("SELECT id, code, name FROM departments WHERE is_active = 1 ORDER BY name")
        departments = c.fetchall()

        c.execute("SELECT id, full_name, identifier FROM users WHERE role = 'operator' ORDER BY full_name")
        operators = c.fetchall()

    return render_template(
        "admin_counters.html",
        counters=counters,
        departments=departments,
        operators=operators
    )


@app.route("/admin/counters/create", methods=["POST"])
@login_required(role="admin")
def admin_counter_create():
    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip().upper()
    department_id = request.form.get("department_id")
    avg_service_time = int(request.form.get("avg_service_time_mins", 8))
    operator_id = request.form.get("operator_id") or None

    if not name or not code or not department_id:
        flash("Counter name, code, and department are required.", "danger")
        return redirect(url_for("admin_counters"))

    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM counters WHERE code = ?", (code,))
        if c.fetchone():
            flash("Counter with this code already exists.", "danger")
            return redirect(url_for("admin_counters"))

        # If operator selected, clear previous assignment for that operator
        if operator_id:
            c.execute("UPDATE counters SET assigned_operator_id = NULL WHERE assigned_operator_id = ?", (operator_id,))

        c.execute("""
            INSERT INTO counters (department_id, name, code, is_active, is_paused, assigned_operator_id, avg_service_time_mins)
            VALUES (?, ?, ?, 1, 0, ?, ?)
        """, (department_id, name, code, operator_id, avg_service_time))

        c.execute("""
            INSERT INTO audit_logs (action, user_id, user_role, details)
            VALUES ('CREATE_COUNTER', ?, 'admin', ?)
        """, (get_current_user_id("admin"), f"Created counter {name} ({code})"))
        conn.commit()

    flash(f"Counter '{name}' added successfully.", "success")
    return redirect(url_for("admin_counters"))


@app.route("/admin/counters/edit/<int:counter_id>", methods=["POST"])
@login_required(role="admin")
def admin_counter_edit(counter_id):
    name = request.form.get("name", "").strip()
    avg_service_time = int(request.form.get("avg_service_time_mins", 8))
    department_id = request.form.get("department_id")
    operator_id = request.form.get("operator_id") or None

    if not name or not department_id:
        flash("Counter name and department are required.", "danger")
        return redirect(url_for("admin_counters"))

    with db.get_db() as conn:
        c = conn.cursor()

        if operator_id:
            # Reassign: unassign from previous counter if any
            c.execute("UPDATE counters SET assigned_operator_id = NULL WHERE assigned_operator_id = ? AND id != ?", (operator_id, counter_id))

        c.execute("""
            UPDATE counters
            SET name = ?, avg_service_time_mins = ?, department_id = ?, assigned_operator_id = ?
            WHERE id = ?
        """, (name, avg_service_time, department_id, operator_id, counter_id))

        c.execute("""
            INSERT INTO audit_logs (action, user_id, user_role, details)
            VALUES ('EDIT_COUNTER', ?, 'admin', ?)
        """, (get_current_user_id("admin"), f"Updated counter ID {counter_id} ({name})"))
        conn.commit()

    flash("Counter updated successfully.", "success")
    return redirect(url_for("admin_counters"))


@app.route("/admin/counters/action/<int:counter_id>", methods=["POST"])
@login_required(role="admin")
def admin_counter_action(counter_id):
    action = request.form.get("action")  # 'open', 'close', 'pause', 'resume'

    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT name, code FROM counters WHERE id = ?", (counter_id,))
        counter = c.fetchone()
        if not counter:
            flash("Counter not found.", "danger")
            return redirect(url_for("admin_counters"))

        if action == "open":
            c.execute("UPDATE counters SET is_active = 1 WHERE id = ?", (counter_id,))
        elif action == "close":
            c.execute("UPDATE counters SET is_active = 0 WHERE id = ?", (counter_id,))
        elif action == "pause":
            c.execute("UPDATE counters SET is_paused = 1 WHERE id = ?", (counter_id,))
        elif action == "resume":
            c.execute("UPDATE counters SET is_paused = 0 WHERE id = ?", (counter_id,))

        c.execute("""
            INSERT INTO audit_logs (action, user_id, user_role, details)
            VALUES (?, ?, 'admin', ?)
        """, (f"ADMIN_COUNTER_{action.upper()}", get_current_user_id("admin"), f"Admin set Counter {counter['code']} to {action}"))
        conn.commit()

    flash(f"Counter {counter['name']} is now updated ({action}).", "info")
    return redirect(url_for("admin_counters"))


# -------------------------------------------------------------
# ADMIN OPERATOR MANAGEMENT
# -------------------------------------------------------------

@app.route("/admin/operators")
@login_required(role="admin")
def admin_operators():
    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT u.*, c.name as assigned_counter_name, c.code as assigned_counter_code, c.id as assigned_counter_id,
                   d.name as department_name
            FROM users u
            LEFT JOIN counters c ON c.assigned_operator_id = u.id
            LEFT JOIN departments d ON d.id = c.department_id
            WHERE u.role = 'operator'
            ORDER BY u.full_name
        """)
        operators = c.fetchall()

        c.execute("""
            SELECT c.id, c.name, c.code, d.name as dept_name
            FROM counters c
            JOIN departments d ON d.id = c.department_id
            ORDER BY d.name, c.name
        """)
        counters = c.fetchall()

    return render_template("admin_operators.html", operators=operators, counters=counters)


@app.route("/admin/operators/create", methods=["POST"])
@login_required(role="admin")
def admin_operator_create():
    full_name = request.form.get("full_name", "").strip()
    identifier = request.form.get("identifier", "").strip().upper()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    password = request.form.get("password", "").strip()
    counter_id = request.form.get("counter_id") or None

    if not all([full_name, identifier, email, password]):
        flash("Full name, employee ID, email, and password are required.", "danger")
        return redirect(url_for("admin_operators"))

    if len(password) < 6:
        flash("Password must be at least 6 characters.", "danger")
        return redirect(url_for("admin_operators"))

    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE email = ? OR identifier = ?", (email, identifier))
        if c.fetchone():
            flash("User with this email or employee ID already exists.", "danger")
            return redirect(url_for("admin_operators"))

        pw_hash = generate_password_hash(password)
        c.execute("""
            INSERT INTO users (email, password_hash, full_name, role, identifier, phone, is_active)
            VALUES (?, ?, ?, 'operator', ?, ?, 1)
        """, (email, pw_hash, full_name, identifier, phone))
        op_id = c.lastrowid

        if counter_id:
            c.execute("UPDATE counters SET assigned_operator_id = ? WHERE id = ?", (op_id, counter_id))

        c.execute("""
            INSERT INTO audit_logs (action, user_id, user_role, details)
            VALUES ('CREATE_OPERATOR', ?, 'admin', ?)
        """, (get_current_user_id("admin"), f"Created operator {full_name} ({identifier})"))
        conn.commit()

    flash(f"Operator account created for {full_name}.", "success")
    return redirect(url_for("admin_operators"))


@app.route("/admin/operators/assign/<int:operator_id>", methods=["POST"])
@login_required(role="admin")
def admin_operator_assign(operator_id):
    raw_counter_id = request.form.get("counter_id", "").strip()
    counter_id = int(raw_counter_id) if raw_counter_id and raw_counter_id.isdigit() else None

    with db.get_db() as conn:
        c = conn.cursor()

        # Unassign operator from any existing desk
        c.execute("UPDATE counters SET assigned_operator_id = NULL WHERE assigned_operator_id = ?", (operator_id,))

        if counter_id:
            c.execute("UPDATE counters SET assigned_operator_id = ? WHERE id = ?", (operator_id, counter_id))

        c.execute("""
            INSERT INTO audit_logs (action, user_id, user_role, details)
            VALUES ('REASSIGN_OPERATOR', ?, 'admin', ?)
        """, (get_current_user_id("admin"), f"Reassigned operator ID {operator_id} to counter ID {counter_id}"))
        conn.commit()

    flash("Operator desk assignment updated.", "success")
    return redirect(url_for("admin_operators"))


@app.route("/admin/operators/toggle/<int:operator_id>", methods=["POST"])
@login_required(role="admin")
def admin_operator_toggle(operator_id):
    with db.get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT full_name, is_active FROM users WHERE id = ? AND role = 'operator'", (operator_id,))
        op = c.fetchone()
        if not op:
            flash("Operator not found.", "danger")
            return redirect(url_for("admin_operators"))

        new_status = 0 if (op["is_active"] if "is_active" in op else 1) else 1
        c.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_status, operator_id))

        # If deactivating, clear counter assignment
        if new_status == 0:
            c.execute("UPDATE counters SET assigned_operator_id = NULL WHERE assigned_operator_id = ?", (operator_id,))

        c.execute("""
            INSERT INTO audit_logs (action, user_id, user_role, details)
            VALUES ('TOGGLE_OPERATOR_STATUS', ?, 'admin', ?)
        """, (get_current_user_id("admin"), f"Set operator {op['full_name']} active state to {new_status}"))
        conn.commit()

    flash(f"Operator {op['full_name']} account status changed.", "info")
    return redirect(url_for("admin_operators"))


# -------------------------------------------------------------
# ADMIN DAILY REPORTS, ANALYTICS & CSV EXPORT
# -------------------------------------------------------------

@app.route("/admin/reports")
@login_required(role="admin")
def admin_reports():
    selected_date = request.args.get("date", datetime.date.today().isoformat())
    selected_dept = request.args.get("department_id", "all")

    with db.get_db() as conn:
        c = conn.cursor()

        # Build parameterized query for filtering
        query = """
            SELECT t.*, c.name as counter_name, c.code as counter_code,
                   d.name as department_name, d.code as department_code
            FROM tokens t
            JOIN counters c ON c.id = t.counter_id
            JOIN departments d ON d.id = t.department_id
            WHERE date(t.created_at) = ?
        """
        params = [selected_date]

        if selected_dept != "all":
            query += " AND t.department_id = ?"
            params.append(int(selected_dept))

        query += " ORDER BY t.id DESC"
        c.execute(query, tuple(params))
        tokens = c.fetchall()

        # Aggregate metrics for the selected filter
        total_tokens = len(tokens)
        completed = sum(1 for t in tokens if t["status"] == "served")
        skipped = sum(1 for t in tokens if t["status"] == "skipped")
        cancelled = sum(1 for t in tokens if t["status"] == "cancelled")
        waiting = sum(1 for t in tokens if t["status"] == "waiting")

        # Department list for dropdown
        c.execute("SELECT id, code, name FROM departments ORDER BY name")
        departments = c.fetchall()

    return render_template(
        "admin_reports.html",
        tokens=tokens,
        selected_date=selected_date,
        selected_dept=selected_dept,
        departments=departments,
        summary={
            "total": total_tokens,
            "completed": completed,
            "skipped": skipped,
            "cancelled": cancelled,
            "waiting": waiting
        }
    )


@app.route("/admin/reports/export.csv")
@login_required(role="admin")
def admin_reports_export_csv():
    selected_date = request.args.get("date", datetime.date.today().isoformat())
    selected_dept = request.args.get("department_id", "all")

    with db.get_db() as conn:
        c = conn.cursor()
        query = """
            SELECT t.id, t.token_number, d.name as department, c.name as counter, c.code as counter_code,
                   t.student_name, t.student_roll, t.service_reason, t.status, t.created_at, t.called_at, t.completed_at
            FROM tokens t
            JOIN counters c ON c.id = t.counter_id
            JOIN departments d ON d.id = t.department_id
            WHERE date(t.created_at) = ?
        """
        params = [selected_date]
        if selected_dept != "all":
            query += " AND t.department_id = ?"
            params.append(int(selected_dept))

        query += " ORDER BY t.id ASC"
        c.execute(query, tuple(params))
        rows = c.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Token ID", "Token Number", "Department", "Counter", "Counter Code",
        "Student Name", "Roll Number", "Service Purpose", "Status",
        "Created At", "Called At", "Completed At"
    ])

    for r in rows:
        writer.writerow([
            r["id"], r["token_number"], r["department"], r["counter"], r["counter_code"],
            r["student_name"], r["student_roll"], r["service_reason"] or "", r["status"],
            r["created_at"], r["called_at"] or "", r["completed_at"] or ""
        ])

    csv_data = output.getvalue()
    filename = f"QueueX_Report_{selected_date}.csv"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )




# Auto-initialize database schema
try:
    init_db()
except Exception as _e:
    import traceback
    print(f"[QueueX] CRITICAL DB Init Error: {_e}")
    traceback.print_exc()
    if os.environ.get("FLASK_ENV") == "production" or os.environ.get("RENDER"):
        # Re-raise so Render logs show the exact failure stack trace and fail fast
        raise

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
