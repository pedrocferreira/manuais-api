"""Responde perguntas do mecanico usando as paginas do manual como contexto.

Provedores de LLM suportados (variavel LLM_PROVIDER):
  groq   - usa apenas Groq (llama/mixtral, sem visao)
  gemini - usa apenas Gemini (com visao para imagens de paginas)
  auto   - tenta Groq primeiro; se falhar, cai no Gemini (padrao)

Variaveis de ambiente necessarias por provedor:
  GROQ_API_KEY   - chave da API Groq
  GEMINI_API_KEY - chave da API Google Gemini
"""
import json
import logging
import os
import sqlite3

from . import search

logger = logging.getLogger(__name__)

# --- Configuracao ---------------------------------------------------------
GEMINI_MODEL  = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL    = os.environ.get("GROQ_MODEL",   "llama-3.3-70b-versatile")
LLM_PROVIDER  = os.environ.get("LLM_PROVIDER", "auto").lower()  # groq | gemini | auto

MAX_CONTEXT_PAGES = 12
# Imagens de pagina so sao enviadas ao Gemini (Groq nao suporta visao)
MAX_IMAGE_PAGES = int(os.environ.get("RAG_IMAGE_PAGES", "6"))
IMAGE_ZOOM = 1.5
# Groq tem limite de tokens/min: reduzimos o contexto por pagina
GROQ_MAX_CHARS_PER_PAGE = int(os.environ.get("GROQ_MAX_CHARS", "2000"))
GEMINI_MAX_CHARS_PER_PAGE = int(os.environ.get("GEMINI_MAX_CHARS", "4000"))


# --- Deteccao de provedores disponiveis -----------------------------------

def _has_groq() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))

def _has_gemini() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))

def has_llm() -> bool:
    if LLM_PROVIDER == "groq":
        return _has_groq()
    if LLM_PROVIDER == "gemini":
        return _has_gemini()
    return _has_groq() or _has_gemini()  # auto


# --- Clientes -------------------------------------------------------------

def _groq_client():
    from groq import Groq
    return Groq(api_key=os.environ["GROQ_API_KEY"])

def _gemini_client():
    from google import genai
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


# --- Helpers --------------------------------------------------------------

def _is_quota_error(exc: Exception) -> bool:
    """Detecta erros 429 / cota esgotada em qualquer provedor."""
    msg = str(exc).lower()
    return (
        "429" in msg
        or "resource_exhausted" in msg
        or "rate_limit_exceeded" in msg
        or "tokens per minute" in msg
        or "requests per minute" in msg
        or "quota" in msg
    )


