# CRM-Digimagem — Aplicação Funcional (Backend + Banco + Frontend)

Este é o sistema **rodando de verdade**, não um mockup: API real em Flask, banco SQLite
persistente, autenticação com token, RBAC (admin vs vendedor) e o motor de alertas
executando as regras de negócio de fato sobre os dados.

> O WhatsApp aqui é só canal de **envio**: o app nunca lê nem armazena conversas.
> A tabela `whatsapp_notification_channels` existe para no futuro conectar a Evolution
> API / WhatsApp Cloud API e disparar o texto dos alertas — hoje o botão "Abrir conversa"
> apenas abre `wa.me/<numero>` no navegador.

## Como rodar

Requer só Python 3 (o Flask já costuma vir instalado; se não vier, é um único pacote):

```bash
pip install flask --break-system-packages   # pule se já tiver o Flask
cd crm-digimagem-app
python3 app.py
```

Acesse **http://localhost:5000**. Na primeira execução o banco `crm.db` é criado e
populado automaticamente com dados de exemplo (2 admins, 2 vendedores, 6 clientes,
6 negócios no funil, 2 compromissos — um deles já vencido de propósito, para você ver
o alerta de "compromisso esquecido" nascer sozinho).

## Logins de teste

| Papel | Email | Senha |
|---|---|---|
| Admin Master 1 | admin1@digimagem.com | admin123 |
| Admin Master 2 | admin2@digimagem.com | admin123 |
| Vendedor | carlos.vendas@lojadigimagem.com.br | vendas123 |
| Vendedora | ana@lojadigimagem.com.br | vendas123 |
| Vendedor | tiago@lojadigimagem.com.br | vendas123 |

Troque essas senhas antes de usar com dados reais — é só criar novos usuários pela
rota `/api/users` (só admin) e desativar os de exemplo.

## O que já funciona de ponta a ponta

- **Login com token** (assinado com `itsdangerous`, expira em 7 dias).
- **RBAC real**: vendedor só enxerga clientes/negócios/tarefas onde ele é o responsável;
  admin por padrão também vê só "os dele", e só enxerga tudo com o toggle
  "ver todos os vendedores" (`?scope=all`) — reproduzido no frontend.
- **Motor de alertas rodando de verdade** a cada chamada ao dashboard, gerando:
  - `inatividade` — cliente recorrente/VIP sem comprar há mais de 30 dias;
  - `abandono_funil` — negócio parado mais de 48h na mesma etapa;
  - `compromisso_esquecido` — tarefa vencida e não concluída (e escalona para os
    admins se passar de 24h vencida);
  - `sugestao_conteudo` — sugestão de fidelização para clientes VIP.
- **Proteção dos 2 admins**: a API bloqueia (HTTP 409) se você tentar desativar um
  admin e isso deixar o sistema com menos de 2 admins ativos.
- **Log de auditoria** (`audit_log`) registrando leituras/alterações feitas pelos usuários.
- **Frontend real**: tela de login, feed de alertas clicável, kanban do funil, painel do
  cliente com tarefas e alertas — tudo consumindo a API via `fetch`, sem dado mockado.
