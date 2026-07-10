"""Autenticacao por usuario/senha com sessao via cookie (JWT).

- Senhas gravadas com hash PBKDF2-SHA256 (sem dependencia externa de criptografia).
- Login devolve um cookie httponly "session" com um JWT; o navegador reenvia esse
  cookie sozinho em toda requisicao (inclusive ao abrir o PDF em outra aba).
"""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time

import jwt
from fastapi import Depends, HTTPException, Request

from . import db

COOKIE_NAME = "session"
TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 dias
PBKDF2_ITERATIONS = 200_000

_SECRET_PATH = db.BASE / "data" / ".secret_key"


def _load_or_create_secret() -> str:
    env_secret = os.environ.get("SECRET_KEY")
    if env_secret:
        return env_secret
    if _SECRET_PATH.exists():
        return _SECRET_PATH.read_text().strip()
    _SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    _SECRET_PATH.write_text(secret)
    return secret


SECRET_KEY = _load_or_create_secret()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, hex_digest = stored.split("$")
        iterations = int(iterations)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations)
    return hmac.compare_digest(digest.hex(), hex_digest)


def create_token(username: str) -> str:
    payload = {"sub": username, "iat": int(time.time()), "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def _decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def get_user(con: sqlite3.Connection, username: str) -> dict | None:
    row = con.execute("SELECT id, username FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def get_current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    username = _decode_token(token) if token else None
    if not username:
        raise HTTPException(401, "Nao autenticado")
    con = db.get_con()
    user = get_user(con, username)
    con.close()
    if not user:
        raise HTTPException(401, "Nao autenticado")
    return user
