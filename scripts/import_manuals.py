"""Importa para o acervo os PDFs extraidos dos lotes em data/incoming/.

Funciona em dois tempos, porque nome de arquivo de manual e' bagunçado demais
para confiar cegamente no que o computador adivinhou:

    1) --plano   le os PDFs, adivinha marca/modelo/ano, classifica cada um e
                 grava data/incoming/plano.csv para voce conferir e corrigir
    2) --aplicar le o plano.csv e indexa de verdade o que estiver marcado

O plano.csv abre no Excel/LibreOffice. Corrija o que estiver errado, mude a
coluna "importar" para S ou N, salve e rode o --aplicar.

Uso (dentro do container, via scripts/importar_manuais.sh):
    python scripts/import_manuals.py --plano
    python scripts/import_manuals.py --aplicar
"""
import csv
import hashlib
import pathlib
import re
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import db, indexer

ENTRADA = db.BASE / "data" / "incoming"
PLANO = ENTRADA / "plano.csv"

# Nome da pasta dentro do RAR -> marca. As pastas vem com erro de digitacao
# ("TRIUNPH", "harley davison"), entao nao da' para confiar no automatico.
MARCA_POR_PASTA = {
    "yamaha": "Yamaha",
    "manual servico bmw": "BMW",
    "manual servico triunph": "Triumph",
    "manual servico triumph": "Triumph",
    "harley davison": "Harley-Davidson",
    "harley davidson": "Harley-Davidson",
}

# Pedacos que aparecem no nome e nao fazem parte do modelo
RUIDO = [
    r"\bMANUAL DE SERVI[CÇ]O\b", r"\bMANUAL SERVI[CÇ]O\b", r"\bSERVICE ?MANUAL\b",
    r"\bMANUAL\b", r"\bSUPLEMENTAR(IO)?\b", r"\bSUPLEMENTO\b", r"\bSUPL\.?\b",
    r"\bIMPORTADA\b", r"\bNACIONAL\b", r"\bANO\b", r"\bNOVA GERACAO\b",
    r"\bBLUE FLEX\b", r"\bGUIA DE SERVI[CÇ]O\b", r"\bMS\b",
]

# palavra-chave no nome -> tipo do documento. A ordem importa: o primeiro que
# casar e' o que vale.
TIPOS = [
    ("outro",        [r"shipment", r"^\W*\d+\W*$"]),
    ("ferramenta",   [r"ferramenta de diagn"]),
    ("esquema",      [r"esquema ?el[eé]tric", r"electrical diagnostic", r"wiring"]),
    ("proprietario", [r"manual proprietario", r"manual do propriet"]),
    ("quadriciclo",  [r"quadriciclo", r"\bYFM\d"]),
    ("suplemento",   [r"\(supl", r"\bsupl\b", r"\bsupl\.", r"suplement"]),
]


