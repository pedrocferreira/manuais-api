"""Módulo auxiliar para processamento e indexação de manuais individuais."""
import pathlib
import re
import unicodedata

import fitz  # pymupdf
import ftfy

from . import db

def detect_language(sample_text: str) -> str:
    pt = len(re.findall(r"\b(de|para|com|não|remova|instale|verifique|aperto|parafuso|óleo|motor|freio)\b", sample_text, re.I))
    en = len(re.findall(r"\b(the|remove|install|check|torque|with|and|engine|brake|oil|bolt)\b", sample_text, re.I))
    de = len(re.findall(r"\b(der|die|das|und|ein|eine|des|dem|den|mit|von|für|wird|werden|ist|sind|nach|beim|beim|Schraube|Motor|Öl|Bremse|Anzugsmoment|Ausbau|Einbau|Wartung|Prüfung)\b", sample_text, re.I))
    best = max(pt, en, de)
    if best == 0:
        return "pt"
    if de == best:
        return "de"
    if en == best:
        return "en"
    return "pt"


def generate_manual_id(brand: str, model: str, year: str) -> str:
    # Tira o acento antes de limpar, senao "diagnóstico" vira "diagn-stico"
    # e o id aparece assim na URL do PDF.
    raw = unicodedata.normalize("NFKD", f"{brand}-{model}-{year}".lower())
    raw = raw.encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return cleaned or "manual-custom"


# Grafia oficial de cada fabricante. A chave e' o nome sem acento, em minusculo
# e sem pontuacao -- e' assim que o texto digitado no painel e' comparado.
BRAND_ALIASES = {
    "honda": "Honda",
    "yamaha": "Yamaha",
    "suzuki": "Suzuki",
    "kawasaki": "Kawasaki",
    "bmw": "BMW",
    "ktm": "KTM",
    "ducati": "Ducati",
    "triumph": "Triumph",
    "harleydavidson": "Harley-Davidson",
    "harley": "Harley-Davidson",
    "royalenfield": "Royal Enfield",
    "bajaj": "Bajaj",
    "dafra": "Dafra",
    "shineray": "Shineray",
    "haojue": "Haojue",
    "traxx": "Traxx",
    "voltz": "Voltz",
    "aprilia": "Aprilia",
    "husqvarna": "Husqvarna",
    "mvagusta": "MV Agusta",
    "motoguzzi": "Moto Guzzi",
    "royalstar": "Royal Star",
}


def normalize_brand(brand: str) -> str:
    """Devolve sempre a mesma grafia para a mesma marca.

    Sem isso, "kawasaki", "Kawasaki" e "KAWASAKI" viram tres grupos diferentes
    na lista de motos -- foi o que aconteceu com os manuais cadastrados pelo
    painel admin.
    """
    limpo = " ".join((brand or "").split())
    if not limpo:
        return ""

    chave = re.sub(r"[^a-z0-9]", "", limpo.lower())
    if chave in BRAND_ALIASES:
        return BRAND_ALIASES[chave]

    # Marca desconhecida: Primeira Maiuscula, mas siglas curtas ficam em caixa alta
    def _palavra(p: str) -> str:
        return p.upper() if len(p) <= 3 and p.isalpha() else p.capitalize()

    return " ".join(_palavra(p) for p in limpo.split())


def index_manual_pdf(
    pdf_source_path: pathlib.Path,
    brand: str,
    model: str,
    year: str,
    custom_id: str | None = None,
) -> dict:
    """Extrai texto do PDF e insere/atualiza nas tabelas manuals e pages (FTS5)."""
    brand = normalize_brand(brand)
    manual_id = custom_id or generate_manual_id(brand, model, year)
    dest_filename = f"{manual_id}.pdf"
    dest_path = db.MANUALS_DIR / dest_filename
    
    # Se o arquivo de origem nao estiver no destino final, copia/move
    if pdf_source_path.resolve() != dest_path.resolve():
        dest_path.write_bytes(pdf_source_path.read_bytes())

    doc = fitz.open(dest_path)
    page_count = doc.page_count
    rows = []

    for i in range(page_count):
        text = ftfy.fix_text(doc[i].get_text("text")).strip()
        if len(text) > 30:
            rows.append((manual_id, i + 1, re.sub(r"[ \t]+", " ", text)))

    indexed = len(rows) > page_count * 0.3
    lang = detect_language(" ".join(r[2][:500] for r in rows[:40])) if indexed else None
    doc.close()

    con = db.get_con()
    # Limpa dados antigos caso esteja substituindo/reindexando
    con.execute("DELETE FROM pages WHERE manual_id = ?", (manual_id,))
    con.execute("DELETE FROM manuals WHERE id = ?", (manual_id,))

    if indexed:
        con.executemany("INSERT INTO pages(manual_id, page, text) VALUES (?,?,?)", rows)

    con.execute(
        """
        INSERT INTO manuals(id, brand, model, year, file, pages, indexed, language)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (manual_id, brand, model.strip(), str(year).strip(), dest_filename, page_count, int(indexed), lang),
    )
    con.commit()
    con.close()

    return {
        "id": manual_id,
        "brand": brand,
        "model": model,
        "year": year,
        "file": dest_filename,
        "pages": page_count,
        "indexed": indexed,
        "language": lang,
    }


def remove_manual_from_db(manual_id: str) -> None:
    """Remove manual e suas paginas do banco e exclui o arquivo PDF."""
    con = db.get_con()
    row = con.execute("SELECT file FROM manuals WHERE id = ?", (manual_id,)).fetchone()
    if row:
        pdf_file = db.MANUALS_DIR / row["file"]
        if pdf_file.exists():
            try:
                pdf_file.unlink()
            except OSError:
                pass
        con.execute("DELETE FROM pages WHERE manual_id = ?", (manual_id,))
        con.execute("DELETE FROM manuals WHERE id = ?", (manual_id,))
        con.commit()
    con.close()
