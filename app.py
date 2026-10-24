import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from flask_socketio import SocketIO, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "queuex_secret_key_change_later")
socketio = SocketIO(app, async_mode="threading")

DB_NAME = os.environ.get("QUEUEX_DB", "database.db")

# ---------- CONFIG ----------
MINUTES_PER_TOKEN = 2

OPERATOR_USERNAME = os.environ.get("OPERATOR_USERNAME", "operator")
OPERATOR_PASSWORD = os.environ.get("OPERATOR_PASSWORD", "operator123")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "superadmin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "super123")

COUNTERS = [
    {"name": "Examination Cell", "slug": "examination-cell"},
    {"name": "Accounts Office", "slug": "accounts-office"},
    {"name": "Library", "slug": "library"},
    {"name": "Cafeteria", "slug": "cafeteria"},
    {"name": "Admission Office", "slug": "admission-office"},
]


# ---------- DATABASE SETUP ----------
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(c, table, column):
    c.execute(f"PRAGMA table_info({table})")
    return any(row["name"] == column for row in c.fetchall())


def _add_column_if_missing(c, table, column, coltype):
    if not _column_exists(c, table, column):
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db():
    conn = get_db()
    c = conn.cursor()

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
    _add_column_if_missing(c, "counters", "status", "TEXT DEFAULT 'open'")
    _add_column_if_missing(c, "counters", "estimated_service_minutes", "INTEGER DEFAULT 2")
    _add_column_if_missing(c, "counters", "max_queue_size", "INTEGER DEFAULT 100")
    _add_column_if_missing(c, "counters", "priority_enabled", "INTEGER DEFAULT 0")
    _add_column_if_missing(c, "counters", "ai_enabled", "INTEGER DEFAULT 1")

    _add_column_if_missing(c, "tokens", "user_id", "INTEGER")
    _add_column_if_missing(c, "tokens", "priority", "INTEGER DEFAULT 0")
    _add_column_if_missing(c, "tokens", "service_id", "INTEGER")
    _add_column_if_missing(c, "tokens", "reason", "TEXT")
    _add_column_if_missing(c, "tokens", "called_at", "TIMESTAMP")
    _add_column_if_missing(c, "tokens", "skipped_at", "TIMESTAMP")
    _add_column_if_missing(c, "tokens", "cancelled_at", "TIMESTAMP")
    _add_column_if_missing(c, "tokens", "completed_by", "INTEGER")
    _add_column_if_missing(c, "tokens", "notes", "TEXT")

    for cdata in COUNTERS:
        c.execute(
            "INSERT OR IGNORE INTO counters (name, slug, current_token) VALUES (?, ?, 0)",
            (cdata["name"], cdata["slug"])
        )

    conn.commit()
    conn.close()


def get_counter_name(slug):
    for cdata in COUNTERS:
        if cdata["slug"] == slug:
            return cdata["name"]
    return slug


def is_valid_counter(slug):
    return any(cdata["slug"] == slug for cdata in COUNTERS)


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

        if not all([full_name, email, phone, roll_no, password, confirm_password]):
            error = "Please fill all required fields."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT id FROM users WHERE email = ?", (email,))
            if c.fetchone():
                error = "An account with this email already exists."
            else:
                c.execute(
                    """INSERT INTO users
                       (full_name, email, phone, password_hash, role, roll_no, department, semester, status)
                       VALUES (?, ?, ?, ?, 'student', ?, ?, ?, 'active')""",
                    (full_name, email, phone, generate_password_hash(password), roll_no, department, semester)
                )
                conn.commit()
                new_id = c.lastrowid
                conn.close()

                session["user_id"] = new_id
                session["role"] = "student"
                return redirect(url_for("student"))
            conn.close()

    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def student_login():
    error = None
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT * FROM users WHERE role = 'student' AND (email = ? OR roll_no = ?)",
            (identifier, identifier)
        )
        row = c.fetchone()

        if row and row["password_hash"] and check_password_hash(row["password_hash"], password):
            if row["status"] != "active":
                error = "This account is deactivated. Contact admin."
            else:
                c.execute("UPDATE users SET last_login = ? WHERE id = ?",
                          (datetime.now().isoformat(timespec="seconds"), row["id"]))
                conn.commit()
                session["user_id"] = row["id"]
                session["role"] = "student"
                conn.close()
                return redirect(url_for("student"))
        else:
            error = "Invalid email/roll number or password."
        conn.close()

    return render_template("student_login.html", error=error)


