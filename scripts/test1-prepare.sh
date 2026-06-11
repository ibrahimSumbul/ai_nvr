#!/usr/bin/env bash
# Test 1 hazırlık — stack up, migrate, ön kontroller.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT_DIR="${ROOT}/perf/runs/test1"
PREFLIGHT="${OUT_DIR}/preflight.txt"

mkdir -p "$OUT_DIR"

log() { echo "[test1-prepare] $*"; }

if ! command -v colima >/dev/null 2>&1; then
  log "UYARI: colima yok — Docker Desktop kullanıyorsan devam edebilirsin."
elif ! colima status 2>/dev/null | grep -q "Running"; then
  log "Colima başlatılıyor (default profil)..."
  colima start
  docker context use colima >/dev/null 2>&1 || true
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon erişilemiyor. colima start veya Docker Desktop aç." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo ".env yok. cp .env.example .env doldur." >&2
  exit 1
fi

log "Stack ayağa kaldırılıyor..."
docker compose up -d --build

log "Alembic migrate (M7 disk_status + service_status)..."
docker compose run --rm --entrypoint "" bridge alembic upgrade head

log "Frigate config reload..."
docker compose restart frigate bridge

log "Sağlık bekleniyor (45s)..."
sleep 45

{
  echo "# Test 1 preflight — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "git=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo ""
  echo "## docker compose ps"
  docker compose ps
  echo ""
  echo "## colima"
  colima list 2>/dev/null || echo "n/a"
  echo ""
  echo "## Frigate cameras (fps)"
  if curl -sf --max-time 10 http://localhost:5100/api/stats >/dev/null; then
    curl -sf http://localhost:5100/api/stats | python3 -c "
import json,sys
d=json.load(sys.stdin)
cams=d.get('cameras',d)
for k,v in sorted(cams.items()):
    if isinstance(v,dict) and 'camera_fps' in v:
        print(f'  {k}: camera_fps={v.get(\"camera_fps\",0)} detection_fps={v.get(\"detection_fps\",0)} skipped={v.get(\"skipped_fps\",0)}')
dets=d.get('detectors',{})
for k,v in sorted(dets.items()):
    if isinstance(v,dict):
        print(f'  detector {k}: inference={v.get(\"inference_speed\",\"?\")}ms')
" 2>/dev/null || curl -sf http://localhost:5100/api/stats | head -c 2000
  else
    echo "  FRIGATE ERİŞİLEMEDİ — localhost:5100"
  fi
  echo ""
  echo "## Ollama"
  if curl -sf --max-time 5 http://localhost:11434/api/tags >/dev/null; then
    curl -sf http://localhost:11434/api/tags | python3 -c "import json,sys; m=[x['name'] for x in json.load(sys.stdin).get('models',[])]; print('  models:', ', '.join(m[:5]))" 2>/dev/null || echo "  tags ok"
  else
    echo "  Ollama erişilemedi (host:11434) — LLM demo etkilenir, perf detect etkilenmez"
  fi
} | tee "$PREFLIGHT"

log "Preflight → $PREFLIGHT"
log "Hazır. Deneme: ./scripts/test1-run.sh trial 600"