def _build_system_prompt(manual: dict) -> str:
    mid = manual["id"]
    lang = manual.get("language") or "pt"
    lang_note = ""
    if lang != "pt":
        lang_names = {"en": "inglês", "de": "alemão", "es": "espanhol", "fr": "francês", "it": "italiano"}
        lang_display = lang_names.get(lang, lang)
        lang_note = (
            f"IMPORTANTE: As paginas do manual estao escritas em {lang_display}. "
            "Leia o conteudo no idioma original, extraia as informacoes tecnicas "
            "(valores numericos, torques, folgas, capacidades, procedimentos) e responda EXCLUSIVAMENTE em portugues do Brasil. "
            f"TRADUZA todos os nomes de pecas e componentes do {lang_display} para o portugues. "
            "Exemplo: 'Zylinderkopfschraube' -> 'parafuso de cabeca do cilindro', 'Oldruckschalter' -> 'sensor de pressao do oleo'. "
            "Nunca deixe termos no idioma original na resposta.\n\n"
        )
    return (
        "Voce e um assistente tecnico especialista para mecanicos de motocicletas. "
        "Responda SEMPRE em portugues do Brasil, usando EXCLUSIVAMENTE as paginas do manual fornecidas.\n\n"
        + lang_note +
        "ESTRUTURA OBRIGATORIA DA RESPOSTA:\n\n"
        "1. RESPOSTA DIRETA (primeira linha, sem titulo)\n"
        "   - Uma unica frase com o valor principal em **negrito**.\n"
        "   - Exemplo: O torque do parafuso de dreno e **4,3 kgf.m (43 Nm)**.\n"
        "   - Sem saudacao, sem introducao, sem 'De acordo com o manual'.\n\n"
        "2. ESPECIFICACOES (somente se houver valores numericos: torques, folgas, capacidades)\n"
        "   - Titulo: ### Especificacoes\n"
        "   - UMA tabela markdown com colunas: Item | Valor | Pagina\n"
        "   - Inclua TODOS os valores relevantes na tabela. Nao repita no texto.\n\n"
        "3. PROCEDIMENTO (somente se a pergunta envolver como fazer algo)\n"
        "   - Titulo: ### Procedimento\n"
        "   - Lista numerada, passos CURTOS e objetivos (max 2 linhas cada).\n"
        "   - Avisos de seguranca: > **Aviso:** texto\n"
        "   - Inclua a citacao de pagina NO FINAL de cada passo.\n\n"
        "4. OBSERVACOES (opcional, somente se houver informacao adicional importante)\n"
        "   - Titulo: ### Observacoes\n"
        "   - Bullets curtos. Sem repeticao do que ja foi dito acima.\n\n"
        "REGRAS DE CITACAO (OBRIGATORIO):\n"
        f"- Use SEMPRE links markdown: [pag. N](/manuals/{mid}/pdf#page=N)\n"
        f"- Exemplo pagina 119: [pag. 119](/manuals/{mid}/pdf#page=119)\n"
        "- Na tabela: coluna Pagina deve conter o link.\n"
        "- No procedimento: link no final da linha do passo, entre parenteses.\n"
        "- NUNCA escreva apenas 'p. N' ou 'pagina X' sem o link.\n"
        "- Se a informacao nao estiver nas paginas, diga: 'Informacao nao encontrada nas paginas consultadas.'\n\n"
        "PROIBICOES:\n"
        "- Nao repita o mesmo valor em secoes diferentes.\n"
        "- Nao use bullet points para especificacoes (use tabela).\n"
        "- Nao cite o mesmo numero de pagina mais de uma vez no procedimento.\n"
        "- Nao explique o que e um parafuso de dreno, torque, etc. O mecanico ja sabe.\n\n"
        "Termine com uma linha: PAGINAS: N, N, N (so os numeros, sera removida antes de exibir)."
    )


def _build_user_message(manual: dict, question: str, context_blocks: list[str]) -> str:
    return (
        f"Moto: {manual['brand']} {manual['model']} {manual['year']}\n"
        f"Pergunta do mecanico: {question}\n\n"
        "Paginas do manual de servico (numero = pagina do PDF):\n"
        + "\n".join(context_blocks)
    )


# --- Expander e tradutor de termos de busca -----------------------------------------

_LANG_NAMES = {
    "pt": "portugues",
    "en": "ingles",
    "de": "alemao",
    "es": "espanhol",
    "fr": "frances",
    "it": "italiano",
}


def _llm_call(prompt: str, max_tokens: int = 256) -> str:
    """Chama o LLM disponivel e retorna o texto da resposta. Falha silenciosamente."""
    try:
        if (LLM_PROVIDER in ("groq", "auto")) and _has_groq():
            client = _groq_client()
            resp = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
            return (resp.choices[0].message.content or "").strip()
        elif _has_gemini():
            client = _gemini_client()
            resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            return (resp.text or "").strip()
    except Exception:
        pass
    return ""


def _expand_terms_with_llm(question: str, language: str | None) -> list[str]:
    """Pede ao LLM termos de busca adicionais. Falha silenciosamente."""
    lang_name = _LANG_NAMES.get(language or "pt", "portugues")
    prompt = (
        "Voce gera termos de busca para localizar paginas em um manual de servico "
        f"de motocicleta escrito em {lang_name}. Pergunta do mecanico: \"{question}\"\n"
        f"Responda SOMENTE com um array JSON de 4 a 10 termos tecnicos curtos em {lang_name} "
        "(pecas, procedimentos, especificacoes). Sem explicacoes."
    )
    try:
        text = _llm_call(prompt, max_tokens=256)
        if not text:
            return []
        start, end = text.index("["), text.rindex("]") + 1
        terms = json.loads(text[start:end])
        return [str(t) for t in terms if isinstance(t, str)]
    except Exception:
        return []


