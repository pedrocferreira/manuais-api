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

# Garante a existencia do usuario admin padrao (admin / admin)
con = db.get_con()
_admin_row = con.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
_admin_hash = auth.hash_password("admin")
if not _admin_row:
    con.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES ('admin', ?, 1)",
        (_admin_hash,),
    )
else:
    con.execute(
        "UPDATE users SET password_hash = ?, is_admin = 1 WHERE username = 'admin'",
        (_admin_hash,),
    )
con.commit()
con.close()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AskRequest(BaseModel):
    question: str


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class RejectSubmissionRequest(BaseModel):
    reason: str | None = None


class PlanRequest(BaseModel):
    name: str
    slug: str
    price: float
    description: str | None = None
    max_manuals: int | None = None


class SetPlanRequest(BaseModel):
    plan_id: int | None = None
    plan_manual_id: str | None = None


class SelectManualRequest(BaseModel):
    manual_id: str


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
        return Response(
            content="""<!doctype html><html><head><title>Acesso Restrito</title>
            <style>body{background:#0b0d14;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}
            .card{background:#1a1e29;padding:40px;border-radius:16px;text-align:center;}
            a{color:#ff7a1a;text-decoration:none;font-weight:bold;}</style></head>
            <body><div class="card"><h1>⛔ Acesso Restrito</h1><p>Esta área é exclusiva para administradores.</p>
            <p><a href="/">← Voltar para o Sistema Principal</a></p></div></body></html>""",
            status_code=403,
            media_type="text/html",
        )
    return FileResponse(STATIC_DIR / "admin.html")


