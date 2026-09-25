"""Padroniza a grafia das marcas na tabela `manuals`.

Os manuais cadastrados pelo painel admin entraram com o texto exatamente como
foi digitado ("kawasaki", "YAMAHA", "Manual"), entao a lista de motos mostrava a
mesma marca em dois ou tres grupos diferentes. Este script coloca todos na
grafia oficial definida em `app.indexer.normalize_brand`.

O id de cada manual NAO muda -- ele e' a referencia do PDF em disco e do plano
de quem assinou o acesso a um modelo so'.

Rodar:
    python scripts/normalize_brands.py --dry-run   # so' mostra o que faria
    python scripts/normalize_brands.py             # aplica
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import db
from app.indexer import normalize_brand

# Correcoes feitas na mao, porque nenhuma regra automatica adivinha que
# "Manual" era uma Suzuki nem que "NINJA_650" e' a Ninja 650. Os nomes sao os
# mesmos que a landing page usa na secao do acervo.
CORRECOES = {
    # marca errada
    "manual-gsx-r1000-2022":   {"brand": "Suzuki", "model": "GSX-R 1000"},

    # modelos digitados em caixa alta, com underline ou sem espaco
    "kawasaki-ninja250-2012":  {"model": "Ninja 250"},
    "kawasaki-ninja300-2013":  {"model": "Ninja 300"},
    "kawasaki-ninja-650-2013": {"model": "Ninja 650"},
    "kawasaki-ninja-h2-2016":  {"model": "Ninja H2"},
    "kawasaki-zx-14-2012":     {"model": "Ninja ZX-14"},
    "kawasaki-zx10r-2009":     {"model": "Ninja ZX-10R"},
    "yamaha-fazer-150-2013":   {"model": "Fazer 150"},
    "yamaha-fazer-250-2011":   {"model": "Fazer 250"},
    "yamaha-fz6n-2009":        {"model": "FZ6-N"},

    # parenteses fora do padrao do resto do acervo
    "yamaha-mt09-2015":        {"model": "MT-09 ABS"},
    "yamaha-r3-2016":          {"model": "YZF-R3 ABS"},
}


def main(dry_run: bool) -> None:
    con = db.get_con()
    linhas = con.execute("SELECT id, brand, model FROM manuals ORDER BY id").fetchall()

    mudancas = []
    for linha in linhas:
        correcao = CORRECOES.get(linha["id"], {})
        marca_nova = normalize_brand(correcao.get("brand", linha["brand"]))
        modelo_novo = correcao.get("model", linha["model"]).strip()
        if marca_nova != linha["brand"] or modelo_novo != linha["model"]:
            mudancas.append((linha["id"], linha["brand"], marca_nova, linha["model"], modelo_novo))

    if not mudancas:
        print("Nada a fazer: todas as marcas ja estao padronizadas.")
        con.close()
        return

    print(f"{len(mudancas)} de {len(linhas)} manuais serao ajustados:\n")
    for manual_id, marca_velha, marca_nova, modelo_velho, modelo_novo in mudancas:
        alvo = f"{marca_velha!r} -> {marca_nova!r}"
        if modelo_velho != modelo_novo:
            alvo += f" | modelo {modelo_velho!r} -> {modelo_novo!r}"
        print(f"  {manual_id:32} {alvo}")

    if dry_run:
        print("\n(dry-run: nada foi gravado)")
        con.close()
        return

    con.executemany(
        "UPDATE manuals SET brand = ?, model = ? WHERE id = ?",
        [(marca, modelo, mid) for mid, _, marca, _, modelo in mudancas],
    )
    con.commit()

    print("\nMarcas depois do ajuste:")
    for r in con.execute("SELECT brand, count(*) n FROM manuals GROUP BY brand ORDER BY brand"):
        print(f"  {r['brand']:14} {r['n']}")
    con.close()


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
