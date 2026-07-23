# 📋 CRM-DIGIMAGEM — Contexto do projeto (handoff para novo chat)

> **Como usar:** anexe este arquivo na primeira mensagem do chat novo e diga algo
> como *"Este é o contexto do meu projeto, leia antes de começarmos"*.
> Anexe também o **último .zip do sistema** (`crm-digimagem-v48.zip`) e a planilha
> **`Base_Comercial_Digimagem.xlsx`**, que são usados o tempo todo.

*Atualizado em 23/07/2026 · versão atual: **v48** · produção no ar*

---

## 1. O QUE É O SISTEMA

CRM de vendas da **Digimagem**, loja que vende equipamentos e insumos fotográficos
(impressoras Fujifilm, papéis, cartuchos, químicos, linha Instax). Usado pelo
dono (admin) e por 4 vendedores. Interface em **português do Brasil**.

**Stack:** Flask (Python) + SQLite + frontend single-file (`static/dashboard.html`,
HTML/CSS/JS puro, sem framework). Tema escuro.

**Tamanho atual:** `app.py` ~4.180 linhas · `dashboard.html` ~4.050 linhas ·
`schema.sql` 351 linhas · 21 tabelas · 75 rotas.

**Arquivos do projeto:** `app.py`, `schema.sql`, `static/dashboard.html`,
`requirements.txt` (Flask, Werkzeug, itsdangerous, gunicorn==22.0.0,
**openpyxl==3.1.5**), `Procfile`, pasta `vps/` (setup_vps.sh, deploy.sh,
backup.sh, GUIA-VPS.md), README.md.

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

- **Produção (VPS):** Administrador `admin@digimagem.com` (admin) · Carlos Roberto
  `carlos.vendas@lojadigimagem.com.br` · Ana `ana@lojadigimagem.com.br` ·
  Tiago `tiago@lojadigimagem.com.br` · Daniel `digimagemsc@hotmail.com`
  (todos vendedores).
- **Render (demo):** `admin1@digimagem.com` / `admin123` ·
  `ana@lojadigimagem.com.br` / `vendas123` (e os demais vendedores com `vendas123`).

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
   sufixo `b` (ex.: v45b, v47b).
5. **Antes de empacotar:** validar `python3 -m py_compile app.py` e extrair os
   `<script>` do HTML para rodar `node --check`.
6. **O usuário quer honestidade**, não concordância. Ele pediu explicitamente:
   *"quero que seja verdadeiro e não me responda somente para me agradar"*.
   Discordar com fundamento é bem-vindo — várias decisões boas do projeto vieram
   de discordâncias explicadas.

### Armadilhas do ambiente de trabalho do Claude

- A pasta `/home/claude/crm-digimagem-app` **some entre turnos**. Para restaurar:
  `cd /home/claude && rm -rf crm-digimagem-app && unzip -q /mnt/user-data/outputs/crm-digimagem-vXX.zip`
  — **sempre apagar antes de reextrair**, senão fica uma versão misturada.
- O servidor Flask em background (`nohup ... &`) **frequentemente não persiste**
  entre comandos bash. Quando isso travar o teste, a saída é **testar a lógica
  direto no SQLite**, importando o app em Python
  (`os.environ["CRM_DB_PATH"]=...; import app; app.init_db_if_needed()`), sem HTTP.
  Para lógica de frontend, extrair as funções e rodar no `node` com um DOM falso.

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

**A trava está no faturamento, não na proposta** (decisão da v37, e é a que faz
o sistema ser usado em vez de contornado): o vendedor **salva qualquer preço** na
proposta; o item abaixo do piso entra como *"⏳ aguardando liberação"* e gera o
pedido automático. O negócio **só pode ser marcado como GANHO** quando todos os
itens estiverem liberados. O admin aprova (podendo ajustar o preço) ou nega.
Liberação é de **uso único** e vale 7 dias.

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