@app.post("/auth/register")
def register(body: RegisterRequest):
    username = body.username.strip().lower()
    password = body.password
    if not username or len(username) < 3:
        raise HTTPException(400, "O nome de usuário deve ter pelo menos 3 caracteres")
    if len(password) < 4:
        raise HTTPException(400, "A senha deve ter pelo menos 4 caracteres")

    con = db.get_con()
    existing = con.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        con.close()
        raise HTTPException(400, "Este nome de usuário já está cadastrado")

    password_hash = auth.hash_password(password)
    cur = con.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 0)",
        (username, password_hash),
    )
    con.commit()
    con.close()

    token = auth.create_token(username)
    response = JSONResponse({"ok": True, "username": username, "is_admin": False})
    response.set_cookie(
        auth.COOKIE_NAME, token, httponly=True, samesite="lax", max_age=auth.TOKEN_TTL_SECONDS,
    )
    return response



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
    # Filtro por plano: se usuario tem plano_manual_id definido, retorna apenas aquele manual
    if not user.get("is_admin") and user.get("plan_manual_id"):
        rows = con.execute(
            "SELECT * FROM manuals WHERE id = ? ORDER BY brand, model",
            (user["plan_manual_id"],),
        ).fetchall()
    elif brand:
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

    terms = result.get("terms", [])
    for r in result["references"]:
        r["pdf_url"] = f"/manuals/{manual_id}/pdf#page={r['page']}"
        r["image_url"] = pages.image_url(manual_id, r["page"], terms)

    # --- Log de uso para analytics e histórico ---
    try:
        import json
        con.execute(
            """
            INSERT INTO usage_logs (user_id, username, manual_id, manual_brand, manual_model, question, response_mode, pages_used, answer, references_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.get("id"),
                user.get("username"),
                manual_id,
                manual.get("brand"),
                manual.get("model"),
                body.question,
                result.get("mode", "unknown"),
                len(result.get("references", [])),
                result.get("answer", ""),
                json.dumps(result.get("references", [])),
            ),
        )
        con.commit()
    except Exception as e:
        print("Log DB falhou:", e)
        pass  # Nao falhar a resposta por causa do log

    con.close()
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


# --- ROTAS DE PLANOS ---

@app.get("/api/plans")
def list_plans_public():
    """Lista planos disponíveis (público, para exibir na tela de cadastro)."""
    con = db.get_con()
    rows = con.execute("SELECT * FROM plans ORDER BY price").fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.get("/api/admin/plans")
def list_plans(admin: dict = Depends(auth.get_current_admin_user)):
    con = db.get_con()
    rows = con.execute("SELECT * FROM plans ORDER BY price").fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.post("/api/admin/plans")
def create_plan(body: PlanRequest, admin: dict = Depends(auth.get_current_admin_user)):
    con = db.get_con()
    try:
        cur = con.execute(
            "INSERT INTO plans (name, slug, price, description, max_manuals) VALUES (?, ?, ?, ?, ?)",
            (body.name.strip(), body.slug.strip().lower(), body.price, body.description, body.max_manuals),
        )
        plan_id = cur.lastrowid
        con.commit()
        plan = dict(con.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone())
        con.close()
        return {"ok": True, "plan": plan}
    except Exception as e:
        con.close()
        raise HTTPException(400, f"Erro ao criar plano: {e}")


@app.put("/api/admin/plans/{plan_id}")
def update_plan(plan_id: int, body: PlanRequest, admin: dict = Depends(auth.get_current_admin_user)):
    con = db.get_con()
    row = con.execute("SELECT id FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(404, "Plano não encontrado")
    con.execute(
        "UPDATE plans SET name=?, slug=?, price=?, description=?, max_manuals=? WHERE id=?",
        (body.name.strip(), body.slug.strip().lower(), body.price, body.description, body.max_manuals, plan_id),
    )
    con.commit()
    plan = dict(con.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone())
    con.close()
    return {"ok": True, "plan": plan}


@app.delete("/api/admin/plans/{plan_id}")
def delete_plan(plan_id: int, admin: dict = Depends(auth.get_current_admin_user)):
    con = db.get_con()
    row = con.execute("SELECT id FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(404, "Plano não encontrado")
    con.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
    con.commit()
    con.close()
    return {"ok": True, "message": "Plano removido."}


# --- ROTAS DE GESTÃO DE USUÁRIOS ---

@app.get("/api/admin/users")
def list_users(admin: dict = Depends(auth.get_current_admin_user)):
    con = db.get_con()
    rows = con.execute(
        """
        SELECT u.id, u.username, u.is_admin, u.plan_id, u.plan_manual_id, u.created_at,
               p.name as plan_name, p.slug as plan_slug, p.price as plan_price,
               m.brand as manual_brand, m.model as manual_model
        FROM users u
        LEFT JOIN plans p ON u.plan_id = p.id
        LEFT JOIN manuals m ON u.plan_manual_id = m.id
        ORDER BY u.created_at DESC
        """
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.post("/api/admin/users/{user_id}/set-plan")
def set_user_plan(user_id: int, body: SetPlanRequest, admin: dict = Depends(auth.get_current_admin_user)):
    con = db.get_con()
    row = con.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(404, "Usuário não encontrado")

    # Se plan_id é None ou plano não é 'owner', limpa plan_manual_id
    plan_manual_id = body.plan_manual_id
    if body.plan_id:
        plan = con.execute("SELECT * FROM plans WHERE id = ?", (body.plan_id,)).fetchone()
        if plan and plan["max_manuals"] != 1:
            plan_manual_id = None  # plano sem restrição de moto
    else:
        plan_manual_id = None

    con.execute(
        "UPDATE users SET plan_id = ?, plan_manual_id = ? WHERE id = ?",
        (body.plan_id, plan_manual_id, user_id),
    )
    con.commit()
    con.close()
    return {"ok": True, "message": "Plano atualizado."}


# --- ROTA PARA USUARIO PROPRIETARIO SELECIONAR SUA MOTO ---

@app.post("/auth/select-manual")
def select_manual_for_plan(body: SelectManualRequest, user: dict = Depends(auth.get_current_user)):
    """Permite ao usuário Proprietário escolher qual manual acessar (uma única vez ou a qualquer momento)."""
    if user.get("is_admin"):
        raise HTTPException(400, "Admin não precisa selecionar manual")

    con = db.get_con()
    # Verificar se o plano do usuário é 'owner'
    plan_row = None
    if user.get("plan_id"):
        plan_row = con.execute("SELECT * FROM plans WHERE id = ?", (user["plan_id"],)).fetchone()

    if not plan_row or plan_row["max_manuals"] != 1:
        con.close()
        raise HTTPException(403, "Esta funcionalidade é apenas para o plano Proprietário")

    # Verificar se o manual existe
    manual = con.execute("SELECT id FROM manuals WHERE id = ?", (body.manual_id,)).fetchone()
    if not manual:
        con.close()
        raise HTTPException(404, "Manual não encontrado")

    con.execute("UPDATE users SET plan_manual_id = ? WHERE id = ?", (body.manual_id, user["id"]))
    con.commit()
    con.close()
    return {"ok": True, "message": "Manual selecionado com sucesso."}


# --- HISTÓRICO DO USUÁRIO ---

@app.get("/api/history")
def get_user_history(
    manual_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    user: dict = Depends(auth.get_current_user),
):
    """Retorna o histórico de perguntas do usuário logado."""
    con = db.get_con()
    if manual_id:
        rows = con.execute(
            """
            SELECT question, manual_id, manual_brand, manual_model, response_mode, pages_used, answer, references_json, created_at
            FROM usage_logs
            WHERE user_id = ? AND manual_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user["id"], manual_id, limit),
        ).fetchall()
    else:
        rows = con.execute(
            """
            SELECT question, manual_id, manual_brand, manual_model, response_mode, pages_used, answer, references_json, created_at
            FROM usage_logs
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user["id"], limit),
        ).fetchall()
    con.close()
    
    import json
    results = []
    for r in rows:
        d = dict(r)
        refs = d.pop("references_json", None)
        d["references"] = json.loads(refs) if refs else []
        results.append(d)
        
    return results


# --- ANALYTICS ---

@app.get("/api/admin/analytics")
def get_analytics(admin: dict = Depends(auth.get_current_admin_user)):
    con = db.get_con()

    # Total de perguntas
    total_questions = con.execute("SELECT COUNT(*) as c FROM usage_logs").fetchone()["c"]

    # Perguntas hoje
    questions_today = con.execute(
        "SELECT COUNT(*) as c FROM usage_logs WHERE date(created_at) = date('now')"
    ).fetchone()["c"]

    # Perguntas por dia (ultimos 30 dias)
    questions_by_day = [
        dict(r) for r in con.execute(
            """
            SELECT date(created_at) as date, COUNT(*) as count
            FROM usage_logs
            WHERE created_at >= datetime('now', '-30 days')
            GROUP BY date(created_at)
            ORDER BY date(created_at)
            """
        ).fetchall()
    ]

    # Top 10 manuais mais consultados
    top_manuals = [
        dict(r) for r in con.execute(
            """
            SELECT manual_id, manual_brand as brand, manual_model as model, COUNT(*) as count
            FROM usage_logs
            WHERE manual_id IS NOT NULL
            GROUP BY manual_id
            ORDER BY count DESC
            LIMIT 10
            """
        ).fetchall()
    ]

    # Top 10 usuarios mais ativos
    top_users = [
        dict(r) for r in con.execute(
            """
            SELECT username, COUNT(*) as count
            FROM usage_logs
            WHERE username IS NOT NULL
            GROUP BY username
            ORDER BY count DESC
            LIMIT 10
            """
        ).fetchall()
    ]

    # Uso por provedor de IA
    llm_rows = con.execute(
        """
        SELECT response_mode, COUNT(*) as count
        FROM usage_logs
        GROUP BY response_mode
        """
    ).fetchall()
    llm_usage = {r["response_mode"]: r["count"] for r in llm_rows}

    # Media de paginas por pergunta
    avg_row = con.execute(
        "SELECT AVG(pages_used) as avg_pages FROM usage_logs WHERE pages_used > 0"
    ).fetchone()
    avg_pages = round(avg_row["avg_pages"], 1) if avg_row["avg_pages"] else 0

    # 20 perguntas mais recentes
    recent_questions = [
        dict(r) for r in con.execute(
            """
            SELECT username, manual_brand, manual_model, question, response_mode, pages_used, created_at
            FROM usage_logs
            ORDER BY created_at DESC
            LIMIT 20
            """
        ).fetchall()
    ]

    # Perguntas esta semana vs semana passada
    this_week = con.execute(
        "SELECT COUNT(*) as c FROM usage_logs WHERE created_at >= datetime('now', '-7 days')"
    ).fetchone()["c"]
    last_week = con.execute(
        "SELECT COUNT(*) as c FROM usage_logs WHERE created_at >= datetime('now', '-14 days') AND created_at < datetime('now', '-7 days')"
    ).fetchone()["c"]

    con.close()

    return {
        "total_questions": total_questions,
        "questions_today": questions_today,
        "questions_this_week": this_week,
        "questions_last_week": last_week,
        "questions_by_day": questions_by_day,
        "top_manuals": top_manuals,
        "top_users": top_users,
        "llm_usage": llm_usage,
        "avg_pages_per_question": avg_pages,
        "recent_questions": recent_questions,
    }


@app.get("/auth/me")
def me(user: dict = Depends(auth.get_current_user)):
    con = db.get_con()
    plan = None
    if user.get("plan_id"):
        plan_row = con.execute("SELECT * FROM plans WHERE id = ?", (user["plan_id"],)).fetchone()
        if plan_row:
            plan = dict(plan_row)
    con.close()
    return {**user, "plan": plan}

