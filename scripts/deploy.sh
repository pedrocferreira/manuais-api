#!/usr/bin/env bash
#
# Deploy do Manuais AI com rede de segurança.
#
#   ./scripts/deploy.sh                      deploy completo
#   ./scripts/deploy.sh -m "o que mudou"     idem, com mensagem de commit
#   ./scripts/deploy.sh --sem-commit         sobe sem commitar (teste rapido)
#   ./scripts/deploy.sh --status             o que esta no ar e quais backups existem
#   ./scripts/deploy.sh --rollback           volta para a versao anterior
#   ./scripts/deploy.sh --restaurar-banco <carimbo>   devolve o banco de um backup
#
# O que ele garante, em ordem:
#   1. backup do banco e do .env ANTES de qualquer coisa
#   2. commit do codigo, para a versao no ar ter um ponto no historico
#   3. a imagem que esta' rodando e' guardada como "anterior"
#   4. sobe a nova e confere se responde de verdade (app + banco)
#   5. se nao responder, volta sozinho para a imagem anterior
#
# O banco NAO volta sozinho no rollback, e isso e' de proposito: entre o deploy
# e a falha pode ter entrado pergunta, usuario ou compra. Derrubar o codigo e'
# reversivel, apagar dado do cliente nao e'. Para voltar o banco, o comando e'
# separado e explicito.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

SERVICO="manuais-api"
CONTAINER="manuais-api"
IMAGEM="manuais-api-manuais-api:latest"
IMAGEM_ANTERIOR="manuais-api:anterior"
SAUDE_URL="http://127.0.0.1:8000"
BACKUPS="$RAIZ/backups"
HISTORICO="$BACKUPS/releases.log"
MANTER=10                      # quantos backups guardar
ESPACO_MINIMO_MB=3000

vermelho() { printf '\033[31m%s\033[0m\n' "$*"; }
verde()    { printf '\033[32m%s\033[0m\n' "$*"; }
amarelo()  { printf '\033[33m%s\033[0m\n' "$*"; }
passo()    { printf '\n\033[1m>> %s\033[0m\n' "$*"; }

# ─────────────────────────────────────────────────────────────────
# Conferencias antes de mexer em qualquer coisa
# ─────────────────────────────────────────────────────────────────
preflight() {
  passo "Conferindo o terreno"

  command -v docker >/dev/null || { vermelho "docker nao encontrado"; exit 1; }
  docker info >/dev/null 2>&1  || { vermelho "o docker nao esta' rodando"; exit 1; }
  [[ -f docker-compose.yml ]]  || { vermelho "docker-compose.yml nao encontrado em $RAIZ"; exit 1; }
  [[ -f .env ]]                || amarelo "   aviso: .env nao encontrado"

  local livre_mb
  livre_mb=$(df -Pm "$RAIZ" | awk 'NR==2 {print $4}')
  if (( livre_mb < ESPACO_MINIMO_MB )); then
    vermelho "   so' restam ${livre_mb}MB livres (minimo ${ESPACO_MINIMO_MB}MB). Deploy cancelado."
    exit 1
  fi
  echo "   disco livre: ${livre_mb}MB"
  echo "   branch: $(git rev-parse --abbrev-ref HEAD) | commit: $(git rev-parse --short HEAD)"
}

# ─────────────────────────────────────────────────────────────────
# Backup: banco (copia consistente, com o app rodando) + .env
# ─────────────────────────────────────────────────────────────────
fazer_backup() {
  local carimbo destino
  carimbo="$(date +%Y-%m-%d_%H%M%S)"
  destino="$BACKUPS/$carimbo"
  mkdir -p "$destino"

  passo "Backup em backups/$carimbo"

  if [[ -f data/index.db ]]; then
    # A API de backup do sqlite copia com o app escrevendo; `cp` puro pode
    # pegar o arquivo no meio de uma transacao e salvar um banco quebrado.
    python3 - "$destino/index.db" <<'PY'
import sqlite3, sys
origem = sqlite3.connect("data/index.db")
destino = sqlite3.connect(sys.argv[1])
with destino:
    origem.backup(destino)
destino.close(); origem.close()
PY
    echo "   banco:  $(du -h "$destino/index.db" | cut -f1)"
  else
    amarelo "   data/index.db nao existe (primeiro deploy?)"
  fi

  [[ -f .env ]] && cp .env "$destino/.env" && echo "   .env:   copiado"

  {
    echo "data=$(date -Iseconds)"
    echo "branch=$(git rev-parse --abbrev-ref HEAD)"
    echo "commit=$(git rev-parse HEAD)"
    echo "imagem=$(docker image inspect --format '{{.Id}}' "$IMAGEM" 2>/dev/null || echo 'nenhuma')"
    echo "manuais=$(python3 -c "import sqlite3;print(sqlite3.connect('data/index.db').execute('select count(*) from manuals').fetchone()[0])" 2>/dev/null || echo '?')"
  } > "$destino/manifest.txt"

  # descarta os mais velhos, mantendo os ultimos $MANTER
  local velhos
  velhos=$(find "$BACKUPS" -maxdepth 1 -type d -name '20*' | sort -r | tail -n +$((MANTER + 1)) || true)
  if [[ -n "$velhos" ]]; then
    echo "$velhos" | while read -r d; do rm -rf "$d"; echo "   removido backup antigo: $(basename "$d")"; done
  fi

  echo "$carimbo"> "$BACKUPS/.ultimo"
}