def _translate_terms(terms: list[str], target_language: str) -> list[str]:
    """Traduz termos de busca do portugues para o idioma do manual. Falha silenciosamente."""
    if not terms:
        return []
    lang_name = _LANG_NAMES.get(target_language, target_language)
    terms_str = ", ".join(terms)
    prompt = (
        f"Traduza estes termos tecnicos de motocicleta do portugues para o {lang_name}. "
        f"Termos: [{terms_str}]\n"
        f"Responda SOMENTE com um array JSON de strings em {lang_name}, "
        "mantendo a mesma quantidade de termos. Sem explicacoes."
    )
    try:
        text = _llm_call(prompt, max_tokens=256)
        if not text:
            return []
        start, end = text.index("["), text.rindex("]") + 1
        translated = json.loads(text[start:end])
        return [str(t) for t in translated if isinstance(t, str)]
    except Exception:
        logger.warning("Falha ao traduzir termos para '%s', usando termos originais.", target_language)
        return []


# --- Busca de paginas relevantes -----------------------------------------

def retrieve(con: sqlite3.Connection, manual_id: str, question: str,
             language: str | None, use_llm: bool) -> tuple[list[dict], list[str]]:
    """Busca paginas relevantes. Se o manual nao for em PT, traduz os termos de busca."""
    terms_pt = search.extract_terms(question)

    # Determina os termos de busca no idioma do manual
    manual_lang = language or "pt"
    if manual_lang != "pt" and use_llm:
        # Traduz os termos para o idioma do manual + expande com sinonimos
        terms_translated = _translate_terms(terms_pt, manual_lang)
        expanded = _expand_terms_with_llm(question, manual_lang)
        terms_search = list(dict.fromkeys(terms_translated + expanded))
        logger.info("Termos traduzidos (%s): %s", manual_lang, terms_search)
    elif use_llm:
        terms_search = list(dict.fromkeys(terms_pt + _expand_terms_with_llm(question, manual_lang)))
    else:
        terms_search = terms_pt

    # Busca com termos no idioma do manual
    results = search.search_pages(con, manual_id, search.build_fts_query(terms_search), MAX_CONTEXT_PAGES)

    # Fallback: se nao achou nada e o idioma nao é PT, tenta tambem com termos originais em PT
    if not results and manual_lang != "pt" and terms_pt != terms_search:
        logger.info("Fallback: buscando com termos originais em PT: %s", terms_pt)
        results = search.search_pages(con, manual_id, search.build_fts_query(terms_pt), MAX_CONTEXT_PAGES)
        if results:
            terms_search = terms_pt

    # Retorna termos traduzidos (para highlight) junto com os originais em PT
    all_terms = list(dict.fromkeys(terms_pt + terms_search))
    return results, all_terms


# --- Geracao de resposta com Groq ----------------------------------------

def _answer_groq(manual: dict, question: str, refs: list[dict],
                 terms: list[str], context_blocks: list[str]) -> dict:
    system_prompt = _build_system_prompt(manual)
    user_msg = _build_user_message(manual, question, context_blocks)

    client = _groq_client()
    try:
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_msg},
            ],
            max_tokens=4096,
        )
    except Exception as exc:
        logger.error("Groq error [%s]: %s", type(exc).__name__, exc)
        if _is_quota_error(exc):
            return _quota_response(refs, terms, "Groq")
        raise

    return _finalize(resp.choices[0].message.content or "", refs, terms, provider="groq")


# --- Geracao de resposta com Gemini (com visao) ---------------------------

def _page_image_parts(manual: dict, ref_pages: list[int]):
    """Renderiza paginas como PNG para o Gemini ler tabelas e diagramas."""
    from google.genai import types
    from . import pages as pages_mod

    parts = []
    for p in ref_pages[:MAX_IMAGE_PAGES]:
        try:
            png = pages_mod.render_page_png(manual, p, zoom=IMAGE_ZOOM)
        except Exception:
            continue
        parts.append(f"Imagem da pagina {p}:")
        parts.append(types.Part.from_bytes(data=png, mime_type="image/png"))
    return parts


