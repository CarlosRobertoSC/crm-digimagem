#!/usr/bin/env bash
# Backup consistente do SQLite (pode rodar com o app no ar) — guarda 14 dias.
set -euo pipefail
TS=$(date +%Y-%m-%d_%H%M%S)
mkdir -p /opt/crm/backups
sqlite3 /opt/crm/data/crm.db ".backup '/opt/crm/backups/crm-${TS}.db'"
ls -1t /opt/crm/backups/crm-*.db 2>/dev/null | tail -n +15 | xargs -r rm --
echo "backup ok: /opt/crm/backups/crm-${TS}.db"
