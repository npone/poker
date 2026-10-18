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
  python3 - "$CFG" "$PORT" "$HOST" <<'PY'
import re, sys
cfg, port, host = sys.argv[1:]
lines = open(cfg).read().splitlines(keepends=True)
idx = next(i for i, l in enumerate(lines) if re.match(r'\s*-\s*service:', l))   # the catch-all
indent = re.match(r'(\s*)-', lines[idx]).group(1)
lines.insert(idx, f"{indent}- hostname: {host}\n{indent}  service: http://127.0.0.1:{port}\n")
open(cfg, "w").write("".join(lines))
PY
  rollback() { echo "!! $1 — restoring $BACKUP"; cp -p "$BACKUP" "$CFG"; systemctl restart cloudflared || true; exit 1; }
  cloudflared --config "$CFG" tunnel ingress validate || rollback "ingress validation failed"
  systemctl restart cloudflared || rollback "cloudflared restart failed"
  sleep 4
  # every http route that existed before must still answer (5xx or no answer = broken)
  for h in $(awk '/hostname:/{h=$NF} /service: https?:\/\//{print h}' "$BACKUP"); do
    code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "https://$h/")"
    [[ $code =~ ^[1-4][0-9][0-9]$ ]] || rollback "$h answered $code"
  done
  echo "==> tunnel restarted; every existing http route still answers"
  sudo -u nliu cloudflared tunnel route dns "$TUNNEL" "$HOST" \
    || echo "!! route dns $HOST failed — if a record for $HOST already exists, fix it in Cloudflare DNS"
fi
echo "Done. Check: curl -s https://$HOST/api/v1/health"
