"""Verifica quais PDFs tem camada de texto e quais sao escaneados (imagem)."""
import pathlib
import fitz  # pymupdf

ROOT = pathlib.Path(__file__).resolve().parent.parent / "data" / "manuals"

for pdf in sorted(ROOT.rglob("*.pdf")):
    try:
        doc = fitz.open(pdf)
        n = doc.page_count
        # amostra ate 12 paginas distribuidas pelo documento
        sample = [doc[i] for i in range(0, n, max(1, n // 12))][:12]
        chars = [len(p.get_text("text").strip()) for p in sample]
        with_text = sum(1 for c in chars if c > 100)
        print(f"{pdf.relative_to(ROOT)} | paginas={n} | amostras_com_texto={with_text}/{len(sample)} | media_chars={sum(chars)//len(chars)}")
        doc.close()
    except Exception as e:
        print(f"{pdf.relative_to(ROOT)} | ERRO: {e}")
