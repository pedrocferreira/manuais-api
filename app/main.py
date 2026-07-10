"""API de manuais de servico de motocicletas.

Rodar: uvicorn app.main:app --reload
Docs interativas: http://localhost:8000/docs
"""
from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, db, rag, search

STATIC_DIR = db.BASE / "app" / "static"

app = FastAPI(
    title="API Manuais de Servico - Motos",
    description=(
        "Consulta manuais de servico de motocicletas. O mecanico escolhe a moto, "
        "faz uma pergunta e recebe a resposta com referencias de pagina do PDF. "
        "Abra o PDF direto na pagina com GET /manuals/{id}/pdf#page=N."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ajustar quando o front tiver dominio definido
    allow_methods=["*"],
    allow_headers=["*"],
)

db.ensure_users_table()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AskRequest(BaseModel):
    question: str


class LoginRequest(BaseModel):
    username: str
    password: str


@app.get("/login")
def login_page():
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/")
def index(request: Request):
    token = request.cookies.get(auth.COOKIE_NAME)
    if not token or not auth._decode_token(token):
        return FileResponse(STATIC_DIR / "login.html")
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/auth/login")
def login(body: LoginRequest):
    con = db.get_con()
    row = con.execute(
        "SELECT username, password_hash FROM users WHERE username = ?", (body.username.strip().lower(),)
    ).fetchone()
    con.close()
    if not row or not auth.verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Usuario ou senha invalidos")
    token = auth.create_token(row["username"])
    response = JSONResponse({"ok": True, "username": row["username"]})
    response.set_cookie(
        auth.COOKIE_NAME, token, httponly=True, samesite="lax", max_age=auth.TOKEN_TTL_SECONDS,
    )
    return response


@app.post("/auth/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(auth.COOKIE_NAME)
    return response


@app.get("/auth/me")
def me(user: dict = Depends(auth.get_current_user)):
    return user


def _get_manual_or_404(manual_id: str) -> dict:
    con = db.get_con()
    row = con.execute("SELECT * FROM manuals WHERE id = ?", (manual_id,)).fetchone()
    con.close()
    if not row:
        raise HTTPException(404, f"Manual '{manual_id}' nao encontrado")
    return dict(row)


@app.get("/manuals")
def list_manuals(brand: str | None = None, user: dict = Depends(auth.get_current_user)):
    con = db.get_con()
    if brand:
        rows = con.execute(
            "SELECT * FROM manuals WHERE lower(brand) = lower(?) ORDER BY brand, model", (brand,)
        ).fetchall()
    else:
        rows = con.execute("SELECT * FROM manuals ORDER BY brand, model").fetchall()
    con.close()
    return [dict(r) | {"searchable": bool(r["indexed"])} for r in rows]


@app.get("/manuals/{manual_id}")
def get_manual(manual_id: str, user: dict = Depends(auth.get_current_user)):
    m = _get_manual_or_404(manual_id)
    return m | {"searchable": bool(m["indexed"])}


@app.get("/manuals/{manual_id}/search")
def search_manual(manual_id: str, q: str = Query(min_length=2), limit: int = Query(10, le=50),
                   user: dict = Depends(auth.get_current_user)):
    manual = _get_manual_or_404(manual_id)
    if not manual["indexed"]:
        raise HTTPException(422, "Este manual e escaneado (sem texto) e ainda nao foi indexado com OCR.")
    con = db.get_con()
    terms = search.extract_terms(q)
    # tenta AND (mais preciso); se nada, cai para OR (mais abrangente)
    results = search.search_pages(con, manual_id, search.build_fts_query(terms, "AND"), limit)
    if not results:
        results = search.search_pages(con, manual_id, search.build_fts_query(terms, "OR"), limit)
    con.close()
    return {
        "manual_id": manual_id,
        "query": q,
        "results": [r | {"pdf_url": f"/manuals/{manual_id}/pdf#page={r['page']}"} for r in results],
    }


@app.post("/manuals/{manual_id}/ask")
def ask_manual(manual_id: str, body: AskRequest, user: dict = Depends(auth.get_current_user)):
    manual = _get_manual_or_404(manual_id)
    if not manual["indexed"]:
        raise HTTPException(422, "Este manual e escaneado (sem texto) e ainda nao foi indexado com OCR.")
    con = db.get_con()
    result = rag.answer(con, manual, body.question)
    con.close()
    for r in result["references"]:
        r["pdf_url"] = f"/manuals/{manual_id}/pdf#page={r['page']}"
    return {"manual_id": manual_id, "question": body.question} | result


@app.get("/manuals/{manual_id}/pdf")
def get_pdf(manual_id: str, user: dict = Depends(auth.get_current_user)):
    manual = _get_manual_or_404(manual_id)
    path = db.MANUALS_DIR / manual["file"]
    if not path.exists():
        raise HTTPException(500, "Arquivo PDF nao encontrado no servidor")
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": "inline"})
