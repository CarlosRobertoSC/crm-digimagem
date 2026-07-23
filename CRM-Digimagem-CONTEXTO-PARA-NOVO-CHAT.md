# 📋 CRM-DIGIMAGEM — Contexto do projeto (handoff para novo chat)

> **Como usar:** anexe este arquivo na primeira mensagem do chat novo e diga algo
> como *"Este é o contexto do meu projeto, leia antes de começarmos"*.
> Anexe também o **último .zip do sistema** (`crm-digimagem-v52.zip`) e a planilha
> **`Base_Comercial_Digimagem.xlsx`**, que são usados o tempo todo.

*Atualizado em 23/07/2026 · versão atual: **v52** · produção no ar*

---

## 1. O QUE É O SISTEMA

CRM de vendas da **Digimagem**, loja que vende equipamentos e insumos fotográficos
(impressoras Fujifilm, papéis, cartuchos, químicos, linha Instax). Usado pelo
dono (admin) e por 4 vendedores. Interface em **português do Brasil**.

**Stack:** Flask (Python) + SQLite + frontend single-file (`static/dashboard.html`,
HTML/CSS/JS puro, sem framework). Tema escuro.

**Tamanho atual:** `app.py` 4.544 linhas · `dashboard.html` 4.327 linhas ·
`schema.sql` 351 linhas · 21 tabelas · **77 rotas**.

**Arquivos do projeto:** `app.py`, `schema.sql`, `static/dashboard.html`,
`requirements.txt` (Flask, Werkzeug, itsdangerous, gunicorn==22.0.0,
**openpyxl==3.1.5**), `Procfile`, **`testes.py`**, **`testes_frontend.js`**,
pasta `vps/` (setup_vps.sh, deploy.sh, backup.sh, GUIA-VPS.md), README.md.

---

## 2. AMBIENTES (os três, e o papel de cada um)

| Ambiente | Endereço | Banco | Atualiza como |
|---|---|---|---|
| **GitHub** | github.com/CarlosRobertoSC/crm-digimagem | — | commit + push pelo GitHub Desktop |
| **Render** (teste) | https://crm-digimagem.onrender.com | **efêmero — zera a cada deploy** | **automático** (~1 min após o push) |
| **VPS Oracle** (produção) | **https://digimagemcrm.com.br** | permanente | **manual** (`deploy.sh`) |

**Fluxo padrão:** publicar no GitHub → Render atualiza sozinho → testar no Render
→ se aprovar, rodar `deploy.sh` na VPS → Ctrl+Shift+R no navegador.

**Importante:** o Render tem banco efêmero, então o catálogo nasce **vazio** —
é preciso reimportar a planilha a cada teste. Na VPS o catálogo é permanente.
A instância gratuita do Render **hiberna**: a primeira requisição pode demorar
50 segundos ou mais. Se algo não aparecer de imediato, espere antes de concluir
que quebrou.

### Acesso à VPS (produção)

```powershell
ssh -o ServerAliveInterval=60 -i C:\Users\user\Documents\chaves-oracle\ssh-key-2026-07-13.key ubuntu@163.176.55.51
```

Já com o **prompt verde** (`ubuntu@instance-...`):

```bash
bash /opt/crm/app/vps/deploy.sh
```

O script faz backup do banco **antes**, dá git pull, atualiza dependências e
reinicia o serviço. Os dados nunca são tocados.

Se o deploy disser `Already up to date.`, confirme se a versão esperada chegou
mesmo — por exemplo `grep -c "def editar_item_orcamento" /opt/crm/app/app.py`.
Já aconteceu de o script rodar limpo por já ter sido executado antes.

**Estrutura na VPS:** código em `/opt/crm/app/` · banco em
`/opt/crm/data/crm.db` · backups em `/opt/crm/backups/` (diário 02:30, 14 dias)
· serviço systemd `crm` (gunicorn 127.0.0.1:8000) + nginx.

**Regra de ouro do SSH:** só colar comandos quando o prompt estiver verde.
Se aparecer `PS C:\...>`, é o Windows. **Nunca rodar o comando `ssh` de dentro
do próprio SSH** (erro que já aconteceu duas vezes).

---

## 3. INFRAESTRUTURA JÁ RESOLVIDA (não precisa refazer)

- **HTTPS ativo:** domínio `digimagemcrm.com.br` (Hostinger, expira 2029-07-22),
  registro A `@` → 163.176.55.51 e CNAME `www`. Certificado Let's Encrypt via
  `certbot --nginx`, válido até 2026-10-20, **renovação automática**.
