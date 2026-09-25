#!/usr/bin/env bash
# Importa os manuais dos arquivos RAR em manuaisNew/ para o acervo.
#
#   ./scripts/importar_manuais.sh              extrai os RARs e monta o plano
#   ./scripts/importar_manuais.sh --aplicar    importa o que esta' marcado com S
#
# Entre um comando e outro, abra data/incoming/plano.csv, confira marca/modelo/
# ano e marque S ou N na primeira coluna.
#
# Extrair de novo e' barato: arquivos ja' extraidos sao pulados (unar -s), entao
# se um RAR falhar no meio da' para rodar o comando outra vez sem perder nada.
set -uo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOTES="$RAIZ/manuaisNew"
DESTINO="$RAIZ/data/incoming"

rodar_no_container() {
  docker compose -f "$RAIZ/docker-compose.yml" exec -T manuais-api \
    python scripts/import_manuals.py "$@" 2>&1 | grep -v "fitz. API is deprecated"
}

if [[ "${1:-}" == "--aplicar" ]]; then
  echo ">> Importando os manuais marcados no plano (pode demorar bastante)..."
  rodar_no_container --aplicar
  exit 0
fi

# ── 1. extrair os RARs ──────────────────────────────────────────────
if ! command -v unar >/dev/null; then
  echo "Falta o extrator de RAR. Instale com:  apt-get install -y unar" >&2
  exit 1
fi

shopt -s nullglob nocaseglob
ARQUIVOS=("$LOTES"/*.rar)
if [[ ${#ARQUIVOS[@]} -eq 0 ]]; then
  echo "Nenhum .rar em $LOTES" >&2
  exit 1
fi

mkdir -p "$DESTINO"
FALHAS=()
for rar in "${ARQUIVOS[@]}"; do
  nome="$(basename "$rar")"
  echo ">> Extraindo $nome ..."
  # -s pula o que ja' existe, -D nao cria pasta extra, -q sem tagarelice.
  # Um PDF corrompido no meio do RAR nao pode derrubar o lote inteiro.
  if ! unar -q -D -s -o "$DESTINO" "$rar"; then
    FALHAS+=("$nome")
    echo "   !! $nome teve arquivo que nao extraiu por completo"
  fi
done

echo
echo ">> PDFs prontos: $(find "$DESTINO" -iname '*.pdf' | wc -l)"
if [[ ${#FALHAS[@]} -gt 0 ]]; then
  echo ">> RARs com problema (arquivo truncado na origem): ${FALHAS[*]}"
fi
echo ">> Montando o plano de importacao..."
echo
rodar_no_container --plano

echo
echo "Proximo passo: revise $DESTINO/plano.csv e rode:"
echo "   ./scripts/importar_manuais.sh --aplicar"
