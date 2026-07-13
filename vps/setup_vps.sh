#!/usr/bin/env bash
# ============================================================
# CRM-Digimagem — Instalador de PRODUÇÃO para VPS Ubuntu
# (testado para Oracle Cloud; funciona em qualquer Ubuntu 22/24)
#
# USO:  bash setup_vps.sh https://github.com/SEU_USUARIO/crm-digimagem.git
#
# O que ele faz, na ordem:
#  1. Instala Python, git, nginx e sqlite3
#  2. Cria a estrutura: /opt/crm/app (código) · /opt/crm/data (BANCO,
#     nunca tocado por atualizações) · /opt/crm/backups
#  3. Baixa o código do seu GitHub e instala as dependências (venv)
#  4. Cria o serviço systemd "crm" (sobe sozinho no boot, reinicia se cair)
#  5. Configura o nginx como porta de entrada (porta 80)
#  6. Abre as portas 80/443 no firewall interno da imagem Oracle
#  7. Agenda backup diário do banco às 02:30 (guarda os últimos 14)
# ============================================================
set -euo pipefail

REPO_URL="${1:?Uso: bash setup_vps.sh https://github.com/SEU_USUARIO/crm-digimagem.git}"
APP_USER="$(whoami)"

echo "==> [1/7] Instalando dependências do sistema…"
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip git nginx sqlite3

echo "==> [2/7] Criando a estrutura em /opt/crm…"
sudo mkdir -p /opt/crm/data /opt/crm/backups
sudo chown -R "$APP_USER":"$APP_USER" /opt/crm

echo "==> [3/7] Baixando o código e instalando dependências…"
if [ ! -d /opt/crm/app/.git ]; then
  git clone "$REPO_URL" /opt/crm/app
fi
python3 -m venv /opt/crm/venv
/opt/crm/venv/bin/pip install --upgrade pip -q
/opt/crm/venv/bin/pip install -r /opt/crm/app/requirements.txt -q

echo "==> [4/7] Criando o serviço systemd (crm)…"
sudo tee /etc/systemd/system/crm.service >/dev/null <<UNIT
[Unit]
Description=CRM Digimagem (gunicorn)
After=network.target

[Service]
User=${APP_USER}
WorkingDirectory=/opt/crm/app
Environment=CRM_DB_PATH=/opt/crm/data/crm.db
Environment=CRM_SEED_DEMO=0
Environment=CRM_ADMIN_NOME=Administrador
Environment=CRM_ADMIN_EMAIL=admin@digimagem.com
Environment=CRM_ADMIN_SENHA=trocar123
ExecStart=/opt/crm/venv/bin/gunicorn app:app --workers 1 --threads 8 --timeout 120 --bind 127.0.0.1:8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now crm

echo "==> [5/7] Configurando o nginx (porta 80 -> app)…"
sudo tee /etc/nginx/sites-available/crm >/dev/null <<'NGINX'
server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 10m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
NGINX
sudo ln -sf /etc/nginx/sites-available/crm /etc/nginx/sites-enabled/crm
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

echo "==> [6/7] Abrindo portas 80/443 no firewall interno (imagem Oracle)…"
sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent >/dev/null 2>&1 || true
sudo netfilter-persistent save >/dev/null 2>&1 || true

echo "==> [7/7] Agendando backup diário do banco (02:30)…"
chmod +x /opt/crm/app/vps/backup.sh /opt/crm/app/vps/deploy.sh
( crontab -l 2>/dev/null | grep -v "vps/backup.sh" ; echo "30 2 * * * /opt/crm/app/vps/backup.sh" ) | crontab -

IP=$(curl -s ifconfig.me || hostname -I | awk '{print $1}')
echo
echo "============================================================"
echo " PRONTO! O CRM está no ar."
echo
echo "   Acesse:  http://${IP}"
echo "   Login inicial: admin@digimagem.com / trocar123"
echo "   >>> TROQUE A SENHA no primeiro acesso (tela Equipe) <<<"
echo
echo "   Atualizar o app no futuro:  bash /opt/crm/app/vps/deploy.sh"
echo "   Backups diários em:         /opt/crm/backups/"
echo "   Banco de dados (intocável): /opt/crm/data/crm.db"
echo "============================================================"