- **Criação e edição de dados pelo próprio painel** (sem precisar mexer no banco):
  - "+ Novo cliente" na barra superior, com cadastro completo (CPF/CNPJ, endereço,
    CEP, cidade, estado, WhatsApp, telefone, email);
  - botão **"Editar cliente"** dentro do painel do cliente e na lista de Clientes —
    dá pra atualizar qualquer dado cadastral a qualquer momento;
  - **Desativar/Reativar cliente**: arquiva o cliente sem apagar nada — ele some das
    listas ativas e para de gerar alertas automáticos, mas todo o histórico (negócios,
    compromissos, alertas antigos) continua acessível. Na tela Clientes, a checkbox
    "mostrar inativos" traz esses clientes arquivados de volta pra visualização;
  - **Excluir cliente**: apaga o cliente e tudo que está diretamente ligado a ele —
    negócios, compromissos e alertas somem junto (é preciso digitar "EXCLUIR" para
    confirmar, pois não tem como desfazer). Tarefas delegadas da equipe que citavam
    esse cliente **não são apagadas**, só perdem esse vínculo;
  - dentro do painel do cliente: "+ Novo negócio" e "+ Novo compromisso";
  - view **Negócios**: funil com controle de etapa direto no card (dropdown + botões
    "marcar ganho"/"marcar perdido"), mais a lista de negócios já fechados;
  - view **Tarefas**: todos os compromissos (vencidos e futuros) de todos os seus
    clientes, com "+ Novo compromisso" avulso (escolhendo o cliente na hora);
  - view **Clientes**: lista completa com criação rápida;
  - view **Equipe** (só admin): criar vendedores/admins, **editar dados de qualquer
    usuário** (nome, email, papel, status, resetar senha) e desativar usuários —
    respeitando sempre a trava de mínimo 2 admins ativos;
  - view **Tarefas da Equipe**: o admin delega uma tarefa para **um vendedor específico**
    ou para **toda a equipe** de uma vez (escolhendo "👥 Toda a equipe" no lugar de uma
    pessoa) — nesse caso, cada vendedor ativo recebe sua própria cópia da tarefa,
    identificada com a etiqueta "👥 equipe", e conduz o fluxo de forma independente:
    **Aberta → Em andamento → Finalizada**, escrevendo uma breve descrição do que foi
    feito ao concluir. Um vendedor concluir a própria cópia não afeta a dos colegas.
    Cada um só mexe nas próprias tarefas atribuídas; o admin vê e acompanha todas;
  - view **Notificações WhatsApp**: cadastro do(s) número(s) que recebem os alertas
    (canal de envio apenas — o sistema não lê conversas).

## ✦ Assistente de Vendas (IA local — 100% gratuito, sem API paga)

Existe uma view "Assistente de Vendas" no menu lateral. Ela roda um **motor de regras
local**, direto sobre os dados do seu próprio banco — não faz nenhuma chamada a serviço
externo, não usa nenhuma API paga, não tem custo nenhum, hoje ou depois.

Para cada negócio aberto, ele calcula um placar de 0 a 100 e monta um checklist do que
fazer para não perder a venda, olhando:
- quanto tempo o negócio está parado na etapa atual (mais de 48h já é sinal de alerta);
- se existe compromisso vencido sem resolver com aquele cliente;
- se não há nenhum follow-up agendado (negócio "esquecido");
- se é um lead novo há mais de 24h sem qualificação;
- se o cliente é VIP (sugestão de diferencial para acelerar);
- se o ticket é alto (sugestão de conversa por ligação/vídeo em vez de só texto).

A tela mostra os negócios "prontos para fechar" (score alto) e os "em risco" (score
baixo), além de uma lista de boas práticas gerais de vendas. Tudo isso é lógica de
regras (`if`/`else` no `app.py`, função `build_deal_recommendation`) — não é um modelo
de linguagem. Se um dia você quiser evoluir para uma IA generativa de verdade, dá pra
plugar por cima dessa mesma função, mas isso sempre vai ser uma decisão sua, nunca algo
ativado por padrão.

## Visibilidade por papel (admin vs vendedor)

- Vendedores **não veem** os menus "Equipe" e o botão "+ Nova tarefa delegada" —
  eles somem da tela para quem não é admin (tanto no menu quanto tentando abrir
  via console do navegador: a tela e o modal ficam bloqueados no próprio frontend,
  além de o backend recusar a chamada com HTTP 403).
- **Isolamento total de dados entre vendedores**: nenhum vendedor consegue ver, editar,
  mover etapa, concluir tarefa ou criar negócio/compromisso em cima de cliente que não
  é dele — mesmo sabendo o ID exato do registro, a API recusa com 403. Isso vale para
  todas as ações (ver cliente, mover negócio no funil, concluir compromisso, marcar
  alerta como lido, criar negócio/tarefa vinculado a cliente alheio). Só o administrador,
  usando o toggle "ver todos os vendedores", enxerga e consegue agir sobre os dados de
  todo mundo.
