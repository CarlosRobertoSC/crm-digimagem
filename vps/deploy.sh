#!/usr/bin/env bash
# ============================================================
# CRM-Digimagem — ATUALIZAÇÃO de produção (roda na VPS)
# Uso: bash /opt/crm/app/vps/deploy.sh
#
# 1. Faz um backup do banco ANTES de qualquer coisa
# 2. Puxa a versão mais nova do GitHub (só o código!)
# 3. Atualiza dependências e reinicia o serviço
# O banco em /opt/crm/data/crm.db NÃO é tocado — as migrações
# automáticas do app cuidam de colunas/tabelas novas no boot.
# ============================================================
set -euo pipefail
echo "==> Backup de segurança antes de atualizar…"
/opt/crm/app/vps/backup.sh
echo "==> Baixando a versão mais nova do GitHub…"
cd /opt/crm/app
git pull
echo "==> Atualizando dependências…"
/opt/crm/venv/bin/pip install -r requirements.txt -q
echo "==> Reiniciando o serviço…"
sudo systemctl restart crm
sleep 2
sudo systemctl --no-pager --lines=0 status crm | head -3
echo "==> Atualizado com sucesso. Dados preservados em /opt/crm/data/crm.db"