@app.route("/student/logout")
def student_logout():
    session.pop("user_id", None)
    if session.get("role") == "student":
        session.pop("role", None)
    return redirect(url_for("index"))


# ---------- STUDENT ROUTES ----------

@app.route("/")
def index():
    return render_template("index.html")


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
        father_name = request.form.get("father_name", "").strip()
        phone = student_user["phone"] or ""
    else:
        student_name = request.form.get("student_name", "").strip()
        roll_no = request.form.get("roll_no", "").strip()
        father_name = request.form.get("father_name", "").strip()
        phone = request.form.get("phone", "").strip()

        if not all([student_name, roll_no, father_name, phone]):
            return jsonify({"error": "all fields are required"}), 400

        if not phone.isdigit() or len(phone) != 10:
            return jsonify({"error": "phone must be 10 digits"}), 400

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT MAX(token_number) as max_token FROM tokens WHERE counter_slug = ?", (slug,))
    row = c.fetchone()
    new_token = (row["max_token"] or 0) + 1

    c.execute(
        """INSERT INTO tokens
           (token_number, counter_slug, student_name, roll_no, father_name, phone, status, user_id)
           VALUES (?, ?, ?, ?, ?, ?, 'waiting', ?)""",
        (new_token, slug, student_name, roll_no, father_name, phone,
         student_user["id"] if student_user else None)
    )
    conn.commit()
    conn.close()

    broadcast_queue_update(slug)

    return redirect(url_for("status", counter=slug, token=new_token))


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

    return render_template("my_tokens.html", tokens=tokens)


@app.route("/status")
def status():
    slug = request.args.get("counter")
    token = parse_token(request.args.get("token"))

    if not is_valid_counter(slug) or token is None:
        return redirect(url_for("student"))

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT student_name, roll_no FROM tokens WHERE counter_slug = ? AND token_number = ?",
        (slug, token)
    )
    row = c.fetchone()
    conn.close()

    return render_template(
        "status.html",
        counter_slug=slug,
        counter_name=get_counter_name(slug),
        token=token,
        student_name=row["student_name"] if row else "",
        roll_no=row["roll_no"] if row else ""
    )


