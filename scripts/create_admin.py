"""Cria ou promove um usuario a Administrador.

Uso:
    python scripts/create_admin.py <usuario> <senha>
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import auth, db  # noqa: E402


def main():
    if len(sys.argv) < 3:
        sys.exit("Uso: python scripts/create_admin.py <usuario> <senha>")

    username = sys.argv[1].strip().lower()
    password = sys.argv[2]

    if len(username) < 3:
        sys.exit("O nome de usuario precisa ter pelo menos 3 caracteres.")
    if len(password) < 4:
        sys.exit("A senha precisa ter pelo menos 4 caracteres.")

    db.ensure_users_table()
    con = db.get_con()
    password_hash = auth.hash_password(password)

    existing = con.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        con.execute("UPDATE users SET password_hash = ?, is_admin = 1 WHERE username = ?", (password_hash, username))
        print(f"✅ Usuário '{username}' promovido a Administrador e senha atualizada com sucesso.")
    else:
        con.execute("INSERT INTO users(username, password_hash, is_admin) VALUES (?, ?, 1)", (username, password_hash))
        print(f"✅ Usuário Administrador '{username}' criado com sucesso.")

    con.commit()
    con.close()


if __name__ == "__main__":
    main()
