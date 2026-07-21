"""API de manuais de servico de motocicletas.

Rodar: uvicorn app.main:app --reload
Docs interativas: http://localhost:8000/docs
"""
from dotenv import load_dotenv

load_dotenv()

import pathlib
import uuid
from datetime import datetime

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, db, indexer, pages, rag, search

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


class RejectSubmissionRequest(BaseModel):
    reason: str | None = None


@app.get("/login")
def login_page():
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/admin")
def admin_page(request: Request):
    token = request.cookies.get(auth.COOKIE_NAME)
    username = auth._decode_token(token) if token else None
    if not username:
        return FileResponse(STATIC_DIR / "login.html")
    con = db.get_con()
    user = auth.get_user(con, username)
    con.close()
    if not user or not user.get("is_admin"):
        raise HTTPException(403, "Acesso restrito a administradores")
    return FileResponse(STATIC_DIR / "admin.html")


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
        "SELECT username, password_hash, is_admin FROM users WHERE username = ?", (body.username.strip().lower(),)
    ).fetchone()
    con.close()
    if not row or not auth.verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Usuario ou senha invalidos")
    token = auth.create_token(row["username"])
    response = JSONResponse({"ok": True, "username": row["username"], "is_admin": bool(row["is_admin"])})
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
    results = search.search_pages(con, manual_id, search.build_fts_query(terms, "AND"), limit)
    if not results:
        results = search.search_pages(con, manual_id, search.build_fts_query(terms, "OR"), limit)
    con.close()
    return {
        "manual_id": manual_id,
        "query": q,
        "results": [
            r | {
                "pdf_url": f"/manuals/{manual_id}/pdf#page={r['page']}",
                "image_url": pages.image_url(manual_id, r["page"], terms),
            }
            for r in results
        ],
    }


@app.post("/manuals/{manual_id}/ask")
def ask_manual(manual_id: str, body: AskRequest, user: dict = Depends(auth.get_current_user)):
    manual = _get_manual_or_404(manual_id)
    if not manual["indexed"]:
        raise HTTPException(422, "Este manual e escaneado (sem texto) e ainda nao foi indexado com OCR.")
    con = db.get_con()
    result = rag.answer(con, manual, body.question)
    con.close()
    terms = result.get("terms", [])
    for r in result["references"]:
        r["pdf_url"] = f"/manuals/{manual_id}/pdf#page={r['page']}"
        r["image_url"] = pages.image_url(manual_id, r["page"], terms)
    return {"manual_id": manual_id, "question": body.question} | result


@app.get("/manuals/{manual_id}/pages/{page}/image")
def get_page_image(manual_id: str, page: int,
                   highlight: str | None = Query(None, description="termos separados por virgula"),
                   zoom: float = Query(2.0, ge=1.0, le=4.0),
                   user: dict = Depends(auth.get_current_user)):
    manual = _get_manual_or_404(manual_id)
    terms = [t.strip() for t in highlight.split(",")] if highlight else []
    try:
        png = pages.render_page_png(manual, page, zoom, terms)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=86400"})


@app.get("/manuals/{manual_id}/pdf")
def get_pdf(manual_id: str, user: dict = Depends(auth.get_current_user)):
    manual = _get_manual_or_404(manual_id)
    path = db.MANUALS_DIR / manual["file"]
    if not path.exists():
        raise HTTPException(500, "Arquivo PDF nao encontrado no servidor")
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": "inline"})


# --- FLUXO DE SUBMISSÃO DE MANUAIS POR USUÁRIOS ---

@app.post("/submissions")

