# CRM-Digimagem — Especificação Técnica de Relatórios Gerenciais
*(Adaptação do prompt de consultoria B2B para o schema real do sistema — 100% local, sem custo de API externa)*

## Decisões de adaptação (leia antes do resto)

O prompt original foi pensado para um CRM B2B genérico com um funil de 5 etapas e
campos que o nosso banco ainda não tinha. Para não estourar escopo nem gerar custo,
tomei estas decisões:

| Pedido no prompt | Decisão | Motivo |
|---|---|---|
| Funil de 5 etapas (Prospecção, Qualificação, Diagnóstico, Proposta, Negociação) | **Mantive as 4 etapas atuais** (Novo Lead, Qualificação, Proposta Enviada, Negociação) | Mudar o funil quebraria o motor de alertas, o Assistente de Vendas e todo o kanban já em uso. Redesenhar o funil não foi pedido nesta conversa — se você quiser, dá pra fazer depois como tarefa separada. |
| Motivo de perda (Loss Analysis) | **Adicionei campo `motivo_perda`** no negócio, preenchido obrigatoriamente ao marcar "perdido" | Não existia forma de capturar isso. Custo zero: é só uma coluna de texto + uma lista fixa de opções na interface. |
| Atividades comerciais (reunião, proposta enviada, follow-up) | **Adicionei campo `tipo_atividade`** nos compromissos (tasks) | O sistema só tinha "descrição livre". Sem classificar o tipo, não dá pra contar "quantas reuniões" ou "quantos follow-ups". Custo zero: mesmo padrão dos campos que já existem. |
| Forecast por "data estimada de fechamento" | **Adicionei campo `data_prevista_fechamento`** no negócio | Não existia. É opcional — se o vendedor não preencher, o negócio simplesmente não entra no relatório de Forecast (não trava nada). |
| Histórico de transição de etapa (para calcular corretamente quando um negócio *entrou* em cada etapa) | **Criei a tabela `deal_stage_history`** | Sem isso, só sabemos a etapa *atual* do negócio, não quando ele passou por cada uma. Isso é essencial pros relatórios de Ciclo de Venda e Atividades. Custo zero: é só uma tabela extra gravando 1 linha a cada troca de etapa. |
| Origem do lead (Outbound, LinkedIn, Indicações, Eventos, Inbound) | **Reaproveitei o campo `origem`** que já existia no cliente, e travei a interface numa lista fixa de opções | Já existia como texto livre; só precisava virar lista fechada pra dar pra agrupar no relatório. |
| Qualquer sugestão de IA generativa, API paga ou serviço de terceiros para os relatórios | **Descartado.** Todos os 6 relatórios são cálculos SQL diretos sobre o próprio banco | Você já pediu antes que nada gerasse custo — isso vale pra relatórios também. |

## Regra de visibilidade (vale para os 6 relatórios)

- **Vendedor**: só vê o próprio relatório. Não existe parâmetro que permita ver dados de
  outro vendedor ou de um admin — a API recusa com 403 se tentar.
- **Administrador**: por padrão vê o próprio relatório (mesma UX de "meus dados" já usada
  em Clientes/Negócios). Pode escolher **um vendedor específico** num seletor, ou marcar
  **"Toda a equipe"** para ver o consolidado de todo mundo, incluindo outros admins.

---

## Filtros de período (regra única para os 6 relatórios)

A interface segue exatamente as 4 opções pedidas. Por trás, existe **uma única função
de resolução de período** no backend (`resolve_period`) que todos os relatórios chamam
— isso evita duplicar lógica de data em 6 lugares diferentes.

### Como cada opção é calculada

- **Quinzenal**: dia 1–15 ou dia 16–fim do mês. A quinzena atual é calculada a partir da
  data de hoje. Navegação anterior/seguinte desloca em blocos de 15 dias (meio mês).
- **Mensal**: do dia 1 ao último dia do mês corrente (ou navegado).
- **Trimestral**: Q1 (jan–mar), Q2 (abr–jun), Q3 (jul–set), Q4 (out–dez), sempre por
  ano civil (mês de fechamento fiscal = mês civil, já que não há configuração de ano
  fiscal customizado no sistema).
