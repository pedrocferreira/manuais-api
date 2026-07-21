"""Cria ou atualiza a senha de um usuario que podera fazer login no front.

Uso:
    python scripts/create_user.py <usuario> [--admin]
"""
import argparse
import getpass
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import auth, db  # noqa: E402



def main():
    parser = argparse.ArgumentParser(description="Cria ou atualiza a senha/papel de um usuario.")
    parser.add_argument("username", help="Nome do usuario")
    parser.add_argument("--admin", action="store_true", help="Define o usuario como administrador")
    args = parser.parse_args()

    username = args.username.strip().lower()
    is_admin = 1 if args.admin else 0

    password = getpass.getpass("Senha: ")
    confirm = getpass.getpass("Confirme a senha: ")
    if password != confirm:
        sys.exit("As senhas nao conferem.")
    if len(password) < 6:
        sys.exit("A senha precisa ter pelo menos 6 caracteres.")

    db.ensure_users_table()
    con = db.get_con()
    password_hash = auth.hash_password(password)
    existing = con.execute("SELECT id, is_admin FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        con.execute(
            "UPDATE users SET password_hash = ?, is_admin = max(is_admin, ?) WHERE username = ?",
            (password_hash, is_admin, username),
        )
        print(f"Senha/permissões atualizadas para o usuario '{username}' (is_admin={max(existing['is_admin'], is_admin)}).")
    else:
        con.execute(
            "INSERT INTO users(username, password_hash, is_admin) VALUES (?, ?, ?)",
            (username, password_hash, is_admin),
        )
        print(f"Usuario '{username}' criado com sucesso (is_admin={is_admin}).")
    con.commit()
    con.close()



if __name__ == "__main__":
    main()