# ─────────────────────────────────────────────────────────────────
# Commit: o que esta' no ar precisa existir no historico
# ─────────────────────────────────────────────────────────────────
commitar() {
  local mensagem="$1"
  passo "Commit do codigo"

  if [[ -z "$(git status --porcelain)" ]]; then
    echo "   nada mudou desde o ultimo commit"
    return
  fi

  git add -A
  local arquivos
  arquivos=$(git diff --cached --name-only | wc -l)
  git commit -q -m "$mensagem"
  verde "   $arquivos arquivo(s) commitados: $(git rev-parse --short HEAD)"
  echo "   (o push para o remoto continua manual, de proposito)"
}

# ─────────────────────────────────────────────────────────────────
# Saude: o app responde E consegue ler o banco?
# ─────────────────────────────────────────────────────────────────
esta_saudavel() {
  local tentativas="${1:-30}" i=0
  while (( i < tentativas )); do
    if curl -fsS -o /dev/null --max-time 5 "$SAUDE_URL/" 2>/dev/null \
       && curl -fsS --max-time 5 "$SAUDE_URL/api/plans" 2>/dev/null | grep -q '"slug"'; then
      return 0
    fi
    i=$((i + 1))
    sleep 2
  done
  return 1
}

# ─────────────────────────────────────────────────────────────────
# Deploy
# ─────────────────────────────────────────────────────────────────
deploy() {
  local mensagem="$1" commitar_sim="$2"

  preflight
  fazer_backup
  local carimbo; carimbo="$(cat "$BACKUPS/.ultimo")"

  [[ "$commitar_sim" == "sim" ]] && commitar "$mensagem"

  passo "Guardando a imagem que esta' no ar"
  if docker image inspect "$IMAGEM" >/dev/null 2>&1; then
    docker tag "$IMAGEM" "$IMAGEM_ANTERIOR"
    docker image inspect --format '{{.Id}}' "$IMAGEM" > "$BACKUPS/.imagem_anterior"
    echo "   $IMAGEM_ANTERIOR <- $(docker image inspect --format '{{.Id}}' "$IMAGEM" | cut -c8-19)"
  else
    amarelo "   nenhuma imagem anterior (primeiro deploy): rollback automatico nao vai existir"
  fi

  passo "Construindo e subindo"
  if ! docker compose up -d --build; then
    vermelho "   a construcao falhou. Nada foi trocado: o que estava no ar continua no ar."
    exit 1
  fi

  passo "Conferindo se respondeu"
  if esta_saudavel 30; then
    verde "   ok: $SAUDE_URL responde e o banco esta' legivel"
  else
    vermelho "   o app NAO respondeu em 60s. Voltando para a versao anterior..."
    docker compose logs --tail 25 "$SERVICO" 2>&1 | sed 's/^/      /'
    rollback "automatico"
    exit 1
  fi

  local commit; commit="$(git rev-parse --short HEAD)"
  local manuais; manuais=$(curl -fsS "$SAUDE_URL/api/plans" >/dev/null 2>&1 && \
    python3 -c "import sqlite3;print(sqlite3.connect('data/index.db').execute('select count(*) from manuals').fetchone()[0])" 2>/dev/null || echo '?')

  mkdir -p "$BACKUPS"
  echo "$(date -Iseconds) | commit=$commit | backup=$carimbo | imagem=$(docker image inspect --format '{{.Id}}' "$IMAGEM" | cut -c8-19) | manuais=$manuais" >> "$HISTORICO"

  passo "Pronto"
  verde "   no ar: commit $commit | $manuais manuais no acervo"
  echo "   backup deste deploy: backups/$carimbo"
  echo "   se der problema:     ./scripts/deploy.sh --rollback"
}

