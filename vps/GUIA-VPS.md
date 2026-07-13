# 🚀 GUIA — Colocar o CRM-Digimagem no ar na VPS Oracle

Este guia assume o ponto onde você parou: **instância criada, com IP público
(Ephemeral)**. São 4 etapas. Reserve ~20 minutos.

---

## ETAPA 1 — Abrir as portas 80 e 443 no painel da Oracle

A Oracle bloqueia tudo por padrão. Sem este passo, o site nunca abre.

1. No painel da Oracle: **Menu ☰ → Networking → Virtual Cloud Networks**.
2. Clique na sua VCN → no menu esquerdo, **Security Lists** → clique na
   *Default Security List*.
3. Clique **Add Ingress Rules** e crie DUAS regras:
   - Regra 1: Source CIDR `0.0.0.0/0` · IP Protocol `TCP` · Destination Port `80`
   - Regra 2: Source CIDR `0.0.0.0/0` · IP Protocol `TCP` · Destination Port `443`
4. Salve.

> 💡 Dica: em **Compute → Instances → sua instância → Attached VNICs → IP
> Addresses**, você pode converter o IP *Ephemeral* em **Reserved** (Edit →
> Reserved). Assim o IP nunca muda, mesmo que a instância seja recriada.

---

## ETAPA 2 — Conectar na VPS pelo seu Windows

Abra o **PowerShell** e conecte com a chave que você baixou ao criar a
instância (arquivo `.key`):

```powershell
ssh -i C:\caminho\para\sua-chave.key ubuntu@SEU_IP_PUBLICO
```

- O usuário é `ubuntu` (imagens Ubuntu da Oracle).
- Se der erro de permissão na chave: clique com o direito no arquivo .key →
  Propriedades → Segurança → deixe apenas o seu usuário com acesso.

---

## ETAPA 3 — Instalar o CRM (2 comandos)

Dentro da VPS (terminal que abriu no passo anterior):

```bash
sudo apt-get update -y && sudo apt-get install -y git
git clone https://github.com/SEU_USUARIO/crm-digimagem.git ~/crm-tmp && bash ~/crm-tmp/vps/setup_vps.sh https://github.com/SEU_USUARIO/crm-digimagem.git
```

**Troque `SEU_USUARIO` pelo seu usuário do GitHub nos DOIS lugares.**

> ⚠️ Se o seu repositório for **privado**, o `git clone` pedirá login. Use um
> *Personal Access Token* do GitHub (Settings → Developer settings → Tokens)
> como senha, ou torne o repositório público (Settings → General → Danger
> Zone → Change visibility).

O instalador faz tudo sozinho (dependências, serviço, nginx, firewall,
backup diário). Ao final ele imprime o endereço de acesso.

**Primeiro acesso:** `http://SEU_IP` → login `admin@digimagem.com` /
`trocar123` → **troque a senha imediatamente** na tela **Equipe** e cadastre
os usuários reais da equipe. O banco nasce **limpo** (sem os dados de
exemplo do Render) — produção começa do zero, do jeito certo.

---

## ETAPA 4 — Seu fluxo de trabalho daqui em diante

O desenho que você pediu, funcionando assim:

```
 [Eu + Claude]  →  GitHub (push)  →  Render (testes, dados de exemplo)
                                   ↘
                                     VPS Oracle (produção, dados REAIS)
                                     atualiza SÓ quando você mandar
```

1. **Testar**: publica a versão nova no GitHub → Render atualiza sozinho →
   você testa lá à vontade (o Render usa dados de exemplo, pode quebrar).
2. **Aprovou?** Conecte na VPS (Etapa 2) e rode **um comando**:
   ```bash
   bash /opt/crm/app/vps/deploy.sh
   ```
   Ele faz backup do banco → baixa o código novo → reinicia. **Nenhum dado é
   perdido**: o banco fica em `/opt/crm/data/crm.db`, fora da pasta do
   código, e as migrações automáticas do app criam sozinhas qualquer tabela
   ou coluna nova da versão (é o mesmo mecanismo que já usamos em todas as
   versões até aqui).

### Por que os dados nunca se perdem?

| O quê                  | Onde vive              | O deploy toca?      |
|------------------------|------------------------|---------------------|
| Código do app          | `/opt/crm/app/`        | ✅ Sim (git pull)   |
| **Banco de dados**     | `/opt/crm/data/crm.db` | ❌ Nunca            |
| Backups (14 dias)      | `/opt/crm/backups/`    | ➕ Ganha mais um    |

### Comandos úteis na VPS

```bash
sudo systemctl status crm        # o app está rodando?
sudo journalctl -u crm -n 50     # últimas 50 linhas de log do app
bash /opt/crm/app/vps/backup.sh  # backup manual agora
sudo systemctl restart crm       # reiniciar o app
```

### Restaurar um backup (se um dia precisar)

```bash
sudo systemctl stop crm
cp /opt/crm/backups/crm-DATA_ESCOLHIDA.db /opt/crm/data/crm.db
sudo systemctl start crm
```

---

## Próximos upgrades recomendados (quando quiser)

1. **Domínio + HTTPS (cadeado)**: compre um domínio (~R$ 40/ano), aponte um
   registro A para o IP da VPS e rode na VPS:
   `sudo apt install -y certbot python3-certbot-nginx && sudo certbot --nginx`
   — o certbot configura o HTTPS sozinho e renova automaticamente.
2. **Backup para fora da VPS**: copiar os backups para um Google Drive
   (rclone) — me peça que eu preparo.