@app.route("/api/status")
def api_status():
    slug = request.args.get("counter")
    token = parse_token(request.args.get("token"))

    if not is_valid_counter(slug) or token is None:
        return jsonify({"error": "invalid counter or token"}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT current_token FROM counters WHERE slug = ?", (slug,))
    row = c.fetchone()
    current_token = row["current_token"] if row else 0
    conn.close()

    people_ahead = max(token - current_token - 1, 0)
    student_status = "served" if token <= current_token else "waiting"
    if student_status == "served":
        people_ahead = 0

    return jsonify({
        "your_token": token,
        "currently_serving": current_token,
        "people_ahead": people_ahead,
        "estimated_wait": people_ahead * MINUTES_PER_TOKEN,
        "status": student_status
    })


# ---------- OPERATOR ROUTES ----------

@app.route("/operator/login", methods=["GET", "POST"])
def operator_login():
    error = None
    if request.method == "POST":
        if (request.form.get("username") == OPERATOR_USERNAME and
                request.form.get("password") == OPERATOR_PASSWORD):
            session["role"] = "operator"
            return redirect(url_for("operator_dashboard"))
        error = "Invalid username or password"
    return render_template("operator_login.html", error=error)


@app.route("/operator/logout")
def operator_logout():
    session.pop("role", None)
    return redirect(url_for("operator_login"))


@app.route("/operator")
def operator_dashboard():
    if session.get("role") != "operator":
        return redirect(url_for("operator_login"))
    return render_template("operator_dashboard.html", counters=COUNTERS)


@app.route("/api/operator/queue")
def api_operator_queue():
    if session.get("role") != "operator":
        return jsonify({"error": "unauthorized"}), 401

    slug = request.args.get("counter")
    if not is_valid_counter(slug):
        return jsonify({"error": "invalid counter"}), 400

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

    c.execute(
        "SELECT COUNT(*) as cnt FROM tokens WHERE counter_slug = ? AND status = 'served' AND date(created_at) = date('now')",
        (slug,)
    )
    served_today = c.fetchone()["cnt"]

    conn.close()

    return jsonify({
        "current_token": current_token,
        "waiting_count": len(waiting),
        "queue": waiting,
        "counter_status": counter_status,
        "served_today": served_today
    })


@app.route("/api/operator/call-next", methods=["POST"])
def call_next():
    if session.get("role") != "operator":
        return jsonify({"error": "unauthorized"}), 401

    slug = request.form.get("counter")
    if not is_valid_counter(slug):
        return jsonify({"error": "invalid counter"}), 400

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT current_token FROM counters WHERE slug = ?", (slug,))
    row = c.fetchone()
    current_token = row["current_token"] if row else 0

    c.execute(
        """SELECT token_number FROM tokens
           WHERE counter_slug = ? AND token_number > ? AND status = 'waiting'
           ORDER BY token_number ASC LIMIT 1""",
        (slug, current_token)
    )
    next_row = c.fetchone()
    if not next_row:
        conn.close()
        return jsonify({"error": "queue is empty", "current_token": current_token}), 400

    new_current = next_row["token_number"]

    c.execute("UPDATE counters SET current_token = ? WHERE slug = ?", (new_current, slug))
    c.execute(
        "UPDATE tokens SET status = 'served', served_at = ?, called_at = ? WHERE counter_slug = ? AND token_number = ?",
        (datetime.now().isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds"), slug, new_current)
    )
    conn.commit()
    conn.close()

    broadcast_queue_update(slug)
    return jsonify({"current_token": new_current})


@app.route("/api/operator/recall", methods=["POST"])
def recall_token():
    """Re-announce the currently serving token without advancing the queue."""
    if session.get("role") != "operator":
        return jsonify({"error": "unauthorized"}), 401

    slug = request.form.get("counter")
    if not is_valid_counter(slug):
        return jsonify({"error": "invalid counter"}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT current_token FROM counters WHERE slug = ?", (slug,))
    row = c.fetchone()
    current_token = row["current_token"] if row else 0
    conn.close()

    socketio.emit("token_recalled", {"counter_slug": slug, "current_token": current_token}, room=slug)
    return jsonify({"current_token": current_token, "message": "recalled"})


@app.route("/api/operator/skip", methods=["POST"])
def skip_token():
    if session.get("role") != "operator":
        return jsonify({"error": "unauthorized"}), 401

    slug = request.form.get("counter")
    if not is_valid_counter(slug):
        return jsonify({"error": "invalid counter"}), 400

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT current_token FROM counters WHERE slug = ?", (slug,))
    row = c.fetchone()
    current_token = row["current_token"] if row else 0

    c.execute(
        """SELECT token_number FROM tokens
           WHERE counter_slug = ? AND token_number > ? AND status = 'waiting'
           ORDER BY token_number ASC LIMIT 1""",
        (slug, current_token)
    )
    next_row = c.fetchone()
    if not next_row:
        conn.close()
        return jsonify({"error": "queue is empty", "current_token": current_token}), 400

    new_current = next_row["token_number"]

    c.execute("UPDATE counters SET current_token = ? WHERE slug = ?", (new_current, slug))
    c.execute(
        "UPDATE tokens SET status = 'skipped', skipped_at = ? WHERE counter_slug = ? AND token_number = ?",
        (datetime.now().isoformat(timespec="seconds"), slug, new_current)
    )
    conn.commit()
    conn.close()

    broadcast_queue_update(slug)
    return jsonify({"current_token": new_current})


@app.route("/api/operator/reset", methods=["POST"])
def reset_queue():
    if session.get("role") != "operator":
        return jsonify({"error": "unauthorized"}), 401

    slug = request.form.get("counter")
    if not is_valid_counter(slug):
        return jsonify({"error": "invalid counter"}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE counters SET current_token = 0 WHERE slug = ?", (slug,))
    c.execute("DELETE FROM tokens WHERE counter_slug = ?", (slug,))
    conn.commit()
    conn.close()

    broadcast_queue_update(slug)
    return jsonify({"message": "reset done"})


@app.route("/api/operator/set-status", methods=["POST"])
def set_counter_status():
    """Pause / Close / Reopen a counter."""
    if session.get("role") != "operator":
        return jsonify({"error": "unauthorized"}), 401

    slug = request.form.get("counter")
    new_status = request.form.get("status")

    if not is_valid_counter(slug):
        return jsonify({"error": "invalid counter"}), 400

    if new_status not in ("open", "paused", "closed"):
        return jsonify({"error": "invalid status"}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE counters SET status = ? WHERE slug = ?", (new_status, slug))
    conn.commit()
    conn.close()

    broadcast_queue_update(slug)
    return jsonify({"status": new_status})


# ---------- SUPER ADMIN ROUTES ----------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if (request.form.get("username") == ADMIN_USERNAME and
                request.form.get("password") == ADMIN_PASSWORD):
            session["role"] = "admin"
            return redirect(url_for("admin_dashboard"))
        error = "Invalid username or password"
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("role", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
def admin_dashboard():
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))
    return render_template("admin_dashboard.html", counters=COUNTERS)


@app.route("/api/admin/overview")
def api_admin_overview():
    if session.get("role") != "admin":
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()

    result = []
    for cdata in COUNTERS:
        slug = cdata["slug"]
        c.execute("SELECT current_token FROM counters WHERE slug = ?", (slug,))
        row = c.fetchone()
        current_token = row["current_token"] if row else 0

        c.execute(
            "SELECT COUNT(*) as cnt FROM tokens WHERE counter_slug = ? AND status = 'waiting' AND token_number > ?",
            (slug, current_token)
        )
        waiting_count = c.fetchone()["cnt"]

        c.execute(
            "SELECT COUNT(*) as cnt FROM tokens WHERE counter_slug = ? AND status = 'served' AND date(created_at) = date('now')",
            (slug,)
        )
        served_today = c.fetchone()["cnt"]

        result.append({
            "name": cdata["name"],
            "slug": slug,
            "current_token": current_token,
            "waiting_count": waiting_count,
            "served_today": served_today
        })

    conn.close()
    return jsonify(result)


@app.route("/api/admin/analytics")
def api_admin_analytics():
    if session.get("role") != "admin":
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()

    c.execute(
        """SELECT counter_slug, COUNT(*) as cnt FROM tokens
           WHERE date(created_at) = date('now') GROUP BY counter_slug"""
    )
    per_counter = {r["counter_slug"]: r["cnt"] for r in c.fetchall()}
    tokens_per_counter = [{"name": cd["name"], "count": per_counter.get(cd["slug"], 0)} for cd in COUNTERS]

    c.execute(
        """SELECT strftime('%H', created_at) as hr, COUNT(*) as cnt FROM tokens
           WHERE date(created_at) = date('now') GROUP BY hr ORDER BY hr"""
    )
    peak_hours = [{"hour": r["hr"] + ":00", "count": r["cnt"]} for r in c.fetchall()]

    c.execute(
        """SELECT AVG((julianday(served_at) - julianday(created_at)) * 24 * 60) as avg_wait
           FROM tokens WHERE status = 'served' AND date(created_at) = date('now')"""
    )
    avg_row = c.fetchone()
    avg_wait = round(avg_row["avg_wait"], 1) if avg_row["avg_wait"] else 0

    c.execute("SELECT COUNT(*) as cnt FROM tokens WHERE date(created_at) = date('now')")
    total_today = c.fetchone()["cnt"]

    busiest = max(tokens_per_counter, key=lambda x: x["count"]) if tokens_per_counter else None

    conn.close()

    return jsonify({
        "tokens_per_counter": tokens_per_counter,
        "peak_hours": peak_hours,
        "avg_wait": avg_wait,
        "total_today": total_today,
        "busiest_counter": busiest["name"] if busiest and busiest["count"] > 0 else "N/A"
    })


# ---------- SOCKET.IO EVENTS ----------

@socketio.on("join")
def handle_join(data):
    room = data.get("room")
    if room:
        join_room(room)

@socketio.on("leave")
def handle_leave(data):
    room = data.get("room")
    if room:
        leave_room(room)


# ---------- RUN APP ----------
if __name__ == "__main__":
    init_db()
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", "5000"))
    socketio.run(app, debug=debug, port=port, host="0.0.0.0", allow_unsafe_werkzeug=True)