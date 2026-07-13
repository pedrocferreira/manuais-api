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
# Quantas paginas tambem sao enviadas como IMAGEM ao Gemini (0 desliga o modo visao).
# Com imagem o modelo le tabelas de torque e diagramas que a extracao de texto embaralha.
MAX_IMAGE_PAGES = int(os.environ.get("RAG_IMAGE_PAGES", "6"))
IMAGE_ZOOM = 1.5


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
             language: str | None, use_llm: bool) -> tuple[list[dict], list[str]]:
    terms = search.extract_terms(question)
    if use_llm:
        terms = list(dict.fromkeys(terms + _expand_terms_with_llm(question, language)))
    results = search.search_pages(con, manual_id, search.build_fts_query(terms), MAX_CONTEXT_PAGES)
    # fallback: tenta termos individualmente mais fortes (AND) se OR trouxe demais? BM25 ja ordena.
    return results, terms


def _page_image_parts(manual: dict, ref_pages: list[int]):
    """Renderiza as primeiras paginas recuperadas como PNG para o Gemini ler
    tabelas e diagramas direto da imagem. Falha de renderizacao nao derruba a resposta."""
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
            "message": ("Modo busca: defina GEMINI_API_KEY para respostas geradas por IA. "
                        "Abaixo estao as paginas mais relevantes do manual."),
            "references": refs,
            "terms": terms,
        }

    context_blocks = []
    for r in refs:
        text = search.get_page_text(con, manual["id"], r["page"]) or ""
        context_blocks.append(f"<pagina numero=\"{r['page']}\">\n{text[:4000]}\n</pagina>")

    from google.genai import types

    contents: list = [
        f"Moto: {manual['brand']} {manual['model']} {manual['year']}\n"
        f"Pergunta do mecanico: {question}\n\n"
        "Paginas do manual de servico (numero = pagina do PDF):\n"
        + "\n".join(context_blocks)
    ]
    contents += _page_image_parts(manual, [r["page"] for r in refs])

    client = _client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        config=types.GenerateContentConfig(
            max_output_tokens=8192,
            system_instruction=(
                "Voce e um assistente tecnico para mecanicos de motocicletas. Responda em portugues, "
                "usando SOMENTE as paginas do manual de servico fornecidas. "
                "Alem do texto extraido, voce recebe IMAGENS de algumas paginas: use-as para ler "
                "tabelas de especificacoes, legendas e diagramas com precisao.\n\n"
                "FORMATO DA RESPOSTA (markdown, sera renderizado na tela do mecanico):\n"
                "- Comece com a resposta direta em 1-2 frases, com o valor principal em negrito. "
                "Nada de saudacao ou introducao.\n"
                "- Depois, se houver mais conteudo util, organize em secoes curtas com titulo '### '.\n"
                "- Especificacoes (torques, folgas, capacidades, tolerancias): SEMPRE em tabela markdown "
                "(colunas como Item | Especificacao | Pagina). Liste TODAS as relacionadas, "
                "nao so o primeiro valor.\n"
                "- Procedimentos: lista numerada, passo a passo, na ordem do manual, incluindo ferramentas "
                "especiais e avisos de seguranca (destaque avisos com '> **Atencao:**').\n"
                "- Cite a pagina no formato [p. N] logo apos cada informacao, UMA vez por item. "
                "As citacoes viram botoes clicaveis que abrem a imagem da pagina - "
                "NUNCA escreva 'veja a imagem da pagina N' nem repita a citacao na mesma frase. "
                "Se um diagrama ou vista explodida ajudar, diga apenas o que ele mostra, ex.: "
                "'o diagrama de sequencia de aperto esta em [p. N]'.\n"
                "- Nao repita a mesma especificacao em varias secoes: consolide na tabela.\n"
                "- Se a informacao nao estiver nas paginas fornecidas, diga isso claramente em vez de inventar.\n"
                "- Termine com uma linha 'PAGINAS: N, N, N' com as paginas realmente usadas "
                "(essa linha e removida antes de exibir)."
            ),
        ),
        contents=contents,
    )
    answer_text = response.text

    # extrai as paginas citadas para o front destacar/abrir o PDF
    cited = _extract_cited_pages(answer_text, [r["page"] for r in refs])
    references = [r | {"cited": r["page"] in cited} for r in refs]

    # a linha 'PAGINAS: ...' e uso interno; nao deve aparecer para o mecanico
    import re
    answer_text = re.sub(r"\n*\**\s*PAGINAS:[\d,\s]+\**\s*$", "", answer_text).rstrip()

    return {"mode": "llm", "answer": answer_text, "message": None,
            "references": references, "terms": terms}


def _extract_cited_pages(answer_text: str, candidate_pages: list[int]) -> set[int]:
    import re
    nums = {int(n) for n in re.findall(r"\[p\.\s*(\d+)\]", answer_text)}
    m = re.search(r"PAGINAS:\s*([\d,\s]+)", answer_text)
    if m:
        nums |= {int(n) for n in re.findall(r"\d+", m.group(1))}
    return nums & set(candidate_pages)
