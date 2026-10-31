"""
QueueX - Database Engine & Dual-Backend Abstraction Layer
Target: CGC University, Mohali, Punjab, India
Supports SQLite locally and PostgreSQL in production (Render / Railway).
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
    """Normalize DATABASE_URL for psycopg2 / SQLAlchemy compatibility."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def is_postgres():
    url = get_database_url()
    return bool(url.startswith("postgresql://") or url.startswith("postgres://"))


def resolve_sqlite_path():
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
    return os.path.abspath("queuex.db")


DB_NAME = resolve_sqlite_path()


class PostgresRowWrapper:
    """Row wrapper providing case-insensitive dict and tuple index access matching sqlite3.Row."""
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


class PostgresCursorWrapper:
    """Cursor wrapper adapting queries and lastrowid behavior for PostgreSQL."""
    def __init__(self, cursor):
        self.cursor = cursor
        self.lastrowid = None

    def execute(self, sql, params=None):
        adapted_sql = self.adapt_query(sql)

        is_insert = adapted_sql.strip().upper().startswith("INSERT INTO")
        has_returning = "RETURNING" in adapted_sql.upper()

        if is_insert and not has_returning and any(t in adapted_sql.lower() for t in ("users", "departments", "counters", "tokens", "feedback", "audit_logs")):
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
        # 1. Parameter placeholder translation: ? -> %s
        adapted = re.sub(r"\?", "%s", sql)
        # 2. DDL type mappings
        adapted = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "SERIAL PRIMARY KEY", adapted, flags=re.IGNORECASE)
        adapted = re.sub(r"PRAGMA\s+[^;]+;?", "", adapted, flags=re.IGNORECASE)
        # 3. Date functions
        adapted = re.sub(r"date\(\s*['\"]now['\"]\s*\)", "CURRENT_DATE", adapted, flags=re.IGNORECASE)
        adapted = re.sub(r"datetime\(\s*['\"]now['\"]\s*\)", "CURRENT_TIMESTAMP", adapted, flags=re.IGNORECASE)
        adapted = re.sub(r"date\((\w+)\)", r"\1::DATE", adapted, flags=re.IGNORECASE)
        return adapted

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class PostgresConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return PostgresCursorWrapper(self.conn.cursor())

    def commit(self):
        return self.conn.commit()

    def rollback(self):
        return self.conn.rollback()

    def close(self):
        return self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()


def get_db():
    if is_postgres():
        if not PSYCOPG2_AVAILABLE:
            raise RuntimeError("psycopg2 is required for PostgreSQL connection.")
        url = get_database_url()
        conn = psycopg2.connect(url)
        return PostgresConnectionWrapper(conn)

    # SQLite
    db_path = resolve_sqlite_path()
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
    except Exception:
        pass
    return conn