def _answer_gemini(manual: dict, question: str, refs: list[dict],
                   terms: list[str], context_blocks: list[str]) -> dict:
    from google.genai import types

    system_prompt = _build_system_prompt(manual)
    user_msg = _build_user_message(manual, question, context_blocks)

    contents: list = [user_msg]
    contents += _page_image_parts(manual, [r["page"] for r in refs])

    client = _gemini_client()
    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                max_output_tokens=8192,
                system_instruction=system_prompt,
            ),
            contents=contents,
        )
    except Exception as exc:
        logger.error("Gemini error [%s]: %s", type(exc).__name__, exc)
        if _is_quota_error(exc):
            return _quota_response(refs, terms, "Gemini")
        raise

    return _finalize(resp.text or "", refs, terms, provider="gemini")


# --- Helpers de resultado -------------------------------------------------

def _quota_response(refs: list[dict], terms: list[str], provider: str) -> dict:
    return {
        "mode": "quota",
        "answer": None,
        "message": (
            f"Limite diario da API {provider} atingido. "
            "As paginas mais relevantes do manual estao disponiveis abaixo."
        ),
        "references": refs,
        "terms": terms,
    }


def _finalize(answer_text: str, refs: list[dict], terms: list[str], provider: str) -> dict:
    import re
    cited = _extract_cited_pages(answer_text, [r["page"] for r in refs])
    references = [r | {"cited": r["page"] in cited} for r in refs]

    # Remove linha interna "PAGINAS: ..."
    answer_text = re.sub(
        r"\n*\*{0,2}\s*PAGINAS\s*:[\d,\s.]+\*{0,2}\s*$",
        "",
        answer_text,
        flags=re.IGNORECASE,
    ).rstrip()

    return {
        "mode": f"llm-{provider}",
        "answer": answer_text,
        "message": None,
        "references": references,
        "terms": terms,
    }


def _extract_cited_pages(answer_text: str, candidate_pages: list[int]) -> set[int]:
    import re
    nums = {int(n) for n in re.findall(r"\[p[aá]g\.\s*(\d+)\]", answer_text)}
    m = re.search(r"PAGINAS:\s*([\d,\s]+)", answer_text)
    if m:
        nums |= {int(n) for n in re.findall(r"\d+", m.group(1))}
    return nums & set(candidate_pages)


# --- Ponto de entrada principal -------------------------------------------

def answer(con: sqlite3.Connection, manual: dict, question: str) -> dict:
    use_llm = has_llm()
    refs, terms = retrieve(con, manual["id"], question, manual.get("language"), use_llm)

    if not refs:
        return {
            "mode": "llm" if use_llm else "search",
            "answer": None,
            "message": "Nenhuma pagina relevante encontrada no manual para essa pergunta.",
            "references": [],
            "terms": terms,
        }

    if not use_llm:
        return {
            "mode": "search",
            "answer": None,
            "message": (
                "Modo busca: defina GROQ_API_KEY ou GEMINI_API_KEY para respostas geradas por IA. "
                "Abaixo estao as paginas mais relevantes do manual."
            ),
            "references": refs,
            "terms": terms,
        }

    # context_blocks para Groq (texto menor) e Gemini (texto maior)
    groq_blocks, gemini_blocks = [], []
    for r in refs:
        text = search.get_page_text(con, manual["id"], r["page"]) or ""
        groq_blocks.append(f"<pagina numero=\"{r['page']}\">\n{text[:GROQ_MAX_CHARS_PER_PAGE]}\n</pagina>")
        gemini_blocks.append(f"<pagina numero=\"{r['page']}\">\n{text[:GEMINI_MAX_CHARS_PER_PAGE]}\n</pagina>")

    # --- Selecao de provedor ---
    if LLM_PROVIDER == "groq":
        return _answer_groq(manual, question, refs, terms, groq_blocks)

    if LLM_PROVIDER == "gemini":
        return _answer_gemini(manual, question, refs, terms, gemini_blocks)

    # auto: Groq primeiro, Gemini como fallback
    if _has_groq():
        try:
            return _answer_groq(manual, question, refs, terms, groq_blocks)
        except Exception as exc:
            logger.warning("Groq falhou (%s), tentando Gemini...", exc)

    if _has_gemini():
        return _answer_gemini(manual, question, refs, terms, gemini_blocks)

    # Nenhum provedor disponivel
    return {
        "mode": "error",
        "answer": None,
        "message": "Nenhum provedor de IA configurado (defina GROQ_API_KEY ou GEMINI_API_KEY).",
        "references": refs,
        "terms": terms,
    }
