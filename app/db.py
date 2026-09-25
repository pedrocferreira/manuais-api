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

    # Colunas do Kiwify na tabela de planos
    plan_columns = [row[1] for row in con.execute("PRAGMA table_info(plans)").fetchall()]
    if "kiwify_plan_id" not in plan_columns:
        # id da assinatura no Kiwify — e' o que identifica o plano no webhook,
        # porque os dois planos compartilham o mesmo product_id
        con.execute("ALTER TABLE plans ADD COLUMN kiwify_plan_id TEXT")
    if "kiwify_checkout_url" not in plan_columns:
        con.execute("ALTER TABLE plans ADD COLUMN kiwify_checkout_url TEXT")

    # Inserir planos padrao se ainda nao existem
    existing_slugs = [r[0] for r in con.execute("SELECT slug FROM plans").fetchall()]
    if "owner" not in existing_slugs:
        con.execute(
            "INSERT INTO plans (name, slug, price, description, max_manuals) VALUES (?, ?, ?, ?, ?)",
            ("Proprietário", "owner", 30.00, "Acesso a 1 modelo específico do acervo", 1),
        )
    if "mechanic" not in existing_slugs:
        con.execute(
            "INSERT INTO plans (name, slug, price, description, max_manuals) VALUES (?, ?, ?, ?, ?)",
            ("Mecânico", "mechanic", 120.00, "Acesso completo a todos os manuais do acervo", None),
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
    if "email" not in columns:
        # Email da compra no Kiwify — usado para casar o webhook com o usuario
        con.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "plan_expires_at" not in columns:
        # Validade da assinatura (NULL = sem validade, liberado manualmente pelo admin)
        con.execute("ALTER TABLE users ADD COLUMN plan_expires_at TEXT")
    if "plan_status" not in columns:
        con.execute("ALTER TABLE users ADD COLUMN plan_status TEXT")
    if "pending_activation" not in columns:
        # Conta criada pelo webhook (compra sem cadastro previo): sem senha ate ativar
        con.execute("ALTER TABLE users ADD COLUMN pending_activation INTEGER NOT NULL DEFAULT 0")
    if "cpf_last4" not in columns:
        con.execute("ALTER TABLE users ADD COLUMN cpf_last4 TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")

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

    # --- Tabela de logs de uso (analytics) ---
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            manual_id TEXT,
            manual_brand TEXT,
            manual_model TEXT,
            question TEXT,
            response_mode TEXT,
            pages_used INTEGER DEFAULT 0,
            answer TEXT,
            references_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    
    # Migração para adicionar answer e references_json caso não existam (já que a tabela já pode estar criada no ambiente do user)
    try:
        con.execute("ALTER TABLE usage_logs ADD COLUMN answer TEXT")
    except sqlite3.OperationalError:
        pass  # coluna já existe
    try:
        con.execute("ALTER TABLE usage_logs ADD COLUMN references_json TEXT")
    except sqlite3.OperationalError:
        pass  # coluna já existe

    # --- Tabela de pagamentos (Kiwify) ---
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            billing_id TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(plan_id) REFERENCES plans(id)
        )
        """
    )
    payment_columns = [row[1] for row in con.execute("PRAGMA table_info(payments)").fetchall()]
    if "kiwify_order_id" not in payment_columns:
        con.execute("ALTER TABLE payments ADD COLUMN kiwify_order_id TEXT")
    if "kiwify_subscription_id" not in payment_columns:
        con.execute("ALTER TABLE payments ADD COLUMN kiwify_subscription_id TEXT")
    if "updated_at" not in payment_columns:
        con.execute("ALTER TABLE payments ADD COLUMN updated_at TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(kiwify_order_id)")

    # --- Webhooks recebidos: idempotencia + auditoria ---
    # event_key = order_id:evento:updated_at. O Kiwify reenvia o mesmo evento
    # ate receber 200, entao o mesmo payload pode chegar varias vezes.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT UNIQUE NOT NULL,
            event_type TEXT,
            order_id TEXT,
            order_status TEXT,
            user_id INTEGER,
            plan_id INTEGER,
            action TEXT,
            detail TEXT,
            payload TEXT,
            received_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )

    con.commit()
    con.close()


