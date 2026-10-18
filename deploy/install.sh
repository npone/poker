#!/usr/bin/env bash
# Run the poker server on 127.0.0.1:8094 and route poker.npone.dev to it through dev176's
# existing Cloudflare tunnel. Shared ground: take the cloudflared-config lease in the
# dev176-tunnel coord channel first (see ~/dev/CLAUDE.md, "The tunnel").
# Usage:  sudo bash ~/dev/poker/deploy/install.sh     (safe to re-run)
# Backs up the tunnel config and restores it if validation, the restart or a route check fails.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
PORT=8094
HOST=poker.npone.dev
CFG=/etc/cloudflared/config.yml

# 1. The service
install -m 0644 "$HERE/poker.service" /etc/systemd/system/poker.service
systemctl daemon-reload
systemctl enable poker
systemctl restart poker
for _ in $(seq 20); do curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/v1/health" && break; sleep 0.5; done
curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/v1/health"
echo "==> serving on 127.0.0.1:$PORT"

# 2. Ingress rule above the catch-all, unless already there
if grep -q "hostname: $HOST$" "$CFG"; then
  echo "==> $HOST already in $CFG; tunnel untouched"
else
  TUNNEL="$(awk '/^tunnel:/{print $2}' "$CFG")"
  BACKUP="$CFG.bak.$(date +%Y%m%d%H%M%S)"
  cp -p "$CFG" "$BACKUP"
  # status of every existing http route before we touch anything; afterwards each must be back
  declare -A BEFORE
  ROUTES="$(awk '/hostname:/{h=$NF} /service: https?:\/\//{print h}' "$CFG")"
  for h in $ROUTES; do BEFORE[$h]="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "https://$h/" || true)"; done
  python3 - "$CFG" "$PORT" "$HOST" <<'PY'
import os, re, shutil, sys
cfg, port, host = sys.argv[1:]
lines = open(cfg).read().splitlines(keepends=True)
idx = next(i for i, l in enumerate(lines) if re.match(r'\s*-\s*service:', l))   # the catch-all
indent = re.match(r'(\s*)-', lines[idx]).group(1)
lines.insert(idx, f"{indent}- hostname: {host}\n{indent}  service: http://127.0.0.1:{port}\n")
tmp = cfg + ".tmp"                   # atomic: a crash mid-write must not leave a truncated config
with open(tmp, "w") as f:
    f.write("".join(lines))
shutil.copystat(cfg, tmp)
os.replace(tmp, cfg)
PY
  rollback() {
    echo "!! $1 — restoring $BACKUP"
    cp -p "$BACKUP" "$CFG.tmp" && mv -f "$CFG.tmp" "$CFG"
    systemctl restart cloudflared || true
    exit 1
  }
  cloudflared --config "$CFG" tunnel ingress validate || rollback "ingress validation failed"
  systemctl restart cloudflared || rollback "cloudflared restart failed"
  # each route that answered (<500) before must answer again within ~30 s; one that was
  # already down is reported, not held against this install
  for h in $ROUTES; do
    was="${BEFORE[$h]}"
    if ! [[ $was =~ ^[1-4][0-9][0-9]$ ]]; then echo "   ($h was already answering $was; not checked)"; continue; fi
    code=000
    for _ in $(seq 15); do
      code="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "https://$h/" || true)"
      [[ $code =~ ^[1-4][0-9][0-9]$ ]] && break
      sleep 2
    done
    [[ $code =~ ^[1-4][0-9][0-9]$ ]] || rollback "$h answered $code after the restart (was $was)"
  done
  echo "==> tunnel restarted; every route that answered before answers again"
  sudo -u nliu cloudflared tunnel route dns "$TUNNEL" "$HOST" \
    || echo "!! route dns $HOST failed — if a record for $HOST already exists, fix it in Cloudflare DNS"
fi
echo "Done. Check: curl -s https://$HOST/api/v1/health"