- **Backup fora da VPS:** script `C:\Users\user\backup-crm.ps1` baixa o banco por
  `scp` para `C:\Users\user\Google Drive\Backups-CRM\crm-AAAA-MM-DD.db` (o Google
  Drive é a unidade **G:**), apagando cópias com mais de 60 dias. Agendado no
  **Agendador de Tarefas do Windows**: *"Backup CRM Digimagem"*, segundas 10:00.
  Testado e funcionando.
- **RISCO CONHECIDO — IP efêmero:** o IP público da Oracle é *Ephemeral*.
  Decidimos **não** converter para Reserved (o processo se mostrou arriscado com
  a instância em produção). **Regra: nunca dar "Stop" na instância pelo painel
  da Oracle** — para reiniciar, usar `sudo reboot` via SSH. Se o IP mudar:
  atualizar o registro A na Hostinger e rodar o certbot de novo.

### Usuários

- **Produção (VPS):** Administrador 1 `admin@digimagem.com` (admin) ·
  **Administrador 2 `admin2@digimagem.com` (admin, conta de emergência)** ·
  Carlos Roberto `carlos.vendas@lojadigimagem.com.br` ·
  Ana `ana@lojadigimagem.com.br` · Tiago `tiago@lojadigimagem.com.br` ·
  Daniel `digimagemsc@hotmail.com` (todos vendedores).
- **Render (demo):** `admin1@digimagem.com` / `admin123` ·
  `ana@lojadigimagem.com.br` / `vendas123` (e os demais vendedores com `vendas123`).

O **Administrador 2** existe como rede de segurança contra perda de acesso; a
senha deve ficar guardada fora do sistema. O sistema exige **no mínimo 2
administradores ativos** (`active_admin_count`), então rebaixar ou desativar um
admin só funciona se o outro existir — crie o substituto **antes**, senão vem
HTTP 409.

**Decisão registrada:** promover um vendedor ativo a admin resolve o acesso, mas
custa caro — o admin **escapa da trava de preço** (`add_item_orcamento`), passa a
ver a carteira inteira e sai das metas de escopo "vendedores", que filtram por
`role = 'vendedor'`. Por isso o Daniel foi promovido e **revertido**, e a rede de
segurança virou uma conta dedicada.

**Redefinir a senha do admin** (se perder o acesso) — via SSH:

```bash
sqlite3 /opt/crm/data/crm.db "SELECT nome,email,role,ativo FROM users;"
/opt/crm/venv/bin/python3 -c "
from werkzeug.security import generate_password_hash
import sqlite3
c = sqlite3.connect('/opt/crm/data/crm.db')
n = c.execute('UPDATE users SET senha_hash=? WHERE email=?',
              (generate_password_hash('NOVASENHA'), 'admin@digimagem.com')).rowcount
c.commit(); print('atualizados:', n)"
```

---

## 4. COMO TRABALHAMOS (método que funcionou — manter)

1. **O usuário executa tudo** no PC/VPS/navegador/contas dele. O Claude **não tem
   acesso** a nada disso: orienta com comandos prontos e prints comentados.
2. **Claude testa a lógica** (roda o sistema no próprio ambiente, valida regras e
   números). **O usuário testa o visual** no Render/produção. Os dois testes se
   complementam — foi assim que se descobriu, por exemplo, que um botão estava
   funcionando mas invisível na tela usada.
3. **Toda entrega** = um `.zip` do projeto + um bloco com **Summary** (título
   curto para o campo Summary do GitHub Desktop) e **Description** (descrição do
   commit).
4. **Versionamento:** v1, v2, … Correção logo após uma versão já publicada ganha
   sufixo `b` (ex.: v45b, v50b). Se acumular, `c` (v51c). Quando a correção fica
   grande, vira versão nova.
5. **Antes de empacotar:** validar `python3 -m py_compile app.py` e extrair os
   `<script>` do HTML para rodar `node --check`. Depois **rodar as duas suítes**.
6. **O usuário quer honestidade**, não concordância. Ele pediu explicitamente:
   *"quero que seja verdadeiro e não me responda somente para me agradar"*.
   Discordar com fundamento é bem-vindo — várias decisões boas do projeto vieram
   de discordâncias explicadas.

### Testes automatizados (v49–v52)

```bash
python3 testes.py          # 94 verificações de backend
node testes_frontend.js    # 48 verificações de frontend
```

