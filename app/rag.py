"""Responde perguntas do mecanico usando as paginas do manual como contexto.

Se a variavel de ambiente GEMINI_API_KEY estiver definida, a resposta e gerada
pelo Gemini citando as paginas usadas. Sem a chave, a API devolve apenas as
paginas mais relevantes (modo busca).
"""
import json
import os
import sqlite3

from . import search

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_CONTEXT_PAGES = 12


def has_llm() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def _client():
    from google import genai
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _expand_terms_with_llm(question: str, language: str | None) -> list[str]:
    """Pede ao Gemini termos de busca no idioma do manual (manuais podem ser em ingles)."""
    lang_name = "portugues" if language == "pt" else "ingles"
    client = _client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=(
            "Voce gera termos de busca para localizar paginas em um manual de servico "
            f"de motocicleta escrito em {lang_name}. Pergunta do mecanico: \"{question}\"\n"
            f"Responda SOMENTE com um array JSON de 4 a 10 termos tecnicos curtos em {lang_name} "
            "(pecas, procedimentos, especificacoes). Sem explicacoes."
        ),
    )
    text = (response.text or "").strip()
    try:
        start, end = text.index("["), text.rindex("]") + 1
        terms = json.loads(text[start:end])
        return [str(t) for t in terms if isinstance(t, str)]
    except (ValueError, json.JSONDecodeError):
        return []


def retrieve(con: sqlite3.Connection, manual_id: str, question: str,
             language: str | None, use_llm: bool) -> list[dict]:
    terms = search.extract_terms(question)
    if use_llm:
        terms = list(dict.fromkeys(terms + _expand_terms_with_llm(question, language)))
    results = search.search_pages(con, manual_id, search.build_fts_query(terms), MAX_CONTEXT_PAGES)
    # fallback: tenta termos individualmente mais fortes (AND) se OR trouxe demais? BM25 ja ordena.
    return results


def answer(con: sqlite3.Connection, manual: dict, question: str) -> dict:
    use_llm = has_llm()
    refs = retrieve(con, manual["id"], question, manual.get("language"), use_llm)

    if not refs:
        return {
            "mode": "llm" if use_llm else "search",
            "answer": None,
            "message": "Nenhuma pagina relevante encontrada no manual para essa pergunta.",
            "references": [],
        }

    if not use_llm:
        return {
            "mode": "search",
            "answer": None,
            "message": ("Modo busca: defina GEMINI_API_KEY para respostas geradas por IA. "
                        "Abaixo estao as paginas mais relevantes do manual."),
            "references": refs,
        }

    context_blocks = []
    for r in refs:
        text = search.get_page_text(con, manual["id"], r["page"]) or ""
        context_blocks.append(f"<pagina numero=\"{r['page']}\">\n{text[:4000]}\n</pagina>")

    from google.genai import types

    client = _client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        config=types.GenerateContentConfig(
            max_output_tokens=8192,
            system_instruction=(
                "Voce e um assistente tecnico para mecanicos de motocicletas. Responda em portugues, "
                "de forma completa e detalhada, usando SOMENTE as paginas do manual de servico fornecidas. "
                "Nao resuma demais: descreva o procedimento passo a passo quando houver um no manual, "
                "na ordem em que aparece, incluindo ferramentas especiais, ordem de desmontagem/montagem "
                "e avisos de seguranca ou cuidado mencionados. "
                "Liste TODAS as especificacoes relacionadas encontradas nas paginas (torque, folgas, "
                "capacidades, tolerancias, limites de desgaste), nao so o primeiro valor que aparecer. "
                "Sempre cite a pagina de cada informacao no formato [p. N] logo apos ela. "
                "Se a informacao nao estiver nas paginas fornecidas, diga isso claramente em vez de inventar. "
                "Ao final, liste em uma linha 'PAGINAS: N, N, N' com as paginas realmente usadas."
            ),
        ),
        contents=(
            f"Moto: {manual['brand']} {manual['model']} {manual['year']}\n"
            f"Pergunta do mecanico: {question}\n\n"
            "Paginas do manual de servico (numero = pagina do PDF):\n"
            + "\n".join(context_blocks)
        ),
    )
    answer_text = response.text

    # extrai as paginas citadas para o front destacar/abrir o PDF
    cited = _extract_cited_pages(answer_text, [r["page"] for r in refs])
    references = [r | {"cited": r["page"] in cited} for r in refs]

    return {"mode": "llm", "answer": answer_text, "message": None, "references": references}


def _extract_cited_pages(answer_text: str, candidate_pages: list[int]) -> set[int]:
    import re
    nums = {int(n) for n in re.findall(r"\[p\.\s*(\d+)\]", answer_text)}
    m = re.search(r"PAGINAS:\s*([\d,\s]+)", answer_text)
    if m:
        nums |= {int(n) for n in re.findall(r"\d+", m.group(1))}
    return nums & set(candidate_pages)
