"""Cria ou atualiza a senha de um usuario que podera fazer login no front.

Uso:
    python scripts/create_user.py <usuario>
(a senha e pedida de forma oculta, sem aparecer no terminal nem no historico)
"""
import getpass
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import auth, db  # noqa: E402


def main():
    if len(sys.argv) != 2:
        sys.exit("Uso: python scripts/create_user.py <usuario>")
    username = sys.argv[1].strip().lower()

    password = getpass.getpass("Senha: ")
    confirm = getpass.getpass("Confirme a senha: ")
    if password != confirm:
        sys.exit("As senhas nao conferem.")
    if len(password) < 6:
        sys.exit("A senha precisa ter pelo menos 6 caracteres.")

    db.ensure_users_table()
    con = db.get_con()
    password_hash = auth.hash_password(password)
    existing = con.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        con.execute("UPDATE users SET password_hash = ? WHERE username = ?", (password_hash, username))
        print(f"Senha atualizada para o usuario '{username}'.")
    else:
        con.execute("INSERT INTO users(username, password_hash) VALUES (?, ?)", (username, password_hash))
        print(f"Usuario '{username}' criado.")
    con.commit()
    con.close()


if __name__ == "__main__":
    main()
