"""Integracao com o Kiwify: checkout, webhook e liberacao/revogacao de acesso.

Os dois planos (Proprietario e Mecanico) sao ofertas do MESMO produto no Kiwify,
entao o `product_id` nao distingue um do outro: o que identifica o plano e' o id da
assinatura (`Subscription.plan.id`), configurado em KIWIFY_PLAN_ID_*.
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import db

KIWIFY_API_BASE = "https://public-api.kiwify.com/v1"

# Dias de tolerancia depois do vencimento antes de cortar o acesso
GRACE_DAYS = 3

# webhook_event_type -> acao (os nomes em portugues sao os dos gatilhos do painel)
GRANT_EVENTS = {"order_approved", "compra_aprovada", "subscription_renewed"}
REVOKE_EVENTS = {"order_refunded", "compra_reembolsada", "chargeback"}
# Cancelamento/atraso nao cortam na hora: o acesso vale ate o fim do periodo pago
SOFT_EVENTS = {"subscription_canceled", "subscription_late"}

GRANT_STATUS = {"paid", "approved"}
REVOKE_STATUS = {"refunded", "chargedback", "chargeback"}

# slug do plano local -> variaveis de ambiente
PLAN_ENV = {
    "owner": ("KIWIFY_CHECKOUT_OWNER", "KIWIFY_PLAN_ID_OWNER", "KIWIFY_PRICE_OWNER"),
    "mechanic": ("KIWIFY_CHECKOUT_MECHANIC", "KIWIFY_PLAN_ID_MECHANIC", "KIWIFY_PRICE_MECHANIC"),
}


def get_kiwify_config() -> dict:
    return {
        "account_id": os.environ.get("KIWIFY_ACCOUNT_ID", ""),
        "client_id": os.environ.get("KIWIFY_CLIENT_ID", ""),
        "client_secret": os.environ.get("KIWIFY_CLIENT_SECRET", ""),
        "product_id": os.environ.get("KIWIFY_PRODUCT_ID", ""),
        "webhook_token": os.environ.get("KIWIFY_WEBHOOK_TOKEN", ""),
        "plans": {
            slug: {
                "checkout_url": os.environ.get(env_checkout, "").strip(),
                "kiwify_plan_id": os.environ.get(env_plan, "").strip(),
                "price": os.environ.get(env_price, "").strip(),
            }
            for slug, (env_checkout, env_plan, env_price) in PLAN_ENV.items()
        },
    }


# --------------------------------------------------------------------------- #
# Datas
# --------------------------------------------------------------------------- #

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(dt: datetime) -> str:
    """Formato do sqlite datetime('now'), para comparar com string mesmo."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_iso(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _expires_from_payload(payload: dict) -> str | None:
    """Ate quando o acesso vale. None = sem validade (compra avulsa/vitalicia)."""
    sub = payload.get("Subscription") or {}
    if not sub:
        return None

    nxt = _parse_iso(sub.get("next_payment"))
    if not nxt:
        frequency = ((sub.get("plan") or {}).get("frequency") or "monthly").lower()
        days = {"weekly": 7, "monthly": 31, "quarterly": 93, "semiannually": 184, "yearly": 366}
        nxt = _now() + timedelta(days=days.get(frequency, 31))

    return _fmt(nxt + timedelta(days=GRACE_DAYS))


# --------------------------------------------------------------------------- #
# Planos: espelha a configuracao do Kiwify na tabela local
# --------------------------------------------------------------------------- #

def sync_plans_from_config() -> None:
    """Grava checkout_url / kiwify_plan_id / preco nos planos locais.

    O Kiwify e' quem cobra, entao o preco de la' e' a fonte da verdade.
    """
    config = get_kiwify_config()
    con = db.get_con()
    for slug, plan_config in config["plans"].items():
        row = con.execute("SELECT id, price FROM plans WHERE slug = ?", (slug,)).fetchone()
        if not row:
            continue
        price = row["price"]
        if plan_config["price"]:
            try:
                price = float(plan_config["price"].replace(",", "."))
            except ValueError:
                pass
        con.execute(
            "UPDATE plans SET kiwify_plan_id = ?, kiwify_checkout_url = ?, price = ? WHERE id = ?",
            (
                plan_config["kiwify_plan_id"] or None,
                plan_config["checkout_url"] or None,
                price,
                row["id"],
            ),
        )
    con.commit()
    con.close()


# --------------------------------------------------------------------------- #
# Checkout
# --------------------------------------------------------------------------- #