async def submit_manual(
    brand: str = Form(...),
    model: str = Form(...),
    year: str = Form(...),
    file: UploadFile = File(...),
    user: dict = Depends(auth.get_current_user),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Apenas arquivos PDF são permitidos")
    
    unique_filename = f"{uuid.uuid4().hex}_{file.filename}"
    save_path = db.PENDING_DIR / unique_filename
    
    content = await file.read()
    save_path.write_bytes(content)
    
    con = db.get_con()
    cur = con.execute(
        """
        INSERT INTO manual_submissions (user_id, username, brand, model, year, file_path, original_filename, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (user["id"], user["username"], brand.strip(), model.strip(), year.strip(), str(save_path), file.filename),
    )
    submission_id = cur.lastrowid
    con.commit()
    con.close()

    return {"ok": True, "submission_id": submission_id, "message": "Manual enviado com sucesso para análise."}


@app.get("/submissions/mine")

def my_submissions(user: dict = Depends(auth.get_current_user)):
    con = db.get_con()
    rows = con.execute(
        "SELECT * FROM manual_submissions WHERE user_id = ? ORDER BY submitted_at DESC", (user["id"],)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


# --- ROTAS ADMINISTRATIVAS ---

@app.get("/api/admin/submissions")

def list_submissions(status: str | None = None, admin: dict = Depends(auth.get_current_admin_user)):
    con = db.get_con()
    if status:
        rows = con.execute(
            "SELECT * FROM manual_submissions WHERE status = ? ORDER BY submitted_at DESC", (status,)
        ).fetchall()
    else:
        rows = con.execute("SELECT * FROM manual_submissions ORDER BY submitted_at DESC").fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.post("/api/admin/submissions/{submission_id}/approve")

def approve_submission(submission_id: int, admin: dict = Depends(auth.get_current_admin_user)):
    con = db.get_con()
    sub = con.execute("SELECT * FROM manual_submissions WHERE id = ?", (submission_id,)).fetchone()
    if not sub:
        con.close()
        raise HTTPException(404, "Submissão não encontrada")
    if sub["status"] != "pending":
        con.close()
        raise HTTPException(400, f"Submissão já possui status '{sub['status']}'")

    file_path = pathlib.Path(sub["file_path"])
    if not file_path.exists():
        con.close()
        raise HTTPException(400, "Arquivo PDF temporário não encontrado no servidor")

    # Indexa o PDF e adiciona ao acervo oficial
    manual_meta = indexer.index_manual_pdf(
        pdf_source_path=file_path,
        brand=sub["brand"],
        model=sub["model"],
        year=sub["year"],
    )

    # Remove o arquivo temporario
    try:
        file_path.unlink()
    except OSError:
        pass

    now = datetime.now().isoformat()
    con.execute(
        "UPDATE manual_submissions SET status = 'approved', reviewed_at = ? WHERE id = ?", (now, submission_id)
    )
    con.commit()
    con.close()

    return {"ok": True, "manual": manual_meta, "message": "Manual aprovado e indexado no acervo com sucesso."}


@app.post("/api/admin/submissions/{submission_id}/reject")

def reject_submission(
    submission_id: int,
    body: RejectSubmissionRequest,
    admin: dict = Depends(auth.get_current_admin_user),
):
    con = db.get_con()
    sub = con.execute("SELECT * FROM manual_submissions WHERE id = ?", (submission_id,)).fetchone()
    if not sub:
        con.close()
        raise HTTPException(404, "Submissão não encontrada")
    
    file_path = pathlib.Path(sub["file_path"])
    if file_path.exists():
        try:
            file_path.unlink()
        except OSError:
            pass

    now = datetime.now().isoformat()
    con.execute(
        "UPDATE manual_submissions SET status = 'rejected', rejection_reason = ?, reviewed_at = ? WHERE id = ?",
        (body.reason, now, submission_id),
    )
    con.commit()
    con.close()

    return {"ok": True, "message": "Submissão rejeitada."}


@app.post("/api/admin/manuals")

async def admin_upload_manual(
    brand: str = Form(...),
    model: str = Form(...),
    year: str = Form(...),
    file: UploadFile = File(...),
    admin: dict = Depends(auth.get_current_admin_user),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Apenas arquivos PDF são permitidos")

    temp_path = db.PENDING_DIR / f"admin_upload_{uuid.uuid4().hex}_{file.filename}"
    content = await file.read()
    temp_path.write_bytes(content)

    try:
        manual_meta = indexer.index_manual_pdf(
            pdf_source_path=temp_path,
            brand=brand,
            model=model,
            year=year,
        )
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    return {"ok": True, "manual": manual_meta, "message": "Manual cadastrado e indexado com sucesso."}


@app.delete("/api/admin/manuals/{manual_id}")

def delete_manual(manual_id: str, admin: dict = Depends(auth.get_current_admin_user)):
    _get_manual_or_404(manual_id)
    indexer.remove_manual_from_db(manual_id)
    return {"ok": True, "message": f"Manual '{manual_id}' removido do acervo com sucesso."}