---

## 6. HISTÓRICO DE FEATURES (v1 → v48, condensado)

**Base (v1–v24):** funil de vendas, carteira de clientes, alertas e triagem,
tarefas, histórico de negociação com anotações e prints, motivo de perda,
recompra programada, metas configuráveis com escopo por usuário, catálogo de
produtos, gestão/transferência de carteira, segurança (XSS, rate-limit),
modo produção + kit de VPS.

**v25–v31:** linha Instax · editar/excluir produtos do catálogo · última compra
com data real · **relatórios com drill-down** (lista negócio a negócio) ·
**WhatsApp compartilhado** (semântica CPF/CNPJ × WhatsApp descrita acima) ·
âncora de recompra corrigida.

**Fase Base Comercial (v32–v37)** — integração da planilha Excel:
- v32: catálogo comercial completo (categoria, equipamento, embalagem, preço
  tabela, preço-limite, desconto máx, status), tabelas de **frete por UF** e
  **condições de pagamento**, rota de importação `.xlsx` idempotente.
- v33/v34: **orçamento no negócio** (tabela `deal_itens`), com subtotal,
  acréscimo de cartão, frete grátis pela UF, proposta; e o orçamento também na
  **criação** do negócio (atômica).
- v35: busca digitada + **3 formas de pagamento fixas** (PIX/TED à vista;
  Cartão até 10x com 2%; Boleto conforme o valor).
- v36/v37: **liberações de preço** (pedido, aprovação/negação, auditoria) e a
  mudança da trava para o faturamento.

**v38–v45b (ajustes nascidos do uso real):**
- v39: desconto do admin como **margem** (v38 foi descartada, não publicada).
- v40/v41: **contexto de equipamento na busca** + **selo colorido por linha**
  (âmbar = minilab/Crystal Archive; ciano = inkjet DX100/DE100/DE100XD/DX400;
  violeta = térmica/ASK; verde = Instax). Nasceu do problema real de confundir os
  quatro papéis "15,2".
- v42/v43: **valor estimado preenchido pelos itens** (e o marco do histórico
  deixando de nascer R$ 0,00) + **forma de pagamento na criação** com cálculo
  do acréscimo.
- v44: **edição do negócio coerente** — resumo do orçamento na tela, campo de
  pagamento, valor travado quando há itens, remoção de campo obsoleto.
- v45/v45b: reabrir negócio ganho e excluir negócio criado por engano (regras na
  seção 5). O `b` moveu o botão 🗑 para o **cartão do funil** e o modal de
  histórico, porque na tabela onde estava ele era **inacessível na prática**.

**Fase 3 (v46–v48) — concluída:**
- v46: relatório **💸 Tabela vs. Limite por vendedor** — faturamento na tabela ×
  praticado, desconto em R$ e %, itens no preço cheio, itens que exigiram
  liberação. Ordenado por maior % de desconto.
- v47: relatório **📦 Vendas por Produto** (quantidade e faturamento por produto
  e por linha) + primeira versão do Kit sugerido.
- v47b: **correção de conceito do Kit** — a primeira versão listava todo o
  catálogo compatível com o equipamento (30+ itens que o cliente nunca comprou).
  Refeito para usar o **histórico real de compras** do cliente: o que ele compra,
  quantidade média por pedido, quantas vezes comprou, data da última compra, e
  marcação de produto descontinuado.
- v48: o **Kit virou carrinho** — seleção por item, quantidade editável, total
  estimado, e o botão **"🛒 Montar orçamento com os selecionados"**, que abre o
  "Novo negócio" já com os itens carregados (reaproveitando todo o fluxo:
  preço vigente, trava de liberação, pagamento, frete).

---

## 7. A PLANILHA (`Base_Comercial_Digimagem.xlsx`)