# Nome final de cada manual, conferido a mao. O automatico acerta a maior parte,
# mas quem le' a lista no app e' mecanico: "YZF-R1 2000" comunica, "R1 2000" e'
# ambiguo e "675 Triumph 2013" nao diz que e' uma Daytona.
# Formato: arquivo -> (modelo, ano[, "S" para entrar mesmo nao sendo manual completo])
NOMES = {
    # ── BMW (sem ano no documento; nem invento nem chuto) ────────────
    "C1-200.pdf":                                      ("C1 200", ""),
    "F 650 GS.pdf":                                    ("F 650 GS", ""),
    "K1100LTrepeng.pdf":                               ("K 1100 LT/RS", ""),

    # ── Triumph ──────────────────────────────────────────────────────
    "675 2013 TRIUMPH-ServiceManual-T3856909.pdf":     ("Daytona 675", "2013"),
    "Daytona 955  Speed Triple 955cc_2002.pdf":        ("Daytona 955i e Speed Triple", "2002"),
    "Daytona675.2006-07.pdf":                          ("Daytona 675", "2006-2007"),
    "Rocket III.2005.pdf":                             ("Rocket III", "2005"),
    "Tiger_955i.pdf":                                  ("Tiger 955i", ""),

    # ── Harley-Davidson ──────────────────────────────────────────────
    "DYNA 2008.pdf":                                   ("Dyna", "2008"),
    "DYNA 2008 Electrical Diagnostics.pdf":            ("Dyna (diagnóstico elétrico)", "2008", "S"),
    "FLHRC 2006.pdf":                                  ("FLHRC Road King Classic", "2006"),
    "SOFTAIL 00-05.pdf":                               ("Softail", "2000-2005"),
    "SOFTAIL 2007.pdf":                                ("Softail", "2007"),
    "SPORTSTER  2006.pdf":                             ("Sportster", "2006"),
    "SPORTSTER 883 e 1200.pdf":                        ("Sportster 883 e 1200", ""),
    "TOURING MODELS 2006.pdf":                         ("Touring", "2006"),
    "TOURING MODELS 2009.pdf":                         ("Touring", "2009"),
    "V-ROD 2003.pdf":                                  ("V-Rod", "2003"),
    "V-ROD 2008.pdf":                                  ("V-Rod", "2008"),

    # ── Yamaha: esportivas ───────────────────────────────────────────
    "R1 2000.pdf":                                     ("YZF-R1", "2000"),
    "R1 2002.pdf":                                     ("YZF-R1", "2002"),
    "R1 ANO 2006.pdf":                                 ("YZF-R1", "2006"),
    "R1 (SUPL.)ANO 2006.pdf":                          ("YZF-R1 (suplemento)", "2006", "S"),
    "R1 ANO 2010.pdf":                                 ("YZF-R1", "2010"),
    "R6 1999.pdf":                                     ("YZF-R6", "1999"),
    "R6 2000.pdf":                                     ("YZF-R6", "2000"),
    "R6 2003.pdf":                                     ("YZF-R6", "2003"),
    "R6 ANO 2008.pdf":                                 ("YZF-R6", "2008"),
    "R6(S)ANO 2004.pdf":                               ("YZF-R6S", "2004"),
    "R6(V) ANO 2006.pdf":                              ("YZF-R6", "2006"),

    # ── Yamaha: naked e estradeiras ──────────────────────────────────
    "MS.2016.MT07 (ABS).2SN.1ED.W0.pdf":               ("MT-07 ABS", "2016"),
    "MT01 2006.pdf":                                   ("MT-01", "2006"),
    "MT01 2007 NACIONAL.pdf":                          ("MT-01", "2007"),
    "MT03 2008.pdf":                                   ("MT-03", "2008"),
    "MS.2009.XJ6N.1BW.W0.pdf":                         ("XJ6-N", "2009"),
    "XJ6F 2010.pdf":                                   ("XJ6-F", "2010"),
    "MS.2014.XJ6F_XJ6F(ABS).2SK.1ED.W0(SUPL).pdf":     ("XJ6-F ABS (suplemento)", "2014", "S"),
    "FZ6N 2004 IMPORTADA.pdf":                         ("FZ6-N", "2004"),
    "FZ6N 2007 IMPORTADA.pdf":                         ("FZ6-N", "2007"),
    "TDM850 ANO 1996.pdf":                             ("TDM 850", "1996"),
    "TDM850 ANO 1997.pdf":                             ("TDM 850", "1997"),
    "TDM850 ANO 1999.pdf":                             ("TDM 850", "1999"),
    "TDM900 2007.pdf":                                 ("TDM 900", "2007"),
    "TDM900(S) ANO 2004.pdf":                          ("TDM 900", "2004"),
    "TDM900A(T)ANO 2005.pdf":                          ("TDM 900", "2005"),

    # ── Yamaha: custom ───────────────────────────────────────────────
    "VMAX 1700.pdf":                                   ("V-Max 1700", "2009"),
    "VMAX1200 ANO 1986.pdf":                           ("V-Max 1200", "1986"),
    "VMAX1200 ANO 1991.pdf":                           ("V-Max 1200", "1991"),
    "VMAX1200 ANO 1993.pdf":                           ("V-Max 1200", "1993"),
    "VMAX1200 ANO 1996.pdf":                           ("V-Max 1200", "1996"),
    "XV250 1997.pdf":                                  ("XV250 Virago", "1997"),
    "XV535 1999.pdf":                                  ("XV535 Virago", "1999"),
    "XV535 1999 2.pdf":                                ("XV535 Virago", "1999"),
    "XV535 2001.pdf":                                  ("XV535 Virago", "2001"),
    "XVS650 ANO 2002.pdf":                             ("XVS650 Drag Star", "2002"),
    "XVS650.pdf":                                      ("XVS650 Drag Star", "2002"),
    "XVS1100 1999.pdf":                                ("XVS1100 Drag Star", "1999"),
    "XVS950 2009.pdf":                                 ("XVS950 Midnight Star", "2009"),

    # ── Yamaha: trail e off-road ─────────────────────────────────────
    "TENERE .XT660Z 2012.pdf":                         ("Tenere XT660Z", "2012"),
    "TENERE 250 ANO 2011.pdf":                         ("Tenere 250", "2011"),
    "TENERE XT1200Z 2012.pdf":                         ("Super Tenere XT1200Z", "2012"),
    "TENERE XT600Z 1988.pdf":                          ("Tenere XT600Z", "1988"),
    "XT660R 2005.pdf":                                 ("XT660R", "2005"),
    "LANDER250 ANO 2006.pdf":                          ("Lander 250", "2006"),
    "LANDER250(SUPL) ANO 2009.pdf":                    ("Lander 250 (suplemento)", "2009", "S"),
    "MS.2006.WR450F(V).5TJ(43).E0_F0_G0_S0   IMPORTADA.pdf": ("WR450F", "2006"),
    "MS.2007.TT-R230.30S.W0.pdf":                      ("TT-R230", "2007"),
    "YZ426 ANO 2000.pdf":                              ("YZ426F", "2000"),

    # ── Yamaha: pequenas e urbanas ───────────────────────────────────
    "FACTOR 2013 nova geracao.pdf":                    ("YBR125 Factor", "2013"),
    "YBR FACTOR ANO 2009.pdf":                         ("YBR125 Factor", "2009"),
    "YBR125 ANO 2000.pdf":                             ("YBR125", "2000"),
    "YBR125 2006 SUPL.pdf":                            ("YBR125 (suplemento)", "2006", "S"),
    "YBR GUIA DE SERVIÇO.pdf":                         ("YBR125 (guia de serviço)", ""),
    "NEO 2005.pdf":                                    ("Neo AT115", "2005"),
    "XTZ125 2002.pdf":                                 ("XTZ 125", "2002"),
    "XTZ125 2009.pdf":                                 ("XTZ 125", "2009"),
}


def sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def impressao_digital(caminho: pathlib.Path) -> str:
    """Identidade do arquivo: tamanho + hash do inicio.

    Ler 8 MB de cada PDF ja' distingue um manual de outro com folga, e evita
    passar horas lendo os 8 GB do lote inteiro so' para achar repetido.
    """
    try:
        with caminho.open("rb") as fh:
            miolo = hashlib.sha1(fh.read(8 * 1024 * 1024)).hexdigest()
        return f"{caminho.stat().st_size}:{miolo}"
    except OSError:
        return ""


def chave_modelo(marca: str, modelo: str, ano: str) -> str:
    """Chave folgada para achar o mesmo manual escrito de outro jeito.

    "MT-09 ABS" e "MT09 (ABS)" do mesmo ano tem que bater, senao a moto entra
    duas vezes no acervo com nome levemente diferente.
    """
    texto = sem_acento(f"{marca}{modelo}").lower()
    return re.sub(r"[^a-z0-9]", "", texto) + "|" + ano.strip()


def conferir_arquivo(caminho: pathlib.Path) -> str:
    """Diz se o PDF esta' inteiro. Devolve "" quando esta' ok.

    A conferencia e' so' na estrutura (assinatura no comeco, marca de fim no
    final) de proposito: um PDF cortado pela metade faz o PyMuPDF travar
    tentando remontar o indice, e isso pendura a importacao inteira. Foi o que
    aconteceu com o R1200C do RAR da BMW.
    """
    try:
        tamanho = caminho.stat().st_size
        if tamanho < 4096:
            return "arquivo vazio ou truncado"
        with caminho.open("rb") as fh:
            if b"%PDF" not in fh.read(1024):
                return "nao e' um PDF"
            fh.seek(-4096, 2)
            if b"%%EOF" not in fh.read():
                return "PDF incompleto (faltou o fim do arquivo)"
    except OSError as e:
        return f"nao deu para ler: {e}"
    return ""


