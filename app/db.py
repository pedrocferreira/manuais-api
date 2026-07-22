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
    """Cria/atualiza tabelas de usuarios, submissoes e planos se nao existirem."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    MANUALS_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)

    # --- Tabela de planos (criada antes de users por causa da FK) ---
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            price REAL NOT NULL,
            description TEXT,
            max_manuals INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )

    # Inserir planos padrao se ainda nao existem
    existing_slugs = [r[0] for r in con.execute("SELECT slug FROM plans").fetchall()]
    if "owner" not in existing_slugs:
        con.execute(
            "INSERT INTO plans (name, slug, price, description, max_manuals) VALUES (?, ?, ?, ?, ?)",
            ("Proprietário", "owner", 15.90, "Acesso a 1 modelo específico do acervo", 1),
        )
    if "mechanic" not in existing_slugs:
        con.execute(
            "INSERT INTO plans (name, slug, price, description, max_manuals) VALUES (?, ?, ?, ?, ?)",
            ("Mecânico", "mechanic", 69.90, "Acesso completo a todos os manuais do acervo", None),
        )

    # --- Tabela de usuarios ---
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
    # Migracoes simples se a tabela ja existia sem colunas novas
    cursor = con.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]
    if "is_admin" not in columns:
        con.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    if "plan_id" not in columns:
        con.execute("ALTER TABLE users ADD COLUMN plan_id INTEGER")
    if "plan_manual_id" not in columns:
        # Para usuarios com plano Proprietario: qual manual especifico podem acessar
        con.execute("ALTER TABLE users ADD COLUMN plan_manual_id TEXT")

    # --- Tabela de submissoes ---
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