Fonte do catálogo. Abas: **Produtos** (72 itens: ID, Categoria, Linha/equipamento,
Descrição, Qtd. ref., Embalagem, Preço tabela, Preço-limite, Desconto máx.,
Validação), **Frete Grátis** (27 UFs, ex.: SP mínimo 3.000; PB 5.000),
**Pagamentos**, **Resumo**, **Análise Comercial**.

Detalhes que já causaram confusão: os papéis **15,2 × 186 m** são de
**minilab/Crystal Archive Type II**; os **15,2 × 65 m** são de
**inkjet/DX100 · DE100 · DE100XD · DX400**. A **ASK-300 está descontinuada**
("não ofertar").

**Importar:** admin → **◎ Metas → 📥 Importar planilha (.xlsx)**. É idempotente
(atualiza o que existe, cria o que falta) e **preserva os descontos configurados**.

---

## 8. PENDÊNCIAS (o que fazer a seguir)

### Prioridade alta (recomendadas antes de features novas)
1. **Criar um 2º administrador** — hoje só existe um admin; se ele perder o
   acesso, é preciso SSH. Rede de segurança barata: **Equipe → + Novo usuário**,
   papel administrador.
2. **Editar a quantidade de um item do orçamento** — hoje só existe adicionar e
   excluir. Errou a quantidade? Apaga e refaz — e se o preço tinha liberação
   aprovada, **ela já foi consumida** (uso único) e precisa ser pedida de novo.
   É a maior fricção diária do sistema.

### Prioridade média
3. **Contador de liberações pendentes no menu** (ex.: "🙋 Liberações **2**") —
   hoje o pedido só aparece dentro do sistema e pode ficar horas parado, travando
   uma venda.
4. **Casar produto por ID na importação** — hoje casa por **nome**; renomear algo
   na planilha cria um produto novo em vez de atualizar (suspeita de duplicatas
   já existentes, ex.: papel 15,2 × 65 m). A planilha tem coluna ID, hoje não
   usada para isso. Vale também uma tela de "possíveis duplicados".
5. **Testes automatizados no repositório** (`testes.py` com os cenários críticos:
   login, criar negócio com itens, trava de preço, liberação, faturamento
   bloqueado, meta contando unidades).

### Prioridade baixa / quando fizer sentido
6. **Auditoria visível** — a tabela `audit_log` registra tudo, mas **não existe
   tela** para consultar; só via SSH e SQL.
7. **Exportar CSV** nos relatórios e no catálogo.
8. **Proposta com número e validade** ("válida até DD/MM") — cria urgência e
   rastreabilidade.
9. **Campo Estado (UF) no cadastro** — sem UF, a regra de frete grátis fica muda.
   O usuário decidiu **não** torná-lo obrigatório; a ideia pendente é um botão
   "📍 Informar o estado" dentro do orçamento.
10. **Fase 4 — prospecção:** status "prospect", prioridade, mensagem sugerida,
    conversão de prospect em cliente.

---

## 9. OBSERVAÇÃO IMPORTANTE SOBRE OS RELATÓRIOS NOVOS

Os relatórios da Fase 3 e o Kit sugerido se alimentam dos **itens de orçamento**,
que só existem desde a Fase 2. **Negócios antigos, registrados apenas com valor
total, não aparecem neles** — um cliente antigo pode ter o kit vazio. Isso é
esperado, não é defeito: a base enriquece conforme a equipe fecha negócios usando
o orçamento.

---

## 10. DOCUMENTOS JÁ PRODUZIDOS (podem ser recriados se necessário)

- `CRM-Digimagem-Sistema-Completo.md` — tudo que o sistema faz, por papel de usuário
- `CRM-Digimagem-Auditoria-v44.md` — auditoria técnica/UX com os 10 pontos priorizados
- `CRM-Digimagem-Analise-Atualizacao.md` — análise de custo/benefício da Base Comercial
- `PLANO-DE-RESTAURACAO.md` — como voltar código e/ou banco em caso de problema
