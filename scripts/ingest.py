"""Indexa os manuais de servico: extrai o texto de cada pagina e grava no SQLite (FTS5).

Uso: python scripts/ingest.py
Reexecutar e seguro: recria o indice do zero.
"""
import pathlib
import re
import sqlite3
import sys

import fitz  # pymupdf
import ftfy

BASE = pathlib.Path(__file__).resolve().parent.parent
MANUALS_DIR = BASE / "data" / "manuals"
DB_PATH = BASE / "data" / "index.db"

# Catalogo: chave = trecho do nome do arquivo (para tolerar problemas de acentuacao)
CATALOG = [
    ("CB 600F Hornet",   dict(id="honda-cb600f-hornet-2008", brand="Honda",    model="CB 600F Hornet",   year="2008-2010")),
    ("CBR1000 RR.2008",  dict(id="honda-cbr1000rr-2008",     brand="Honda",    model="CBR1000RR",        year="2008")),
    ("NINJA 400",        dict(id="kawasaki-ninja400-2019",   brand="Kawasaki", model="Ninja 400",        year="2019")),
    ("NINJA ZX-6R",      dict(id="kawasaki-zx6r-2020",       brand="Kawasaki", model="Ninja ZX-6R",      year="2020")),
    ("ZX-10R NINJA_2015",dict(id="kawasaki-zx10r-2015",      brand="Kawasaki", model="Ninja ZX-10R",     year="2015")),
    ("ZX10R-2017",       dict(id="kawasaki-zx10r-2017",      brand="Kawasaki", model="Ninja ZX-10R",     year="2017")),
    ("GSX 1300R Hayabusa", dict(id="suzuki-hayabusa-2008",   brand="Suzuki",   model="GSX 1300R Hayabusa", year="2008")),
    ("GSXR 1000 2009",   dict(id="suzuki-gsxr1000-2009",     brand="Suzuki",   model="GSX-R 1000",       year="2009")),
    ("GSXR 750 2007",    dict(id="suzuki-gsxr750-2007",      brand="Suzuki",   model="GSX-R 750",        year="2007")),
    ("MT09",             dict(id="yamaha-mt09-2015",         brand="Yamaha",   model="MT-09 (ABS)",      year="2015")),
    ("MT07",             dict(id="yamaha-mt07-2016",         brand="Yamaha",   model="MT-07",            year="2016")),
    ("YZF-R3",           dict(id="yamaha-r3-2016",           brand="Yamaha",   model="YZF-R3 (ABS)",     year="2016")),
    ("R1 2007",          dict(id="yamaha-r1-2007",           brand="Yamaha",   model="YZF-R1",           year="2007")),
    ("YZF-R6S",          dict(id="yamaha-r6s-2007",          brand="Yamaha",   model="YZF-R6S",          year="2007")),
]


def find_meta(pdf_path: pathlib.Path):
    for key, meta in CATALOG:
        if key.lower() in pdf_path.name.lower():
            return meta
    return None


def detect_language(sample_text: str) -> str:
    pt = len(re.findall(r"\b(de|para|com|nao|não|remova|instale|verifique|aperto)\b", sample_text, re.I))
    en = len(re.findall(r"\b(the|remove|install|check|torque|with|and)\b", sample_text, re.I))
    return "pt" if pt >= en else "en"


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(
        """
        CREATE TABLE manuals (
            id TEXT PRIMARY KEY,
            brand TEXT NOT NULL,
            model TEXT NOT NULL,
            year TEXT NOT NULL,
            file TEXT NOT NULL,
            pages INTEGER NOT NULL,
            indexed INTEGER NOT NULL,
            language TEXT
        );
        CREATE VIRTUAL TABLE pages USING fts5(
            manual_id UNINDEXED,
            page UNINDEXED,
            text,
            tokenize = "unicode61 remove_diacritics 2"
        );
        """
    )

    pdfs = sorted(MANUALS_DIR.rglob("*.pdf"))
    if not pdfs:
        sys.exit(f"Nenhum PDF encontrado em {MANUALS_DIR}")

    for pdf in pdfs:
        meta = find_meta(pdf)
        if not meta:
            print(f"AVISO: sem metadados para {pdf.name}, pulando")
            continue
        doc = fitz.open(pdf)
        rows = []
        for i in range(doc.page_count):
            # ftfy conserta mojibake dos PDFs (ex.: "vÃ¡lvulas" -> "válvulas")
            text = ftfy.fix_text(doc[i].get_text("text")).strip()
            if len(text) > 30:
                rows.append((meta["id"], i + 1, re.sub(r"[ \t]+", " ", text)))
        indexed = len(rows) > doc.page_count * 0.3  # menos de 30% com texto => escaneado
        lang = detect_language(" ".join(r[2][:500] for r in rows[:40])) if indexed else None
        if indexed:
            con.executemany("INSERT INTO pages(manual_id, page, text) VALUES (?,?,?)", rows)
        con.execute(
            "INSERT INTO manuals(id, brand, model, year, file, pages, indexed, language) VALUES (?,?,?,?,?,?,?,?)",
            (meta["id"], meta["brand"], meta["model"], meta["year"],
             str(pdf.relative_to(MANUALS_DIR)), doc.page_count, int(indexed), lang),
        )
        status = f"indexado ({len(rows)} paginas, idioma={lang})" if indexed else "NAO indexado (escaneado, requer OCR)"
        print(f"{meta['id']}: {status}")
        doc.close()

    con.commit()
    con.close()
    print(f"\nIndice gravado em {DB_PATH}")


if __name__ == "__main__":
    main()