- O que o vendedor **consegue fazer normalmente**: gerenciar seus próprios clientes,
  negócios, compromissos, ver seus alertas, usar o Assistente de Vendas, e — o que o
  administrador pede pra ele — **conduzir o fluxo das tarefas que foram delegadas**
  (Iniciar → Concluir, com a descrição do que foi feito). Um vendedor só enxerga e só
  consegue mexer nas tarefas atribuídas a ele; nunca nas de outro vendedor.
- **Identificação do vendedor no modo "ver todos"**: quando o admin liga o toggle
  "ver todos os vendedores", cada alerta, card do funil, tarefa e negócio fechado
  ganha uma etiqueta com o nome do vendedor responsável — assim dá pra saber de quem
  é cada coisa sem precisar adivinhar. As listas de Clientes e Negócios Fechados também
  ganham uma coluna "Responsável"/"Vendedor" nesse modo (some de novo quando o toggle
  é desligado, pra não poluir a tela com o próprio nome repetido).

## 📊 Relatórios Gerenciais (visibilidade por papel, sem custo de API)

Existe uma view "Relatórios" no menu lateral, visível para todos. A regra de
visibilidade é a que você pediu:
- **Vendedor**: só vê o próprio relatório. Não existe parâmetro na API que deixe ver
  o relatório de outro vendedor ou de um admin — a tentativa é ignorada silenciosamente
  no lugar de vazar dado (testado).
- **Administrador**: vê o próprio por padrão, pode escolher **um vendedor específico**
  no seletor do topo, ou **"👥 Toda a equipe"** para ver o consolidado de todo mundo
  (incluindo outros admins, se houver mais de um).

Os 6 relatórios (todos com filtro Quinzenal/Mensal/Trimestral/Personalizado, com
navegação `‹ ›` entre períodos anteriores/seguintes):
1. **Pipeline** — volume e quantidade de negócios por etapa do funil.
2. **Desempenho da Equipe** — taxa de conversão e ciclo médio de venda por vendedor.
3. **Motivos de Perda** — por que os negócios perdidos foram perdidos.
4. **Atividades Comerciais** — reuniões, propostas enviadas, follow-ups por vendedor.
5. **Forecast** — previsão de vendas ponderada pela probabilidade da etapa.
6. **Origem de Leads** — qual canal traz negócios de maior valor.

A especificação técnica completa (fórmulas, campos usados, e como cada filtro de
período afeta a query sem perder performance) está em `relatorios_especificacao.md`.
Esse arquivo também documenta o que foi adaptado do pedido original — nada de custo
extra: são 3 colunas novas em `deals`, 1 em `tasks`, e uma tabela de histórico de
etapa, todas gratuitas e locais.

## Estrutura

```
crm-digimagem-app/
├── app.py                        # backend Flask: rotas, auth, RBAC, motor de alertas, relatórios, seed
├── schema.sql                    # schema SQLite
├── relatorios_especificacao.md   # especificação técnica dos 6 relatórios (fórmulas, campos, filtros)
├── static/
│   └── dashboard.html            # frontend (login + painel), conversa com a API via fetch
└── crm.db                        # criado automaticamente na primeira execução
```

## Próximos passos reais para produção

1. Trocar SQLite por PostgreSQL (o `schema.sql` da primeira entrega já está pronto
   para isso — os tipos/enum são equivalentes).
2. Trocar o servidor de desenvolvimento do Flask por Gunicorn/uWSGI atrás de um Nginx.
3. Conectar `whatsapp_notification_channels` a uma instância real da Evolution API ou
   da WhatsApp Cloud API para os alertas saírem de fato como mensagem, e não só no painel.
4. Mover o `SECRET_KEY` do `app.py` para variável de ambiente.
5. Rodar o motor de alertas também em um cron/worker separado (hoje ele roda "on demand"
   a cada carregamento do dashboard, o que já é automático e correto para o uso diário,
   mas um job periódico garante alertas mesmo com o painel fechado).