def normalizar_nome(nome: str) -> str:
    """Underline e ponto viram espaco antes de qualquer analise.

    Sem isso "955cc_2002" esconde o ano (o _ conta como letra para o regex) e
    "Manual_Ferramenta_de_Diagnostico" nao e' reconhecido como manual de
    ferramenta.
    """
    return re.sub(r"\s+", " ", nome.replace("_", " ")).strip()


def classificar(nome: str) -> str:
    alvo = sem_acento(normalizar_nome(nome)).lower()
    for tipo, padroes in TIPOS:
        if any(re.search(p, alvo, re.I) for p in padroes):
            return tipo
    return "manual"


def extrair_ano(nome: str) -> tuple[str, str]:
    """Devolve (ano, nome sem o ano). Entende 2016, 2006-07 e 00-05."""
    m = re.search(r"\b(19[7-9]\d|20[0-3]\d)\s*[-/]\s*(\d{2}|\d{4})\b", nome)
    if m:
        fim = m.group(2)
        fim = fim if len(fim) == 4 else m.group(1)[:2] + fim
        return f"{m.group(1)}-{fim}", nome.replace(m.group(0), " ")

    m = re.search(r"\b(19[7-9]\d|20[0-3]\d)\b", nome)
    if m:
        return m.group(1), nome.replace(m.group(0), " ")

    m = re.search(r"\b(\d{2})\s*-\s*(\d{2})\b", nome)      # Harley: "00-05"
    if m:
        def completa(dd: str) -> str:
            return ("20" if int(dd) <= 30 else "19") + dd
        return f"{completa(m.group(1))}-{completa(m.group(2))}", nome.replace(m.group(0), " ")

    return "", nome


def arrumar_modelo(bruto: str) -> str:
    texto = normalizar_nome(bruto)
    for padrao in RUIDO:
        texto = re.sub(padrao, " ", texto, flags=re.I)

    # Numero de peca no fim do nome da Triumph (T3856909). NAO existe regra
    # geral para codigo de peca aqui: qualquer regex do tipo "letra + digito"
    # engole R1, R6, R3 e C1, que sao nomes de moto.
    texto = re.sub(r"\b[A-Z]\d{6,}\b", " ", texto)

    texto = re.sub(r"\([^)]*\)", lambda m: " " + m.group(0) + " ", texto)   # solta os (ABS)
    texto = re.sub(r"\(\s*[.\s]*\)", " ", texto)      # parenteses que sobrou vazio
    texto = re.sub(r"[-–]\s*[-–]", " ", texto)        # traco orfao de pedaco removido
    texto = re.sub(r"(?<=\s)\.|\.(?=\s)", " ", texto)  # ponto solto entre palavras
    texto = re.sub(r"\s+", " ", texto).strip(" .-")
    texto = re.sub(r"\s+\d{1,2}$", "", texto)         # "XV535 2" = segunda copia

    def palavra(p: str) -> str:
        if re.fullmatch(r"[A-Za-zÀ-ÿ]{5,}", p):     # FAZER, SOFTAIL, TOURING
            return p.capitalize()
        return p

    # "FAZER250" -> "Fazer 250", mas preserva XV535, TDM900, XT660R
    texto = re.sub(r"^([A-Za-z]{5,})(\d)", r"\1 \2", texto)
    return " ".join(palavra(p) for p in texto.split()).strip(" .-")


