import pathlib
import sqlite3

BASE = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = BASE / "data" / "index.db"
MANUALS_DIR = BASE / "data" / "manuals"
PENDING_DIR = BASE / "data" / "pending_manuals"


def get_con() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def ensure_users_table() -> None:
    """Cria/atualiza tabelas de usuarios e submissoes se nao existirem."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    MANUALS_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    # Migracao simples se a tabela users ja existia sem is_admin
    cursor = con.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]
    if "is_admin" not in columns:
        con.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS manual_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT NOT NULL,
            brand TEXT NOT NULL,
            model TEXT NOT NULL,
            year TEXT NOT NULL,
            file_path TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            rejection_reason TEXT,
            submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
            reviewed_at TEXT
        )
        """
    )

    con.commit()
    con.close()

