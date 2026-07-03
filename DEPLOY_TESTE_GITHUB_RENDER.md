# CRM-Digimagem — Guia de Deploy no Ambiente de Teste (GitHub + Render)

Este guia leva o projeto do seu computador até um link de teste na internet
(`https://algumnome.onrender.com`), com deploy automático toda vez que o
código for atualizado no GitHub. **Isso é só o ambiente de teste** — quando
o app estiver pronto de verdade, migramos para a VPS da Hostinger.

---

## Parte 1 — Subir o projeto pro GitHub (via GitHub Desktop)

1. Abra o **GitHub Desktop** e faça login (clique em "Sign in to GitHub.com",
   ele abre o navegador — nunca digite a senha dentro de um chat ou programa
   que não seja o site oficial do GitHub).
2. No menu **File → New Repository**:
   - Name: `crm-digimagem`
   - Local Path: escolha uma pasta no seu computador
   - Deixe **"Initialize this repository with a README" desmarcado** (o projeto
     já tem os arquivos prontos, vamos copiar por cima).
3. Copie **todo o conteúdo** da pasta `crm-digimagem-app` que você baixou daqui
   pra dentro da pasta que o GitHub Desktop acabou de criar.
4. Volte pro GitHub Desktop. Ele vai listar todos os arquivos como "mudanças".
   Escreva uma mensagem tipo `Versão inicial` no campo de baixo à esquerda e
   clique em **"Commit to main"**.
5. Clique em **"Publish repository"** no topo. Marque a opção **"Keep this
   code private"** (importante — mantém o repositório fechado, só você vê).
6. Pronto — o projeto está no GitHub.

### Quando eu (Claude) te entregar uma atualização depois disso

Toda vez que eu enviar uma nova versão do `app.py` ou `dashboard.html`:
1. Baixe o zip novo.
2. Substitua os arquivos correspondentes na sua pasta local do projeto
   (a mesma pasta ligada ao GitHub Desktop).
3. Abra o GitHub Desktop — ele detecta sozinho o que mudou.
4. Escreva uma mensagem breve (ex: `Ajuste no relatorio de forecast`) e
   clique em **"Commit to main"** → **"Push origin"**.
5. Pronto. Se o passo da Parte 2 já estiver feito, o Render redeploya sozinho
   em 1-3 minutos.

---

## Parte 2 — Conectar o Render ao repositório

1. Crie uma conta em **render.com** (dá pra entrar direto com a conta do
   GitHub, fica mais simples).
2. No painel, clique em **"New +"** → **"Web Service"**.
3. Escolha **"Build and deploy from a Git repository"** e autorize o Render
   a acessar o repositório `crm-digimagem` que você acabou de criar.
4. Preencha:
   - **Name**: `crm-digimagem` (vira parte do link: `crm-digimagem.onrender.com`)
   - **Region**: a mais próxima do Brasil disponível (ex: Ohio/US East costuma
     ser a de menor latência das opções gratuitas)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --workers 1 --threads 4 --timeout 60`
   - **Instance Type**: **Free**
5. Em **"Environment Variables"**, adicione:
   - `SECRET_KEY` → gere um valor aleatório (pode usar
     [este gerador](https://randomkeygen.com/) e copiar uma "CodeIgniter
     Encryption Key", por exemplo) — isso protege o login dos usuários.
   - `FLASK_DEBUG` → **não crie essa variável** (deixe ausente = modo seguro).
6. Clique em **"Create Web Service"**. O primeiro deploy leva uns 2-5 minutos.
7. Quando terminar, o Render te dá um link tipo
   `https://crm-digimagem.onrender.com` — esse é o endereço de teste.

### Importante sobre esse ambiente gratuito

- **Ele "dorme" depois de 15 minutos sem uso.** A primeira pessoa que acessar
  depois disso espera de 10 a 60 segundos pra ele "acordar" — depois disso
  fica rápido normalmente.
- **Os dados resetam** toda vez que você faz um novo deploy (push no GitHub)
  ou quando ele "dorme" por muito tempo — ele volta pros dados de exemplo
  (os mesmos logins de teste: `admin1@digimagem.com` / `admin123` etc.).
  Isso é esperado nessa fase — é ambiente de teste, não guarda histórico real.
  Quando migrarmos pra Hostinger, os dados passam a ser permanentes de verdade.
- Não precisa cartão de crédito pra esse plano.

### Não deixar o link "público" de verdade

Por padrão o Render não indexa o app no Google, mas pra garantir, adicione
este arquivo em `static/robots.txt` (posso gerar se você quiser) bloqueando
os buscadores. De resto, como o app já exige login, só quem tem usuário e
senha entra — o link em si pode ser compartilhado sem problema.

---

## Quando migrar pra Hostinger (mais pra frente)

Quando você chegar numa versão final satisfatória testando no Render, me avise
que eu preparo os arquivos de produção de verdade (Nginx, systemd, HTTPS,
backup automático do banco) pra rodar na VPS, com dados permanentes.