def ler_pdf(caminho: pathlib.Path) -> dict:
    marca_bruta = caminho.parent.name
    marca = MARCA_POR_PASTA.get(sem_acento(marca_bruta).lower().strip(),
                                indexer.normalize_brand(marca_bruta))

    nome = normalizar_nome(caminho.stem)
    tipo = classificar(nome)

    # Padrao interno da Yamaha: MS.<ano>.<modelo>.<codigos>. Aqui o modelo e'
    # o primeiro campo depois do ano, entao os codigos ficam de fora sozinhos.
    m = re.match(r"^MS\.(\d{4})\.([^.]+)", caminho.stem, re.I)
    if m:
        ano, modelo_bruto = m.group(1), m.group(2)
    else:
        ano, resto = extrair_ano(nome)
        modelo_bruto = resto

    modelo = arrumar_modelo(modelo_bruto)

    # "675 Triumph" -> "675": a marca ja' esta' na coluna do lado
    modelo = re.sub(rf"\b{re.escape(marca.split('-')[0])}\b", " ", modelo, flags=re.I)
    modelo = re.sub(r"\s+", " ", modelo).strip(" .-")

    return {"marca": marca, "modelo": modelo, "ano": ano, "tipo": tipo, "arquivo": caminho}


def gerar_plano() -> None:
    pdfs = sorted(p for p in ENTRADA.rglob("*.pdf") if p.is_file())
    if not pdfs:
        print(f"Nenhum PDF em {ENTRADA}. Extraia os RARs antes "
              f"(scripts/importar_manuais.sh faz isso).")
        return

    con = db.get_con()
    acervo = [dict(r) for r in con.execute("SELECT id, brand, model, year, file FROM manuals")]
    con.close()
    ja_no_acervo = {m["id"] for m in acervo}

    print(f"Comparando com os {len(acervo)} manuais que ja' estao no acervo...")
    digitais_acervo, chaves_acervo = {}, {}
    for m in acervo:
        caminho = db.MANUALS_DIR / m["file"]
        etiqueta = f"{m['brand']} {m['model']} {m['year']}".strip()
        if caminho.exists():
            digitais_acervo[impressao_digital(caminho)] = etiqueta
        chaves_acervo[chave_modelo(m["brand"], m["model"], m["year"])] = etiqueta

    linhas, vistos, digitais_lote = [], set(), {}
    for pdf in pdfs:
        item = ler_pdf(pdf)
        if not item["modelo"]:
            item["tipo"] = "outro"

        # Nome conferido a mao ganha do palpite automatico
        ajuste = NOMES.get(pdf.name)
        forcado = False
        if ajuste:
            item["modelo"], item["ano"] = ajuste[0], ajuste[1]
            forcado = len(ajuste) > 2 and ajuste[2] == "S"

        manual_id = indexer.generate_manual_id(item["marca"], item["modelo"], item["ano"])
        problema = conferir_arquivo(pdf)
        digital = impressao_digital(pdf) if not problema else ""
        chave = chave_modelo(item["marca"], item["modelo"], item["ano"])

        if problema:
            situacao = problema
            item["tipo"] = "danificado"
        elif digital and digital in digitais_acervo:
            situacao = f"ja no acervo como: {digitais_acervo[digital]}"
        elif digital and digital in digitais_lote:
            situacao = f"copia, no lote, de: {digitais_lote[digital]}"
        elif manual_id in ja_no_acervo:
            situacao = "ja no acervo"
        elif chave in chaves_acervo:
            situacao = f"parece ser: {chaves_acervo[chave]}"
        elif manual_id in vistos:
            situacao = "repetido no lote"
        else:
            situacao = "novo"

        vistos.add(manual_id)
        if digital:
            digitais_lote.setdefault(digital, f"{item['marca']} {item['modelo']} {item['ano']}".strip())

        ehmanual = item["tipo"] == "manual" or forcado
        importar = "S" if (situacao == "novo" and ehmanual) else "N"
        linhas.append({
            "importar": importar,
            "marca": item["marca"],
            "modelo": item["modelo"],
            "ano": item["ano"],
            "tipo": item["tipo"],
            "situacao": situacao,
            "tamanho_mb": f"{pdf.stat().st_size / 1_000_000:.1f}",
            "id_gerado": manual_id,
            "arquivo": str(item["arquivo"].relative_to(ENTRADA)),
        })

    ENTRADA.mkdir(parents=True, exist_ok=True)
    with PLANO.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(linhas[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(linhas)

    marcados = sum(1 for l in linhas if l["importar"] == "S")
    print(f"{len(linhas)} PDFs analisados -> {PLANO}\n")
    print(f"  marcados para importar : {marcados}")
    for rotulo, teste in [
        ("ja no acervo",      lambda l: l["situacao"].startswith(("ja no acervo", "parece ser"))),
        ("repetido no lote",  lambda l: l["situacao"].startswith(("copia, no lote", "repetido no lote"))),
        ("suplemento",        lambda l: l["tipo"] == "suplemento"),
        ("esquema eletrico",  lambda l: l["tipo"] == "esquema"),
        ("manual do dono",    lambda l: l["tipo"] == "proprietario"),
        ("nao e' moto",       lambda l: l["tipo"] in ("quadriciclo", "ferramenta", "outro")),
        ("arquivo danificado", lambda l: l["tipo"] == "danificado"),
    ]:
        n = sum(1 for l in linhas if teste(l))
        if n:
            print(f"  {rotulo:22} : {n}  (marcados com N)")
    print(f"\nConfira o arquivo, ajuste o que precisar e rode com --aplicar.")


def aplicar() -> None:
    if not PLANO.exists():
        print(f"Plano nao encontrado: {PLANO}. Rode com --plano primeiro.")
        return

    with PLANO.open(encoding="utf-8-sig", newline="") as fh:
        linhas = list(csv.DictReader(fh, delimiter=";"))

    escolhidos = [l for l in linhas if l["importar"].strip().upper() in ("S", "SIM")]
    if not escolhidos:
        print("Nenhuma linha marcada com S no plano.")
        return

    con = db.get_con()
    ja_no_acervo = {r["id"] for r in con.execute("SELECT id FROM manuals")}
    con.close()

    print(f"{len(escolhidos)} manuais marcados para importar.\n")
    importados, pulados, sem_texto, erros = 0, 0, [], []

    for i, linha in enumerate(escolhidos, 1):
        marca, modelo, ano = linha["marca"].strip(), linha["modelo"].strip(), linha["ano"].strip()
        caminho = ENTRADA / linha["arquivo"]
        etiqueta = f"{marca} {modelo} {ano}".strip()

        if not caminho.exists():
            erros.append((etiqueta, "arquivo nao encontrado"))
            print(f"[{i}/{len(escolhidos)}] {etiqueta} -- arquivo sumiu, pulando")
            continue

        # Vale conferir de novo mesmo quem marcou S na mao: PDF quebrado
        # trava o PyMuPDF e pendura a importacao toda.
        problema = conferir_arquivo(caminho)
        if problema:
            erros.append((etiqueta, problema))
            print(f"[{i}/{len(escolhidos)}] {etiqueta} -- {problema}, pulando")
            continue

        manual_id = indexer.generate_manual_id(marca, modelo, ano)
        if manual_id in ja_no_acervo:
            pulados += 1
            print(f"[{i}/{len(escolhidos)}] {etiqueta} -- ja esta no acervo, pulando")
            continue

        print(f"[{i}/{len(escolhidos)}] {etiqueta} ...", flush=True)
        try:
            meta = indexer.index_manual_pdf(caminho, marca, modelo, ano)
        except Exception as e:                       # PDF corrompido, protegido, etc
            erros.append((etiqueta, str(e)[:120]))
            print(f"          ERRO: {e}")
            continue

        ja_no_acervo.add(meta["id"])
        importados += 1
        if meta["indexed"]:
            print(f"          ok: {meta['pages']} paginas, idioma {meta['language']}")
        else:
            sem_texto.append(etiqueta)
            print(f"          ATENCAO: {meta['pages']} paginas sem camada de texto (precisa de OCR)")

    print("\n" + "=" * 60)
    print(f"importados        : {importados}")
    print(f"pulados           : {pulados}")
    if sem_texto:
        print(f"sem texto (OCR)   : {len(sem_texto)}")
        for t in sem_texto:
            print(f"   - {t}")
    if erros:
        print(f"com erro          : {len(erros)}")
        for t, e in erros:
            print(f"   - {t}: {e}")


if __name__ == "__main__":
    if "--aplicar" in sys.argv:
        aplicar()
    else:
        gerar_plano()