- **Personalizado**: `data_inicio` e `data_fim` informados livremente pelo usuário.

### Navegação por deslocamento (offset)

Em vez de cada relatório calcular "período anterior" na mão, uso um único parâmetro
inteiro `offset`:
- `offset=0` → período atual
- `offset=-1` → período anterior
- `offset=1` → período seguinte

Isso converte quinzena/mês/trimestre num "índice contínuo" (ex: quinzena vira
`ano*24 + mes*2 + quinzena`), soma o offset, e converte de volta pra datas. Um único
algoritmo cobre as 3 opções fixas; o "personalizado" ignora o offset e usa as datas
informadas diretamente.

### Performance: como isso não pesa no banco

1. **Datas armazenadas como texto ISO (`YYYY-MM-DD` ou `YYYY-MM-DD HH:MM:SS`)** —
   formato que o SQLite compara *lexicograficamente* na ordem certa, então
   `WHERE data BETWEEN ? AND ?` funciona como comparação normal, sem função de
   conversão nem `strftime()` na cláusula `WHERE` (que impediria o uso de índice).
2. **Nunca aplicar função na coluna filtrada.** Errado: `WHERE strftime('%Y-%m', data) = '2026-07'`
   (obriga varrer a tabela inteira). Certo: `WHERE data >= '2026-07-01' AND data < '2026-08-01'`
   (usa índice normalmente).
3. **Índices nas colunas de data mais consultadas**: já adicionei índices em
   `deals.etapa_atualizada_em`, `deal_stage_history.data_transicao`, `tasks.data_lembrete`
   e `customers.created_at` — são exatamente as colunas que os 6 relatórios filtram.
4. **Escala do problema**: é um CRM de uma equipe pequena/média (dezenas a poucas
   centenas de negócios por mês). Nesse volume, SQLite com índice responde em
   milissegundos — não há necessidade de cache, view materializada ou banco separado
   para relatórios.

---

## 1. Relatório de Funil de Vendas (Pipeline)

**Objetivo:** mostrar volume financeiro e quantidade de negócios abertos em cada etapa,
para enxergar onde o funil está "engordando" ou "afinando".

**Métricas:**
- `valor_total_etapa` = `SUM(valor_estimado)` dos negócios abertos naquela etapa
- `quantidade_etapa` = `COUNT(*)` dos negócios abertos naquela etapa
- `ticket_medio_etapa` = `valor_total_etapa / quantidade_etapa`

**Tabelas/campos:** `deals` (`etapa_funil`, `valor_estimado`, `status`, `created_at`,
`etapa_atualizada_em`), `customers` (para nome, se o admin quiser detalhar).

**Como o filtro de período afeta a query:** o usuário escolhe se quer ver o funil pela
**data de criação** (`created_at`) ou pela **data prevista de fechamento**
(`data_prevista_fechamento`). A query aplica `WHERE data_escolhida BETWEEN inicio AND fim`
antes de agrupar por etapa. Se nenhuma das duas datas for escolhida, o relatório mostra
a **foto atual** do funil (sem filtro de data, só `status = 'aberto'`), que é o modo
mais comum de uso desse relatório no dia a dia.

---

## 2. Relatório de Desempenho da Equipe

**Objetivo:** taxa de conversão e ciclo médio de venda por vendedor.

**Métricas:**
- `taxa_conversao` = `negocios_ganhos / (negocios_ganhos + negocios_perdidos)` no período
- `ciclo_medio_dias` = média de `(data_fechamento - deals.created_at)` em dias, só dos
  negócios **ganhos** no período
- `valor_ganho_total`, `valor_perdido_total`, `ticket_medio_ganho`

**Tabelas/campos:** `deals` (`user_id`, `status`, `created_at`, `etapa_atualizada_em`
como proxy de `data_fechamento`, `valor_estimado`), `users` (nome do vendedor).

**Como o filtro de período afeta a query:** filtra por **data de fechamento**
(`etapa_atualizada_em` nos negócios com `status IN ('ganho','perdido')`) — é a única
opção que faz sentido aqui, exatamente como pedido no prompt original.

---

## 3. Relatório de Motivos de Perda

**Objetivo:** identificar os principais motivos de negócios perdidos.