def create_checkout(user_id: int, plan_slug: str, return_url: str | None = None,
                    email: str | None = None, name: str | None = None) -> str:
    """Monta a URL de checkout do Kiwify com o id do usuario no parametro `src`.

    O Kiwify devolve esse `src` em TrackingParameters no webhook — e' assim que
    amarramos o pagamento ao usuario que clicou.
    """
    config = get_kiwify_config()
    plan_config = config["plans"].get(plan_slug)
    if plan_config is None:
        raise ValueError(f"Plano '{plan_slug}' nao suportado.")

    base_url = plan_config["checkout_url"]
    if not base_url:
        env_name = PLAN_ENV[plan_slug][0]
        raise ValueError(f"Link de checkout do Kiwify nao configurado ({env_name} no .env).")

    params = {"src": str(user_id)}
    if email:
        params["email"] = email          # pre-preenche o checkout e ajuda a casar a compra
    if name:
        params["name"] = name
    separator = "&" if "?" in base_url else "?"
    checkout_url = f"{base_url}{separator}{urllib.parse.urlencode(params)}"

    con = db.get_con()
    plan = con.execute("SELECT id FROM plans WHERE slug = ?", (plan_slug,)).fetchone()
    if plan:
        con.execute(
            "INSERT INTO payments (billing_id, user_id, plan_id, status, updated_at) "
            "VALUES (?, ?, ?, 'pending', datetime('now'))",
            (f"kwf_pending_{secrets.token_hex(8)}", user_id, plan["id"]),
        )
        con.commit()
    con.close()

    return checkout_url


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #

def verify_signature(body_bytes: bytes, query_params) -> tuple[bool, str]:
    """Valida o webhook do Kiwify.

    O Kiwify acrescenta `?signature=<HMAC-SHA1 do corpo cru>` na URL cadastrada,
    assinado com o token do webhook. Tambem aceitamos `?token=<token>` para quem
    cadastra a URL com o token embutido. Sem token configurado, recusa tudo —
    caso contrario qualquer POST anonimo liberaria plano de graca.
    """
    token = get_kiwify_config()["webhook_token"]
    if not token:
        return False, "KIWIFY_WEBHOOK_TOKEN nao configurado no .env"

    signature = query_params.get("signature") or ""
    if signature:
        expected = hmac.new(token.encode(), body_bytes, hashlib.sha1).hexdigest()
        if hmac.compare_digest(expected, signature.lower()):
            return True, "signature"
        return False, "assinatura invalida"

    if hmac.compare_digest(query_params.get("token") or "", token):
        return True, "token"

    return False, "webhook sem signature/token"


def _parse_body(body_bytes: bytes) -> dict:
    try:
        payload = json.loads(body_bytes)
        if isinstance(payload, dict):
            return payload
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    parsed = urllib.parse.parse_qs(body_bytes.decode("utf-8", errors="replace"))
    return {k: v[0] for k, v in parsed.items()}


def _resolve_plan(con: sqlite3.Connection, payload: dict) -> sqlite3.Row | None:
    """Descobre o plano local pelo id da assinatura do Kiwify."""
    subscription = payload.get("Subscription") or {}
    kiwify_plan_id = (subscription.get("plan") or {}).get("id") or payload.get("plan_id")
    if kiwify_plan_id:
        row = con.execute("SELECT * FROM plans WHERE kiwify_plan_id = ?", (kiwify_plan_id,)).fetchone()
        if row:
            return row
    return None


def _resolve_user(con: sqlite3.Connection, payload: dict) -> tuple[sqlite3.Row | None, str]:
    """Acha o usuario da compra: src do checkout, depois email, depois cria a conta."""
    customer = payload.get("Customer") or {}
    email = (customer.get("email") or "").strip().lower()

    tracking = payload.get("TrackingParameters")
    src = tracking.get("src") if isinstance(tracking, dict) else None
    src = src or payload.get("src")
    if src:
        try:
            row = con.execute("SELECT * FROM users WHERE id = ?", (int(src),)).fetchone()
            if row:
                return row, "src"
        except (TypeError, ValueError):
            pass

    if email:
        row = con.execute(
            "SELECT * FROM users WHERE lower(email) = ? OR username = ? ORDER BY id LIMIT 1",
            (email, email),
        ).fetchone()
        if row:
            return row, "email"

        # Comprou pelo link do Kiwify sem ter conta: cria pendente de ativacao.
        # Sem senha valida ate a pessoa definir uma em /ativar.
        cpf = "".join(ch for ch in str(customer.get("CPF") or "") if ch.isdigit())
        cur = con.execute(
            "INSERT INTO users (username, password_hash, is_admin, email, pending_activation, cpf_last4) "
            "VALUES (?, '', 0, ?, 1, ?)",
            (email, email, cpf[-4:] if len(cpf) >= 4 else None),
        )
        row = con.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        return row, "criado"

    return None, "sem src nem email no payload"