Ambos rodam da raiz do projeto, criam banco temporário e **não dependem da
planilha** (geram um produto de teste se ela não estiver ao lado). Cobrem:
login, criar negócio com itens, trava de preço, liberação (pedido, aprovação,
uso único, validade), faturamento bloqueado, edição de item, contador de
liberações, produto sem preço, exclusão de produto, auditoria e o comparador de
alterações. **Falta cobrir: meta contando unidades.**

### Lições que custaram caro

- **O que escapa dos testes é texto de interface.** Duas vezes a lógica estava
  certa e a mensagem na tela estava desatualizada ou errada. As capturas de tela
  do usuário valeram tanto quanto a suíte.
- **Teste que passa por sorte é pior que teste que falha.** Uma chamada nova
  dentro de um `try/catch` gerava `ReferenceError` engolido em `alert`, com a
  suíte verde. A correção foi assertar *"nenhum alerta inesperado"*.
- **Rodar a suíte inteira depois de qualquer mexida.** Um `NameError` numa
  linha de auditoria derrubava a aprovação de liberação inteira (sem `commit`,
  tudo era desfeito) — a suíte acusou 8 falhas em cascata.

### Armadilhas do ambiente de trabalho do Claude

- A pasta de trabalho **some entre turnos**. Para restaurar:
  `cd /home/claude && rm -rf app && unzip -q /mnt/user-data/outputs/crm-digimagem-vXX.zip`
  — **sempre apagar antes de reextrair**, senão fica uma versão misturada.
- O servidor Flask em background (`nohup ... &`) **frequentemente não persiste**
  entre comandos bash. A saída que funciona bem é usar o **`test_client()` do
  Flask** sobre um banco temporário (`os.environ["CRM_DB_PATH"]=...; import app;
  app.init_db_if_needed()`), sem HTTP. Para lógica de frontend, extrair as
  funções do HTML e rodar no `node` com um DOM falso.

---

## 5. REGRAS DE NEGÓCIO QUE IMPORTAM (decisões, não detalhes)

Estas são as escolhas conceituais do sistema. Mudá-las sem entender quebra a
lógica comercial.

**Preço e desconto**
- O **preço de tabela** vem da planilha e é sempre o preço de referência do
  vendedor. O **desconto do admin não muda o preço** — ele **amplia a margem de
  negociação**. Ex.: tabela R$ 500, desconto autorizado R$ 50 → o vendedor vende
  até R$ 450 **sem pedir nada**; a R$ 449 salva, mas precisa de aprovação.
- O desconto do admin **só amplia** a autonomia, nunca reduz o piso já existente
  na planilha. Ele **sobrevive à reimportação** da planilha.
- Onde o admin configura: **◎ Metas → Catálogo → coluna "💸 Desconto autorizado
  (R$)"** → digitar o valor e clicar fora (salva sozinho).
- **Produto sem preço de tabela não pode ser vendido (v50).** Sem preço não há
  piso, e a trava nunca dispararia: o item entraria aprovado por qualquer valor.
  Esses produtos somem da lista do orçamento e são recusados ao adicionar e ao
  editar — inclusive para o admin.

**A trava está no faturamento, não na proposta** (decisão da v37, e é a que faz
o sistema ser usado em vez de contornado): o vendedor **salva qualquer preço** na
proposta; o item abaixo do piso entra como *"⏳ aguardando liberação"* e gera o
pedido automático. O negócio **só pode ser marcado como GANHO** quando todos os
itens estiverem liberados. O admin aprova (podendo ajustar o preço) ou nega.
Liberação é de **uso único** e vale 7 dias.

**Editar item do orçamento (v49):** mudar **só a quantidade** não encosta em
preço, aprovação nem liberação — o que foi liberado continua valendo. Mudar o
**preço** reavalia a trava: reaproveita a liberação que já cubra o novo preço ou
abre pedido novo, e cancela (status `cancelada`) um pendente que perdeu o
sentido. Aumentar a quantidade de item com liberação aprovada é **livre, mas fica
registrado no `audit_log`** com o valor adicional — decisão explícita do dono.

**Identidade do cliente:** CPF/CNPJ identifica a **empresa** (repetido bloqueia
sempre). WhatsApp identifica a **pessoa** — pode repetir dentro da própria
carteira; só bloqueia se já existir exclusivamente na carteira de outro vendedor.

**Carteira e sigilo:** vendedor só enxerga os próprios clientes, negócios e
números. Testado inclusive contra tentativa de burla por parâmetro
(`scope=all`). Transferência de carteira é auditada e preserva o histórico.