**Métricas:**
- `quantidade_por_motivo` = `COUNT(*) GROUP BY motivo_perda`
- `valor_perdido_por_motivo` = `SUM(valor_estimado) GROUP BY motivo_perda`
- `percentual_por_motivo` = `quantidade_por_motivo / total_perdidos`

**Tabelas/campos:** `deals` (`motivo_perda`, `motivo_perda_detalhe`, `valor_estimado`,
`etapa_atualizada_em` como data da perda).

**Lista fixa de motivos** (definida na interface, sem digitação livre pra manter o
relatório agrupável): `Preço`, `Concorrente`, `Falta de funcionalidade/serviço`,
`Sumiu/não respondeu (no-show)`, `Sem orçamento`, `Timing errado`, `Outro` (com campo
de detalhe livre só para esse último).

**Como o filtro de período afeta a query:** filtra por **data em que o negócio foi
marcado como perdido** (`etapa_atualizada_em` onde `status = 'perdido'`).

---

## 4. Relatório de Atividades Comerciais

**Objetivo:** produtividade da equipe em atividades de venda (reuniões, propostas,
follow-ups), não só resultado financeiro.

**Métricas:**
- `reunioes_agendadas` = `COUNT(tasks)` com `tipo_atividade = 'reuniao'` criadas no período
- `reunioes_realizadas` = idem, mas com `executado = 1` e `executado_em` no período
- `propostas_enviadas` = `COUNT(deal_stage_history)` com `etapa_nova = 'proposta_enviada'`
  no período (conta cada vez que um negócio *entrou* nessa etapa, mesmo que tenha
  voltado atrás e entrado de novo)
- `follow_ups_realizados` = `COUNT(tasks)` com `tipo_atividade = 'follow_up'` e
  `executado = 1` no período

**Tabelas/campos:** `tasks` (`tipo_atividade` — campo novo, `executado`, `executado_em`,
`created_at`, `user_id`), `deal_stage_history` (`etapa_nova`, `data_transicao`, `user_id`).

**Como o filtro de período afeta a query:** filtra por **data de realização da
atividade** — `executado_em` para tarefas concluídas, `data_transicao` para as entradas
de etapa (propostas).

---

## 5. Relatório de Previsão de Vendas (Forecast)

**Objetivo:** projetar quanto deve fechar num período, ponderando valor pela
probabilidade da etapa atual.

**Métricas:**
- `valor_ponderado` = `SUM(valor_estimado * probabilidade_etapa)` dos negócios abertos
  com `data_prevista_fechamento` dentro do período escolhido
- `probabilidade_etapa` (mesma lógica de peso já usada no Assistente de Vendas):
  Novo Lead = 15%, Qualificação = 35%, Proposta Enviada = 55%, Negociação = 75%
- `valor_bruto_total` = `SUM(valor_estimado)` sem ponderar (visão otimista)

**Tabelas/campos:** `deals` (`valor_estimado`, `etapa_funil`, `data_prevista_fechamento`,
`status = 'aberto'`).

**Como o filtro de período afeta a query:** filtra **estritamente** por
`data_prevista_fechamento BETWEEN inicio AND fim`, exatamente como pedido. Negócios sem
essa data preenchida não entram no relatório (ficam de fora do forecast, mas continuam
aparecendo normalmente no funil).

---

## 6. Relatório de Origem de Leads

**Objetivo:** identificar quais canais trazem negócios de maior valor.

**Métricas:**
- `quantidade_clientes_por_origem` = `COUNT(customers) GROUP BY origem`
- `valor_total_ganho_por_origem` = `SUM(deals.valor_estimado)` dos negócios **ganhos**,
  agrupado pela origem do cliente
- `ticket_medio_por_origem` = `valor_total_ganho_por_origem / quantidade_negocios_ganhos_por_origem`

**Tabelas/campos:** `customers` (`origem`, `created_at`), `deals` (`valor_estimado`,
`status`, `customer_id`).

**Lista fixa de canais:** `Outbound`, `LinkedIn`, `Indicações`, `Eventos`, `Inbound`,
`Outro`.

**Como o filtro de período afeta a query:** filtra por **data de entrada do lead**
(`customers.created_at BETWEEN inicio AND fim`), exatamente como pedido.
