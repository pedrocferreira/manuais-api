"""Sincroniza os numeros e o acervo da landing page com o banco.

A LP anuncia quantos manuais e quantas paginas o sistema tem, e lista as motos
uma a uma. Cada importacao deixava isso desatualizado -- ou seja, a pagina de
venda passava a mentir sobre o produto. Rodar este script depois de mexer no
acervo resolve:

    python scripts/atualizar_lp.py

Ele so' mexe entre as marcas <!-- ACERVO:INICIO --> e <!-- ACERVO:FIM --> e nos
numeros do topo. O resto do arquivo fica intacto.
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import db

LP = db.BASE / "app" / "static" / "lp.html"

# Quantas motos de CADA marca aparecem antes do botao "ver todos".
# Por marca, e nao um corte geral: cortando os primeiros N da lista inteira,
# a vitrine mostrava so' Yamaha (que tem 61) e parecia que as outras marcas
# tinham sumido do acervo.
POR_MARCA = 4


def escapar(texto: str) -> str:
    return (texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def main() -> None:
    con = db.get_con()
    motos = [dict(r) for r in con.execute(
        "SELECT brand, model, year, indexed FROM manuals ORDER BY brand, model, year"
    )]
    total_paginas = con.execute("SELECT sum(pages) FROM manuals").fetchone()[0] or 0
    con.close()

    if not motos:
        print("Banco sem manuais; nada a fazer.")
        return

    marcas: dict[str, list[dict]] = {}
    for m in motos:
        marcas.setdefault(m["brand"], []).append(m)

    # marca com mais manuais primeiro, que e' como a vitrine fica melhor
    ordem = sorted(marcas, key=lambda b: (-len(marcas[b]), b))
    total = len(motos)
    liberados = sum(1 for m in motos if m["indexed"])
    sem_ocr = total - liberados

    html = LP.read_text(encoding="utf-8")

    # ── numeros do topo ──────────────────────────────────────────────
    html = re.sub(r'(<b data-count=")\d+(">0</b><span>Manuais no acervo)',
                  rf"\g<1>{total}\g<2>", html)
    html = re.sub(r'(<b data-count=")\d+(">0</b><span>Páginas indexadas)',
                  rf"\g<1>{total_paginas}\g<2>", html)
    html = re.sub(r'(<div class="stat"><b>)\d+(</b><span>Marcas atendidas)',
                  rf"\g<1>{len(ordem)}\g<2>", html)
    html = re.sub(r'<h2 class="rv" data-d="1">[^<]*manuais de serviço[^<]*</h2>',
                  f'<h2 class="rv" data-d="1">{total} manuais de serviço, '
                  f'crescendo toda semana</h2>', html)
    html = re.sub(r"Já são [\d\.]+ páginas no índice",
                  f"Já são {total_paginas:,}".replace(",", ".") + " páginas no índice", html)
    html = re.sub(r"Hoje são [\d\.]+ páginas no acervo",
                  f"Hoje são {total_paginas:,}".replace(",", ".") + " páginas no acervo", html)
    html = re.sub(r"Todos os \d+ manuais", f"Todos os {total} manuais", html)

    # ── filtros e grade de motos ─────────────────────────────────────
    filtros = [f'<button class="filt on" data-mk="all">Todas <b>{total}</b></button>']
    cartoes = []
    for marca in ordem:
        slug = re.sub(r"[^a-z0-9]+", "-", marca.lower()).strip("-")
        filtros.append(f'<button class="filt" data-mk="{slug}">'
                       f'{escapar(marca)} <b>{len(marcas[marca])}</b></button>')
        for posicao, m in enumerate(marcas[marca]):
            classe = "bike" if m["indexed"] else "bike soon"
            # Acervo grande vira rolagem infinita no celular: o que passa das
            # primeiras de cada marca so' aparece no "ver todos" ou ao filtrar.
            if posicao >= POR_MARCA:
                classe += " extra"
            rotulo = escapar(marca) + ("" if m["indexed"] else " · em processamento")
            ano = escapar(m["year"] or "—")
            cartoes.append(
                f'      <div class="{classe}" data-mk="{slug}">'
                f'<div><p class="bike-mk">{rotulo}</p>'
                f'<p class="bike-md">{escapar(m["model"])}</p></div>'
                f'<span class="bike-yr">{ano}</span></div>'
            )

    escondidas = sum(max(0, len(v) - POR_MARCA) for v in marcas.values())
    botao = ""
    if escondidas:
        botao = (f'\n    <button class="ver-todas" id="ver-todas">'
                 f'Ver as {total} motos do acervo</button>')

    bloco = ('<!-- ACERVO:INICIO -->\n'
             '    <div class="filters rv" data-d="2" id="filters">\n      '
             + "\n      ".join(filtros)
             + '\n    </div>\n\n    <div class="garage rv compacto" data-d="3" id="garage">\n'
             + "\n".join(cartoes)
             + '\n    </div>' + botao + '\n    <!-- ACERVO:FIM -->')

    if "<!-- ACERVO:INICIO -->" in html:
        html = re.sub(r"<!-- ACERVO:INICIO -->.*?<!-- ACERVO:FIM -->", lambda _: bloco,
                      html, flags=re.S)
    else:  # primeira vez: troca o bloco escrito na mao pelas marcas
        alvo = re.search(r'<div class="filters rv".*?<div class="garage rv".*?\n    </div>\n',
                         html, re.S)
        if not alvo:
            print("Nao achei o bloco do acervo na LP. Nada foi alterado.")
            return
        html = html[:alvo.start()] + bloco + html[alvo.end():]

    # ── recado embaixo da grade ──────────────────────────────────────
    html = re.sub(r"\d+ manuais já estão liberados para pergunta e busca\.\s*"
                  r"\n?\s*Os \d+ marcados como “em processamento”\s*\n?\s*são",
                  f"{liberados} manuais já estão liberados para pergunta e busca.\n      "
                  f"Os {sem_ocr} marcados como “em processamento” são", html)

    LP.write_text(html, encoding="utf-8")
    paginas_fmt = f"{total_paginas:,}".replace(",", ".")
    print(f"LP atualizada: {total} manuais, {paginas_fmt} páginas, {len(ordem)} marcas")
    print(f"  liberados: {liberados} | em processamento (OCR): {sem_ocr}")
    for marca in ordem:
        print(f"    {marca:16} {len(marcas[marca]):3}")


if __name__ == "__main__":
    main()