**Autonomia do vendedor (v45):** pode **reabrir** negócio ganho ou perdido (sai
da meta, histórico preservado) e **excluir** negócio criado por engano — mas só
se estiver **aberto e sem conversa registrada**. Isso impede maquiar resultado
apagando perdas. O admin pode excluir qualquer negócio.

**Recompra:** a âncora do próximo contato é **a data da última compra + o ciclo**,
não a data de hoje.

**O que a auditoria registra (v51/v52).** Um log que mente é pior que log nenhum,
então: só é gravado o que **de fato mudou**, no formato `antes → depois`; salvar
sem alterar nada não gera registro. Abrir a ficha de um cliente só é registrado
quando é **carteira de outra pessoa** (na prática, o admin abrindo cliente de um
vendedor) — registrar todo clique enchia a tabela de ruído. Senha nunca aparece,
apenas a marca de que foi redefinida. **Registros antigos nunca são apagados**:
um log que pode ser limpo não serve como prova.

---

## 6. HISTÓRICO DE FEATURES (v1 → v52, condensado)

**Base (v1–v24):** funil de vendas, carteira de clientes, alertas e triagem,
tarefas, histórico de negociação com anotações e prints, motivo de perda,
recompra programada, metas configuráveis com escopo por usuário, catálogo de
produtos, gestão/transferência de carteira, segurança (XSS, rate-limit),
modo produção + kit de VPS.

**v25–v31:** linha Instax · editar/excluir produtos do catálogo · última compra
com data real · **relatórios com drill-down** · **WhatsApp compartilhado** ·
âncora de recompra corrigida.

**Fase Base Comercial (v32–v37)** — integração da planilha Excel:
- v32: catálogo comercial completo, **frete por UF**, **condições de pagamento**,
  rota de importação `.xlsx` idempotente.
- v33/v34: **orçamento no negócio** (`deal_itens`) e também na **criação**.
- v35: busca digitada + **3 formas de pagamento fixas**.
- v36/v37: **liberações de preço** e a mudança da trava para o faturamento.

**v38–v45b (ajustes nascidos do uso real):**
- v39: desconto do admin como **margem** (v38 descartada).
- v40/v41: **contexto de equipamento na busca** + **selo colorido por linha**.
- v42/v43: **valor estimado preenchido pelos itens** + pagamento na criação.
- v44: **edição do negócio coerente**.
- v45/v45b: reabrir e excluir negócio; o `b` moveu o 🗑 porque era **inacessível**.

**Fase 3 (v46–v48):**
- v46: relatório **💸 Tabela vs. Limite por vendedor**.
- v47/v47b: relatório **📦 Vendas por Produto** + Kit sugerido pelo **histórico
  real de compras** do cliente.
- v48: o **Kit virou carrinho**, com o botão "🛒 Montar orçamento".

**Fase 4 (v49–v52) — a sessão de 23/07/2026:**
- **v49: editar quantidade e preço de item do orçamento.** Nova rota
  `PUT /api/deals/<id>/orcamento/itens/<item_id>` e botão ✏️ na linha. Resolveu a
  maior fricção diária: antes era preciso apagar e refazer o item, o que consumia
  a liberação de uso único. Primeira versão com `testes.py`.
- **v50: contador de liberações no menu** (badge no ◎ Metas, rota própria e
  enxuta que **não** dispara o motor de alertas) + dois defeitos de catálogo
  achados numa auditoria: produto sem preço vendia sem controle de margem, e o
  🗑 quebrava com **HTTP 500** em produto usado em orçamento (a checagem via
  `deals` e `metas`, mas não `deal_itens` nem `liberacoes_preco`).
- **v50b:** texto da confirmação de exclusão, que ficara desatualizado.
- **v51: auditoria visível.** Tela 🗂 Auditoria (admin, somente leitura) com
  filtros, busca e paginação. IDs resolvidos em nomes, inclusive os que ficam
  **dentro** dos detalhes — a transferência de carteira agora diz o nome de quem
  recebeu. A decisão de liberação passou a registrar produto, vendedor e preços.
- **v51b/v51c:** dinheiro exibido como moeda, rótulos acentuados, e a auditoria
  de leitura restrita a carteira alheia.
- **v52: auditoria registra o que mudou, não o que foi enviado.** Quatro rotas
  gravavam o corpo inteiro da requisição; agora um comparador guarda só os campos
  alterados, no formato `antes → depois`. Trata vazio/nulo e número/texto como
  equivalentes, **sem** converter números longos (WhatsApp, CNPJ) para float.

---

## 7. A PLANILHA (`Base_Comercial_Digimagem.xlsx`)

