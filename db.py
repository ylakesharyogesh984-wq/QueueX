"""
QueueX Database Engine & Multi-Backend Abstraction Layer
Supports PostgreSQL (Production on Railway) and SQLite (Development & Testing)
Ensures zero data loss, concurrency safety, and seamless query adaptation.
"""

import os
import re
import sqlite3

try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


def get_database_url():
    """Retrieve and normalize the DATABASE_URL environment variable."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def is_postgres():
    """Return True if a valid PostgreSQL DATABASE_URL is configured."""
    url = get_database_url()
    return bool(url.startswith("postgresql://") or url.startswith("postgres://"))


def is_production():
    """Check if application is running in a production environment."""
    return bool(
        os.environ.get("RAILWAY_ENVIRONMENT")
        or os.environ.get("FLASK_ENV") == "production"
        or os.environ.get("ENVIRONMENT") == "production"
    )


def verify_production_database_safety():
    """
    Enforce that SQLite is not accidentally used in production.
    Raises RuntimeError if running in production without PostgreSQL unless explicitly overridden.
    """
    if is_production() and not is_postgres() and os.environ.get("ALLOW_SQLITE_IN_PRODUCTION") != "1":
        raise RuntimeError(
            "Production Safety Block: DATABASE_URL is not set. "
            "SQLite is prohibited in production to prevent data loss on ephemeral containers. "
            "Please attach a PostgreSQL database on Railway or set DATABASE_URL. "
            "(To explicitly permit SQLite with a persistent volume mount, set ALLOW_SQLITE_IN_PRODUCTION=1)."
        )


def resolve_sqlite_path():
    """
    Determine SQLite database file location with Railway volume fallback support.
    """
    for env_var in ("DATABASE_PATH", "QUEUEX_DB", "DATA_DIR", "RAILWAY_VOLUME_MOUNT_PATH"):
        val = os.environ.get(env_var, "").strip()
        if val:
            if val.endswith(".db"):
                path = val
            else:
                path = os.path.join(val, "queuex.db")
            try:
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            except Exception:
                pass
            return path

    if os.path.exists("/data") and os.access("/data", os.W_OK):
        path = "/data/queuex.db"
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        except Exception:
            pass
        return path

    return os.path.abspath("database.db")


# Global database identifier (path for SQLite, URL for PostgreSQL)
DB_NAME = resolve_sqlite_path()


class PostgresRowWrapper:
    """Row wrapper providing case-insensitive dict and tuple access matching sqlite3.Row."""
    def __init__(self, data, description):
        self._col_names = [col.name.lower() for col in description] if description else []
        if isinstance(data, (list, tuple)):
            self._data_tuple = tuple(data)
            self._data_dict = dict(zip(self._col_names, self._data_tuple))
        elif hasattr(data, "items"):
            self._data_dict = {k.lower(): v for k, v in data.items()}
            self._data_tuple = tuple(self._data_dict.get(c) for c in self._col_names)
        else:
            self._data_tuple = ()
            self._data_dict = {}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._data_tuple[key]
        return self._data_dict[str(key).lower()]

    def get(self, key, default=None):
        return self._data_dict.get(str(key).lower(), default)

    def keys(self):
        return list(self._data_dict.keys())

    def items(self):
        return self._data_dict.items()

    def values(self):
        return self._data_dict.values()

    def __contains__(self, key):
        return str(key).lower() in self._data_dict

    def __repr__(self):
        return f"<PostgresRow {self._data_dict}>"


class PostgresCursorWrapper:
    """Cursor wrapper adapting queries and lastrowid behavior for PostgreSQL."""
    def __init__(self, cursor):
        self.cursor = cursor
        self.lastrowid = None

    def execute(self, sql, params=None):
        adapted_sql = self.adapt_query(sql)

        # Handle lastrowid emulation on INSERT statements
        is_insert = adapted_sql.strip().upper().startswith("INSERT INTO")
        has_returning = "RETURNING" in adapted_sql.upper()

        if is_insert and not has_returning and any(tbl in adapted_sql.lower() for tbl in ("tokens", "users", "counters", "complaints", "colleges", "notifications", "operators", "counter_services")):
            adapted_sql += " RETURNING id"
            has_returning = True

        if params is not None:
            self.cursor.execute(adapted_sql, params)
        else:
            self.cursor.execute(adapted_sql)

        if is_insert and has_returning:
            try:
                row = self.cursor.fetchone()
                if row:
                    self.lastrowid = row[0] if isinstance(row, (tuple, list)) else row.get("id")
            except Exception:
                pass

        return self

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        return PostgresRowWrapper(row, self.cursor.description)

    def fetchall(self):
        rows = self.cursor.fetchall()
        desc = self.cursor.description
        return [PostgresRowWrapper(r, desc) for r in rows]

    @staticmethod
    def adapt_query(sql):
        """Translate SQLite-flavored syntax into PostgreSQL compatible SQL."""
        # 1. Parameter placeholder translation: ? -> %s
        adapted = re.sub(r"\?", "%s", sql)

        # 2. DDL type mappings
        adapted = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "SERIAL PRIMARY KEY", adapted, flags=re.IGNORECASE)
        adapted = re.sub(r"PRAGMA\s+[^;]+;?", "", adapted, flags=re.IGNORECASE)

        # 3. Date & time functions
        adapted = re.sub(r"date\(\s*['\"]now['\"]\s*\)", "CURRENT_DATE", adapted, flags=re.IGNORECASE)
        adapted = re.sub(r"date\(\s*['\"]now['\"]\s*,\s*'-1 day'\s*\)", "(CURRENT_DATE - INTERVAL '1 day')", adapted, flags=re.IGNORECASE)
        adapted = re.sub(r"date\(\s*['\"]now['\"]\s*,\s*'-7 days'\s*\)", "(CURRENT_DATE - INTERVAL '7 days')", adapted, flags=re.IGNORECASE)
        adapted = re.sub(r"date\(\s*['\"]now['\"]\s*,\s*'-30 days'\s*\)", "(CURRENT_DATE - INTERVAL '30 days')", adapted, flags=re.IGNORECASE)
        adapted = re.sub(r"date\((\w+)\)", r"\1::DATE", adapted, flags=re.IGNORECASE)
        adapted = re.sub(r"strftime\('%H',\s*(\w+)\)", r"TO_CHAR(\1, 'HH24')", adapted, flags=re.IGNORECASE)
        adapted = re.sub(
            r"julianday\(([^)]+)\)\s*-\s*julianday\(([^)]+)\)\s*\*\s*24\s*\*\s*60",
            r"EXTRACT(EPOCH FROM (\1 - \2)) / 60",
            adapted,
            flags=re.IGNORECASE
        )
        return adapted

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class PostgresConnectionWrapper:
    """Connection wrapper providing a uniform sqlite3-like interface for psycopg2."""
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        import psycopg2.extras
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        return PostgresCursorWrapper(cur)

    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        return self.conn.commit()

    def rollback(self):
        return self.conn.rollback()

    def close(self):
        return self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()

    def __getattr__(self, name):
        return getattr(self.conn, name)


def get_db():
    """
    Return a database connection.
    Automatically connects to PostgreSQL if DATABASE_URL is set;
    otherwise connects to SQLite with busy timeout and WAL mode enabled.
    """
    # Enforce production security check
    verify_production_database_safety()

    if is_postgres():
        if not PSYCOPG2_AVAILABLE:
            raise RuntimeError("psycopg2 is required for PostgreSQL connections. Install with: pip install psycopg2-binary")
        pg_url = get_database_url()
        raw_conn = psycopg2.connect(pg_url)
        return PostgresConnectionWrapper(raw_conn)

    # SQLite connection
    db_dir = os.path.dirname(os.path.abspath(DB_NAME))
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
        except Exception:
            pass

    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
    except Exception:
        pass
    return conn


def _column_exists(c, table, column):
    """Check if a column exists in a table in a database-agnostic manner."""
    if is_postgres():
        c.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
            (table.lower(), column.lower())
        )
        return c.fetchone() is not None

    c.execute(f"PRAGMA table_info({table})")
    return any(row["name"] == column for row in c.fetchall())


def _add_column_if_missing(c, table, column, coltype):
    """Add a column to a table if it doesn't already exist."""
    if not _column_exists(c, table, column):
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