def _grant(con: sqlite3.Connection, user: sqlite3.Row, plan: sqlite3.Row, expires_at: str | None) -> None:
    # Troca de plano limpa a moto escolhida (so' vale para o plano Proprietario)
    plan_manual_id = user["plan_manual_id"] if user["plan_id"] == plan["id"] else None
    con.execute(
        "UPDATE users SET plan_id = ?, plan_manual_id = ?, plan_expires_at = ?, plan_status = 'active' WHERE id = ?",
        (plan["id"], plan_manual_id, expires_at, user["id"]),
    )


def _revoke(con: sqlite3.Connection, user_id: int, status: str) -> None:
    con.execute(
        "UPDATE users SET plan_id = NULL, plan_manual_id = NULL, plan_expires_at = NULL, plan_status = ? WHERE id = ?",
        (status, user_id),
    )


def _record_payment(con: sqlite3.Connection, user_id: int, plan_id: int, payload: dict, status: str) -> None:
    """Fecha o pagamento pendente do usuario (ou cria um) com o pedido real."""
    order_id = payload.get("order_id") or payload.get("subscription_id") or secrets.token_hex(8)
    subscription_id = payload.get("subscription_id") or (payload.get("Subscription") or {}).get("id")

    existing = con.execute("SELECT id FROM payments WHERE kiwify_order_id = ?", (order_id,)).fetchone()
    if existing:
        con.execute(
            "UPDATE payments SET status = ?, plan_id = ?, updated_at = datetime('now') WHERE id = ?",
            (status, plan_id, existing["id"]),
        )
        return

    pending = con.execute(
        "SELECT id FROM payments WHERE user_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if pending:
        con.execute(
            "UPDATE payments SET status = ?, plan_id = ?, kiwify_order_id = ?, kiwify_subscription_id = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (status, plan_id, order_id, subscription_id, pending["id"]),
        )
        return

    # billing_id e' UNIQUE e legado; o sufixo evita colisao em renovacoes do mesmo pedido
    con.execute(
        "INSERT INTO payments (billing_id, user_id, plan_id, status, kiwify_order_id, kiwify_subscription_id, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (f"kwf_{order_id}_{secrets.token_hex(4)}", user_id, plan_id, status, order_id, subscription_id),
    )


def process_webhook(body_bytes: bytes, query_params) -> dict:
    """Processa o webhook do Kiwify. Devolve {ok, action, detail} para a rota."""
    valid, how = verify_signature(body_bytes, query_params)
    if not valid:
        return {"ok": False, "action": "rejected", "detail": how}

    payload = _parse_body(body_bytes)
    event_type = (payload.get("webhook_event_type") or "").lower()
    order_status = (payload.get("order_status") or "").lower()
    order_id = payload.get("order_id") or payload.get("subscription_id") or ""

    # Idempotencia: o Kiwify reenvia o mesmo evento ate receber 200.
    # Carrinho abandonado e' o unico gatilho sem order_id — nesse caso a chave
    # sai do proprio corpo, senao todos colidiriam na mesma linha.
    if order_id:
        event_key = f"{order_id}:{event_type}:{payload.get('updated_at') or ''}"
    else:
        event_key = f"{event_type}:{hashlib.sha1(body_bytes).hexdigest()}"
    con = db.get_con()
    try:
        already = con.execute(
            "SELECT action, detail FROM webhook_events WHERE event_key = ?", (event_key,)
        ).fetchone()
        if already:
            return {"ok": True, "action": "duplicate", "detail": f"ja processado ({already['action']})"}

        if event_type in REVOKE_EVENTS or order_status in REVOKE_STATUS:
            action = "revoke"
        elif event_type in SOFT_EVENTS:
            action = "soft"
        elif event_type in GRANT_EVENTS or order_status in GRANT_STATUS:
            action = "grant"
        else:
            action = "ignored"

        user, user_how = (None, "")
        plan = None
        detail = ""

        if action == "ignored":
            detail = f"evento sem acao: {event_type or order_status or '?'}"
        else:
            user, user_how = _resolve_user(con, payload)
            if not user:
                action, detail = "error", f"usuario nao identificado: {user_how}"

        if action == "grant":
            plan = _resolve_plan(con, payload)
            if not plan:
                # Ultimo recurso: o plano do pagamento pendente que o usuario abriu
                pending = con.execute(
                    "SELECT plan_id FROM payments WHERE user_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
                    (user["id"],),
                ).fetchone()
                if pending:
                    plan = con.execute("SELECT * FROM plans WHERE id = ?", (pending["plan_id"],)).fetchone()
            if not plan:
                action, detail = "error", "plano nao identificado (confira KIWIFY_PLAN_ID_* no .env)"
            else:
                expires_at = _expires_from_payload(payload)
                _grant(con, user, plan, expires_at)
                _record_payment(con, user["id"], plan["id"], payload, "paid")
                detail = f"plano {plan['slug']} liberado ate {expires_at or 'sem validade'} (match por {user_how})"

        elif action == "revoke":
            _revoke(con, user["id"], order_status or event_type or "revoked")
            if user["plan_id"]:
                _record_payment(con, user["id"], user["plan_id"], payload, order_status or "refunded")
            detail = f"acesso revogado ({event_type or order_status}, match por {user_how})"

        elif action == "soft":
            # Nao corta agora: plan_expires_at ja' limita o acesso ao periodo pago
            status = "canceled" if "cancel" in event_type else "late"
            con.execute("UPDATE users SET plan_status = ? WHERE id = ?", (status, user["id"]))
            detail = f"assinatura marcada como {status}; acesso mantido ate {user['plan_expires_at'] or 'o fim do periodo'}"

        con.execute(
            "INSERT INTO webhook_events (event_key, event_type, order_id, order_status, user_id, plan_id, "
            "action, detail, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_key, event_type, order_id, order_status,
                user["id"] if user else None, plan["id"] if plan else None,
                action, detail, json.dumps(payload, ensure_ascii=False)[:20000],
            ),
        )
        con.commit()
        return {"ok": action != "error", "action": action, "detail": detail}
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# API publica do Kiwify (diagnostico no painel admin)
# --------------------------------------------------------------------------- #