# ─────────────────────────────────────────────────────────────────
# Rollback: volta a imagem anterior (codigo), nao o banco
# ─────────────────────────────────────────────────────────────────
rollback() {
  local origem="${1:-manual}"
  passo "Rollback ($origem)"

  if ! docker image inspect "$IMAGEM_ANTERIOR" >/dev/null 2>&1; then
    vermelho "   nao existe imagem anterior guardada. Nada a fazer."
    return 1
  fi

  # guarda a que falhou, para dar para investigar depois
  if docker image inspect "$IMAGEM" >/dev/null 2>&1; then
    docker tag "$IMAGEM" "manuais-api:falhou" && echo "   imagem com problema salva como manuais-api:falhou"
  fi

  docker tag "$IMAGEM_ANTERIOR" "$IMAGEM"
  docker compose up -d --force-recreate --no-build "$SERVICO" >/dev/null

  if esta_saudavel 20; then
    verde "   voltou e esta' respondendo"
    local anterior
    anterior=$(tail -2 "$HISTORICO" 2>/dev/null | head -1 | grep -o 'commit=[a-f0-9]*' | cut -d= -f2 || true)
    [[ -n "$anterior" ]] && echo "   codigo correspondente: git checkout $anterior"
    echo "   o BANCO nao foi tocado. Se precisar dele de volta:"
    echo "      ./scripts/deploy.sh --restaurar-banco $(ls -1 "$BACKUPS" | grep '^20' | tail -1)"
  else
    vermelho "   a versao anterior tambem nao respondeu. Olhe os logs:"
    echo "      docker compose logs --tail 50 $SERVICO"
    return 1
  fi
}

# ─────────────────────────────────────────────────────────────────
# Restaurar banco: destrutivo, so' na mao e com backup do atual antes
# ─────────────────────────────────────────────────────────────────
restaurar_banco() {
  local carimbo="${1:-}"
  local origem="$BACKUPS/$carimbo/index.db"

  [[ -n "$carimbo" ]] || { vermelho "informe qual backup. Veja com --status"; exit 1; }
  [[ -f "$origem" ]]  || { vermelho "backup nao encontrado: $origem"; exit 1; }

  passo "Restaurar o banco de $carimbo"
  amarelo "   ATENCAO: tudo que entrou no sistema depois de $carimbo sera' perdido"
  echo -n "   digite CONFIRMO para seguir: "
  local resposta; read -r resposta
  [[ "$resposta" == "CONFIRMO" ]] || { echo "   cancelado"; exit 0; }

  local salvamento="$BACKUPS/antes-de-restaurar_$(date +%Y-%m-%d_%H%M%S)"
  mkdir -p "$salvamento"
  cp data/index.db "$salvamento/index.db"
  echo "   banco atual guardado em $(basename "$salvamento")"

  docker compose stop "$SERVICO" >/dev/null
  cp "$origem" data/index.db
  docker compose start "$SERVICO" >/dev/null

  if esta_saudavel 20; then
    verde "   banco restaurado e app respondendo"
  else
    vermelho "   o app nao subiu depois da restauracao. Logs:"
    docker compose logs --tail 30 "$SERVICO"
  fi
}

# ─────────────────────────────────────────────────────────────────
status() {
  passo "No ar agora"
  docker compose ps --format "   {{.Name}}  {{.Status}}" 2>/dev/null || echo "   container parado"
  echo "   commit:  $(git rev-parse --short HEAD) ($(git rev-parse --abbrev-ref HEAD))"
  echo "   imagem:  $(docker image inspect --format '{{.Id}}' "$IMAGEM" 2>/dev/null | cut -c8-19 || echo '-')"
  if esta_saudavel 1; then verde "   saude:   respondendo"; else vermelho "   saude:   NAO responde"; fi
  python3 -c "import sqlite3;c=sqlite3.connect('data/index.db');print('   acervo:  %d manuais, %d paginas'%(c.execute('select count(*) from manuals').fetchone()[0],c.execute('select count(*) from pages').fetchone()[0]))" 2>/dev/null || true

  passo "Backups guardados"
  if [[ -d "$BACKUPS" ]]; then
    find "$BACKUPS" -maxdepth 1 -type d -name '20*' | sort -r | while read -r d; do
      printf '   %-22s %6s  %s\n' "$(basename "$d")" \
        "$(du -h "$d/index.db" 2>/dev/null | cut -f1 || echo '-')" \
        "$(grep -o 'manuais=.*' "$d/manifest.txt" 2>/dev/null || true)"
    done
  else
    echo "   nenhum"
  fi

  if [[ -f "$HISTORICO" ]]; then
    passo "Ultimos deploys"
    tail -5 "$HISTORICO" | sed 's/^/   /'
  fi
}

# ─────────────────────────────────────────────────────────────────
MENSAGEM="deploy: $(date '+%d/%m/%Y %H:%M')"
COMMITAR="sim"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--mensagem)      MENSAGEM="${2:-$MENSAGEM}"; shift 2 ;;
    --sem-commit)       COMMITAR="nao"; shift ;;
    --rollback)         rollback "manual"; exit $? ;;
    --status)           status; exit 0 ;;
    --restaurar-banco)  restaurar_banco "${2:-}"; exit $? ;;
    -h|--help)          sed -n '3,20p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *)                  vermelho "opcao desconhecida: $1"; exit 1 ;;
  esac
done

deploy "$MENSAGEM" "$COMMITAR"
