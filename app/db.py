import pathlib
import sqlite3

BASE = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = BASE / "data" / "index.db"
MANUALS_DIR = BASE / "data" / "manuals"


def get_con() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def ensure_users_table() -> None:
    """Cria a tabela de usuarios se nao existir (ingest.py recria manuals/pages, mas nao mexe em users)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    con.commit()
    con.close()