_token_cache = {"value": "", "expires_at": 0.0}
_token_lock = threading.Lock()


def api_token() -> str:
    """Token OAuth do Kiwify, com cache (vale 24h)."""
    with _token_lock:
        if _token_cache["value"] and _token_cache["expires_at"] > time.time():
            return _token_cache["value"]

        config = get_kiwify_config()
        if not config["client_id"] or not config["client_secret"]:
            raise ValueError("KIWIFY_CLIENT_ID / KIWIFY_CLIENT_SECRET nao configurados no .env")

        data = urllib.parse.urlencode({
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
        }).encode()
        req = urllib.request.Request(
            f"{KIWIFY_API_BASE}/oauth/token", data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())

        _token_cache["value"] = body["access_token"]
        _token_cache["expires_at"] = time.time() + int(body.get("expires_in", 86400)) - 300
        return _token_cache["value"]


def api_get(path: str) -> dict:
    config = get_kiwify_config()
    req = urllib.request.Request(
        f"{KIWIFY_API_BASE}/{path.lstrip('/')}",
        headers={
            "Authorization": f"Bearer {api_token()}",
            "x-kiwify-account-id": config["account_id"],
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def diagnostics() -> dict:
    """Confere a configuracao local contra o que existe no Kiwify."""
    config = get_kiwify_config()
    report = {
        "webhook_token_configurado": bool(config["webhook_token"]),
        "credenciais_api": bool(config["client_id"] and config["client_secret"] and config["account_id"]),
        "planos": [],
        "webhooks_cadastrados": [],
        "erros": [],
    }

    con = db.get_con()
    plans = con.execute("SELECT slug, name, price, kiwify_plan_id, kiwify_checkout_url FROM plans").fetchall()
    con.close()

    kiwify_plans, kiwify_links = {}, {}
    try:
        product = api_get(f"products/{config['product_id']}") if config["product_id"] else {}
        kiwify_plans = {s["id"]: s for s in product.get("subscriptions", [])}
        kiwify_links = {l["id"]: l for l in product.get("links", [])}
    except (urllib.error.URLError, ValueError, KeyError) as exc:
        report["erros"].append(f"Nao foi possivel ler o produto no Kiwify: {exc}")

    for plan in plans:
        kiwify_plan = kiwify_plans.get(plan["kiwify_plan_id"] or "")
        link_id = (plan["kiwify_checkout_url"] or "").rstrip("/").rsplit("/", 1)[-1]
        report["planos"].append({
            "slug": plan["slug"],
            "preco_local": plan["price"],
            "kiwify_plan_id": plan["kiwify_plan_id"],
            "checkout_url": plan["kiwify_checkout_url"],
            "encontrado_no_kiwify": bool(kiwify_plan),
            "preco_kiwify": (kiwify_plan or {}).get("price", 0) / 100 if kiwify_plan else None,
            "link_valido": link_id in kiwify_links,
        })

    try:
        report["webhooks_cadastrados"] = api_get("webhooks").get("data", [])
    except (urllib.error.URLError, ValueError, KeyError) as exc:
        report["erros"].append(f"Nao foi possivel listar os webhooks: {exc}")

    if not report["webhooks_cadastrados"]:
        report["erros"].append("Nenhum webhook cadastrado no Kiwify — as compras nao vao liberar acesso.")

    return report
