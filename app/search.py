"""Busca full-text (FTS5/BM25) nas paginas dos manuais."""
import re
import sqlite3

# Palavras muito comuns que so atrapalham a busca (PT + EN)
STOPWORDS = {
    "a", "o", "e", "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
    "um", "uma", "para", "por", "com", "como", "que", "qual", "quais", "quanto",
    "quanta", "onde", "quando", "ser", "esta", "estao", "sao", "ter", "tem", "meu",
    "minha", "se", "eu", "voce", "ele", "ela", "isso", "esse", "essa", "este",
    "the", "a", "an", "of", "in", "on", "for", "to", "is", "are", "what", "how",
    "which", "where", "when", "do", "does", "my", "it", "this", "that", "and", "or",
    "moto", "manual",
}


def extract_terms(question: str) -> list[str]:
    words = re.findall(r"[\w\-]{2,}", question.lower())
    return [w for w in words if w not in STOPWORDS]


def build_fts_query(terms: list[str], operator: str = "OR") -> str:
    # aspas em cada termo para escapar a sintaxe do FTS5
    safe = [f'"{t}"' for t in terms if t.strip('"')]
    return f" {operator} ".join(safe)


def search_pages(con: sqlite3.Connection, manual_id: str, fts_query: str, limit: int = 10) -> list[dict]:
    if not fts_query:
        return []
    rows = con.execute(
        """
        SELECT page,
               snippet(pages, 2, '[', ']', ' ... ', 24) AS snippet,
               bm25(pages) AS score
        FROM pages
        WHERE pages MATCH ? AND manual_id = ?
        ORDER BY bm25(pages)
        LIMIT ?
        """,
        (fts_query, manual_id, limit),
    ).fetchall()
    return [dict(page=r["page"], snippet=r["snippet"], score=round(r["score"], 2)) for r in rows]


def get_page_text(con: sqlite3.Connection, manual_id: str, page: int) -> str | None:
    row = con.execute(
        "SELECT text FROM pages WHERE manual_id = ? AND page = ?", (manual_id, page)
    ).fetchone()
    return row["text"] if row else None