Fonte do catálogo. Abas: **Produtos** (a importação registra **74 itens**; o
documento antigo dizia 72), **Frete Grátis** (27 UFs, ex.: SP mínimo 3.000;
PB 5.000), **Pagamentos**, **Resumo**, **Análise Comercial**.

Detalhes que já causaram confusão: os papéis **15,2 × 186 m** são de
**minilab/Crystal Archive Type II**; os **15,2 × 65 m** são de
**inkjet/DX100 · DE100 · DE100XD · DX400**. A **ASK-300 está descontinuada**
("não ofertar").

**Importar:** admin → **◎ Metas → 📥 Importar planilha (.xlsx)**. É idempotente
(atualiza o que existe, cria o que falta) e **preserva os descontos configurados**.

---

## 8. PENDÊNCIAS (o que fazer a seguir)

### Prioridade média
1. **Botão "📍 Informar o estado" dentro do orçamento** — sem UF o frete grátis
   fica mudo, e o aviso *"Cliente sem UF cadastrada"* aparece o tempo todo na
   tela de orçamento. O usuário decidiu **não** tornar o campo obrigatório no
   cadastro; a ideia é resolver ali mesmo, sem sair da tela. *(Era a nº 9.)*
2. **Fechar os testes automatizados** — falta o cenário **meta contando
   unidades**. O resto já está coberto (94 + 48 verificações). *(Era a nº 5.)*
3. **Casar produto por ID na importação** — hoje casa por **nome**; renomear algo
   na planilha criaria um produto novo em vez de atualizar. **A suspeita de
   duplicatas existentes foi investigada em 23/07/2026 e NÃO se confirmou**:
   nenhum nome repetido, nem ignorando espaços e pontuação; 77 produtos = 74 da
   planilha + 3 manuais. Continua válida como prevenção, mas **caiu de
   prioridade**. *(Era a nº 4.)*

### Prioridade baixa / quando fizer sentido
4. **Exportar CSV** nos relatórios, no catálogo e **na auditoria**.
5. **Proposta com número e validade** ("válida até DD/MM") — cria urgência e
   rastreabilidade.
6. **Fase 5 — prospecção:** status "prospect", prioridade, mensagem sugerida,
   conversão de prospect em cliente.

### Fechadas na sessão de 23/07/2026
- ~~2º administrador~~ → Administrador 2 criado; Daniel promovido e revertido.
- ~~Editar quantidade de item do orçamento~~ → v49.
- ~~Contador de liberações pendentes no menu~~ → v50.
- ~~Auditoria visível~~ → v51/v51b/v51c/v52.

### Defeitos encontrados e corrigidos (não estavam em lista nenhuma)
- Produto sem preço de tabela vendia **sem controle de margem** (v50).
- 🗑 de produto usado em orçamento devolvia **HTTP 500** (v50).
- Auditoria registrava **"alterou" sem alteração** e não dizia o que mudou (v52).
- Auditoria gravava **um registro por clique** em ficha de cliente (v51c).

### Três itens Instax desativados
`Filme Instax`, `Camera + Filme Instax` e `Instax` eram entradas manuais da fase
v25–v31, **sem preço**, que a planilha depois substituiu. Nunca foram usados em
orçamento algum e foram **desativados** em 23/07/2026. Se aparecerem em algum
relatório antigo, é isso.

---

## 9. OBSERVAÇÃO IMPORTANTE SOBRE OS RELATÓRIOS

Os relatórios da Fase 3 e o Kit sugerido se alimentam dos **itens de orçamento**,
que só existem desde a Fase 2. **Negócios antigos, registrados apenas com valor
total, não aparecem neles** — um cliente antigo pode ter o kit vazio. Isso é
esperado, não é defeito: a base enriquece conforme a equipe fecha negócios usando
o orçamento.

O mesmo vale para a **auditoria**: ela mostra desde sempre, mas os registros
anteriores à v52 seguem o formato antigo (corpo da requisição inteiro, e um
"consultou" por clique). Não foram apagados de propósito.

---

## 10. DOCUMENTOS JÁ PRODUZIDOS (podem ser recriados se necessário)

- `CRM-Digimagem-Sistema-Completo.md` — tudo que o sistema faz, por papel de usuário
- `CRM-Digimagem-Auditoria-v44.md` — auditoria técnica/UX com os 10 pontos priorizados
- `CRM-Digimagem-Analise-Atualizacao.md` — análise de custo/benefício da Base Comercial
- `PLANO-DE-RESTAURACAO.md` — como voltar código e/ou banco em caso de problema
