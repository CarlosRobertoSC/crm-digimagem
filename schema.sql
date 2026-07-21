-- =========================================================
-- CRM-DIGIMAGEM — SCHEMA SQLITE (versão executável do schema.sql/Postgres)
-- Gestão de vendas e retenção, com alertas automáticos via WhatsApp.
-- O sistema NÃO lê nem armazena conteúdo de conversas do WhatsApp.
-- =========================================================

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    nome            TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    senha_hash      TEXT NOT NULL,
    role            TEXT NOT NULL CHECK(role IN ('admin','vendedor')) DEFAULT 'vendedor',
    ativo           INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS customers (
    id                  TEXT PRIMARY KEY,
    nome                TEXT NOT NULL,
    whatsapp_id         TEXT,  -- identifica a PESSOA (pode ter várias empresas)
    telefone            TEXT,
    email               TEXT,
    cpf_cnpj            TEXT,
    endereco            TEXT,
    cep                 TEXT,
    cidade              TEXT,
    estado              TEXT,
    ativo               INTEGER NOT NULL DEFAULT 1,
    data_ultima_compra  TEXT,
    status_fidelidade   TEXT NOT NULL CHECK(status_fidelidade IN ('novo','recorrente','vip','inativo','perdido')) DEFAULT 'novo',
    recompra_dias       INTEGER,  -- 🔁 ciclo de recompra em dias (NULL = desativado)
    proxima_recompra    TEXT,     -- data agendada do próximo contato (YYYY-MM-DD)
    equipamentos        TEXT,     -- 🖨 JSON: equipamentos Fujifilm do cliente
    rolos_mes_media     INTEGER,  -- 📦 média mensal de rolos de papel (precificação)
    responsavel_id      TEXT REFERENCES users(id) ON DELETE SET NULL,
    origem              TEXT,
    observacoes         TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deals (
    id                       TEXT PRIMARY KEY,
    customer_id              TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    user_id                  TEXT NOT NULL REFERENCES users(id),
    titulo                   TEXT NOT NULL,
    etapa_funil              TEXT NOT NULL CHECK(etapa_funil IN
                              ('novo_lead','qualificacao','proposta_enviada','negociacao','fechado_ganho','fechado_perdido')
                              ) DEFAULT 'novo_lead',
    valor_estimado           REAL DEFAULT 0,
    status                   TEXT NOT NULL CHECK(status IN ('aberto','ganho','perdido')) DEFAULT 'aberto',
    etapa_atualizada_em      TEXT NOT NULL DEFAULT (datetime('now')),
    data_prevista_fechamento TEXT,
    motivo_perda             TEXT,
    motivo_perda_detalhe     TEXT,
    origem_recompra          INTEGER NOT NULL DEFAULT 0,  -- 1 = criado pelo ciclo 🔁
    categoria                TEXT NOT NULL DEFAULT 'padrao',  -- 'padrao' | 'software'
    produto_software         TEXT,  -- revele_momentos | revele_momentos_frontier
    produto_id               TEXT REFERENCES produtos(id),  -- 📦 produto do catálogo (opcional)
    produto_qtd              INTEGER,  -- 📦 unidades negociadas (NULL = 1)
    condicao_pagamento_id    TEXT,      -- 🧾 condição de pagamento do orçamento
    created_at               TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Histórico de transição de etapa: uma linha a cada vez que um negócio muda de etapa.
-- Sem isso não dá pra saber "quando" um negócio entrou em cada etapa (só a etapa atual).
CREATE TABLE IF NOT EXISTS deal_stage_history (
    id              TEXT PRIMARY KEY,
    deal_id         TEXT NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    etapa_anterior  TEXT,
    etapa_nova      TEXT NOT NULL,
    user_id         TEXT REFERENCES users(id),
    -- preenchidos apenas quando etapa_nova = 'fechado_perdido':
    motivo_perda         TEXT,
    motivo_perda_detalhe TEXT,
    data_transicao  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_stage_history_deal ON deal_stage_history(deal_id);

-- Histórico da negociação: cada linha é uma "conversa" registrada pelo
-- vendedor em um negócio, carimbada com a etapa do funil em que ocorreu.
-- Visibilidade: vendedor só vê notas dos PRÓPRIOS negócios; admin vê tudo.
CREATE TABLE IF NOT EXISTS deal_notes (
    id          TEXT PRIMARY KEY,
    deal_id     TEXT NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL REFERENCES users(id),
    etapa_funil TEXT NOT NULL,
    conteudo    TEXT NOT NULL,
    tipo        TEXT NOT NULL DEFAULT 'nota',    -- 'nota' | 'whatsapp'
    tem_anexo   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Print/imagem anexado a uma nota do histórico (ex.: captura da conversa
-- no WhatsApp). Guardado como BLOB no próprio banco: assim o backup do
-- crm.db leva junto os anexos, sem depender de pasta de uploads.
CREATE TABLE IF NOT EXISTS deal_note_anexos (
    note_id      TEXT PRIMARY KEY REFERENCES deal_notes(id) ON DELETE CASCADE,
    mime         TEXT NOT NULL,
    nome_arquivo TEXT,
    dados        BLOB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deal_notes_deal ON deal_notes(deal_id);

-- 💰 Histórico de valores do negócio: valor inicial (valor_anterior NULL)
-- e cada alteração posterior. Alimenta a linha do tempo da negociação.
CREATE TABLE IF NOT EXISTS deal_value_history (
    id              TEXT PRIMARY KEY,
    deal_id         TEXT NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    valor_anterior  REAL,
    valor_novo      REAL NOT NULL,
    user_id         TEXT REFERENCES users(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_deal_value_deal ON deal_value_history(deal_id);

-- 🎯 Metas configuráveis pelo administrador
CREATE TABLE IF NOT EXISTS metas (
    id             TEXT PRIMARY KEY,
    titulo         TEXT NOT NULL,
    descricao      TEXT,
    tipo           TEXT NOT NULL CHECK(tipo IN ('vendas','manual')),
    alvo_vendas    TEXT,      -- qualquer|padrao|software_qualquer|revele_momentos|revele_momentos_frontier|produto
    alvo_produto_id TEXT REFERENCES produtos(id),  -- quando alvo_vendas = 'produto'
    quantidade     INTEGER NOT NULL,
    apuracao       TEXT NOT NULL CHECK(apuracao IN ('individual','coletiva')) DEFAULT 'individual',
    escopo         TEXT NOT NULL CHECK(escopo IN ('todos','vendedores','individual','selecionados')),
    escopo_user_id TEXT REFERENCES users(id),      -- legado: escopo 'individual'
    escopo_users   TEXT,                            -- JSON: ids p/ escopo 'selecionados'
    periodo_tipo   TEXT NOT NULL CHECK(periodo_tipo IN ('mensal','periodo','sem_fim')),
    data_inicio    TEXT,
    data_fim       TEXT,
    status         TEXT NOT NULL CHECK(status IN ('ativa','excluida')) DEFAULT 'ativa',
    criado_por     TEXT REFERENCES users(id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    excluida_por   TEXT,
    excluida_em    TEXT,
    editada_por    TEXT,
    editada_em     TEXT
);

-- registros de progresso das metas MANUAIS (histórico de trabalho)
CREATE TABLE IF NOT EXISTS meta_progresso (
    id         TEXT PRIMARY KEY,
    meta_id    TEXT NOT NULL REFERENCES metas(id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL REFERENCES users(id),
    quantidade INTEGER NOT NULL DEFAULT 1,
    nota       TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_meta_prog_meta ON meta_progresso(meta_id);

-- 📦 Catálogo de produtos (admin gerencia): vincula negócios a metas.
CREATE TABLE IF NOT EXISTS produtos (
    id               TEXT PRIMARY KEY,
    nome             TEXT NOT NULL,
    ativo            INTEGER NOT NULL DEFAULT 1,
    criado_por       TEXT REFERENCES users(id),
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    -- 📊 Base Comercial (Fase 1)
    seq              INTEGER,        -- nº na planilha oficial
    categoria        TEXT,           -- ex.: Cartucho inkjet, Papel térmico
    equipamento      TEXT,           -- linha compatível: DX100, ASK-400…
    embalagem        TEXT,           -- rendimento/embalagem
    preco_tabela     REAL,           -- preço oficial de oferta
    preco_limite     REAL,           -- piso interno de negociação (sigiloso)
    desconto_max     REAL,           -- fração (0.067 = 6,7%)
    status_comercial TEXT,           -- validação da planilha (OK, não ofertar…)
    ofertavel        INTEGER NOT NULL DEFAULT 1,  -- 0 = fora das opções de venda
    desconto_valor   REAL NOT NULL DEFAULT 0     -- 💸 desconto em R$ definido pelo admin
);

-- 🚚 Mínimo do pedido para frete grátis, por UF
CREATE TABLE IF NOT EXISTS frete_uf (
    uf            TEXT PRIMARY KEY,
    regiao        TEXT,
    estado        TEXT,
    minimo        REAL NOT NULL,
    atualizado_em TEXT
);

-- 💳 Condições de pagamento autorizadas pelo financeiro (+ notas operacionais)
CREATE TABLE IF NOT EXISTS condicoes_pagamento (
    id            TEXT PRIMARY KEY,
    perfil        TEXT,
    forma         TEXT,
    condicao      TEXT,
    regra         TEXT,
    eh_nota       INTEGER NOT NULL DEFAULT 0,
    ordem         INTEGER,
    acrescimo_pct REAL NOT NULL DEFAULT 0,  -- ex.: 2.0 = +2% (cartão)
    atualizado_em TEXT
);

-- 🙋 Liberações pontuais de preço abaixo do limite (v36)
CREATE TABLE IF NOT EXISTS liberacoes_preco (
    id               TEXT PRIMARY KEY,
    deal_id          TEXT NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    produto_id       TEXT NOT NULL REFERENCES produtos(id),
    user_id          TEXT NOT NULL REFERENCES users(id),   -- quem pediu
    preco_pedido     REAL NOT NULL,
    motivo           TEXT,
    status           TEXT NOT NULL DEFAULT 'pendente',      -- pendente|aprovada|negada|usada
    preco_autorizado REAL,
    admin_id         TEXT REFERENCES users(id),
    observacao       TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    decidido_em      TEXT,
    usado_em         TEXT
);

CREATE INDEX IF NOT EXISTS idx_liberacoes_status ON liberacoes_preco(status);

-- 🧾 Itens do orçamento de cada negócio (Fase 2)
CREATE TABLE IF NOT EXISTS deal_itens (
    id          TEXT PRIMARY KEY,
    deal_id     TEXT NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    produto_id  TEXT NOT NULL REFERENCES produtos(id),
    qtd         INTEGER NOT NULL DEFAULT 1,
    preco_unit  REAL NOT NULL,              -- preço praticado nesta proposta
    usou_limite INTEGER NOT NULL DEFAULT 0, -- 1 = abaixo do preço de tabela
    aprovado    INTEGER NOT NULL DEFAULT 1, -- 0 = abaixo do limite, aguardando liberação
    liberacao_id TEXT REFERENCES liberacoes_preco(id),
    user_id     TEXT REFERENCES users(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_deal_itens_deal ON deal_itens(deal_id);

-- ⇄ Transferências de titularidade de clientes (auditoria completa)
CREATE TABLE IF NOT EXISTS customer_transfers (
    id           TEXT PRIMARY KEY,
    customer_id  TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    de_user_id   TEXT REFERENCES users(id),
    para_user_id TEXT NOT NULL REFERENCES users(id),
    admin_id     TEXT NOT NULL REFERENCES users(id),
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_transfers_customer ON customer_transfers(customer_id);
CREATE INDEX IF NOT EXISTS idx_deal_notes_user ON deal_notes(user_id);
CREATE INDEX IF NOT EXISTS idx_stage_history_data ON deal_stage_history(data_transicao);
CREATE INDEX IF NOT EXISTS idx_stage_history_etapa_nova ON deal_stage_history(etapa_nova);

CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    deal_id         TEXT REFERENCES deals(id) ON DELETE CASCADE,
    customer_id     TEXT REFERENCES customers(id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL REFERENCES users(id),
    descricao       TEXT NOT NULL,
    tipo_atividade  TEXT NOT NULL DEFAULT 'outro' CHECK(tipo_atividade IN
                     ('reuniao','proposta','follow_up','ligacao','email','outro')),
    data_lembrete   TEXT NOT NULL,
    executado       INTEGER NOT NULL DEFAULT 0,
    executado_em    TEXT,
    nota_conclusao  TEXT,   -- anotação opcional feita ao concluir
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Canal de saída para alertas (o sistema NUNCA lê mensagens, só envia)
CREATE TABLE IF NOT EXISTS whatsapp_notification_channels (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    numero_whatsapp TEXT NOT NULL,
    provedor        TEXT NOT NULL DEFAULT 'whatsapp_cloud_api',
    ativo           INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS whatsapp_notifications_enviadas (
    id              TEXT PRIMARY KEY,
    ai_insight_id   TEXT REFERENCES ai_insights(id) ON DELETE SET NULL,
    user_id         TEXT NOT NULL REFERENCES users(id),
    mensagem        TEXT NOT NULL,
    status_envio    TEXT NOT NULL DEFAULT 'pendente',
    enviado_em      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ai_insights (
    id                  TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    deal_id             TEXT REFERENCES deals(id) ON DELETE CASCADE,
    user_id             TEXT REFERENCES users(id),
    tipo_alerta         TEXT NOT NULL CHECK(tipo_alerta IN
                         ('inatividade','compromisso_esquecido','abandono_funil','sugestao_conteudo')),
    prioridade          TEXT NOT NULL CHECK(prioridade IN ('baixa','media','alta','urgente')) DEFAULT 'media',
    descricao_insight   TEXT NOT NULL,
    dados_extra         TEXT,
    lido                INTEGER NOT NULL DEFAULT 0,
    escalado_admin      INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id              TEXT PRIMARY KEY,
    user_id         TEXT REFERENCES users(id),
    acao            TEXT NOT NULL,
    entidade        TEXT NOT NULL,
    entidade_id     TEXT,
    detalhes        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Tarefas delegadas: admin atribui uma tarefa a um vendedor (ou outro admin),
-- que conduz o fluxo aberta -> em_andamento -> finalizada e, ao concluir,
-- registra uma breve descrição do que foi feito.
CREATE TABLE IF NOT EXISTS delegated_tasks (
    id                      TEXT PRIMARY KEY,
    titulo                  TEXT NOT NULL,
    descricao               TEXT,
    criado_por              TEXT NOT NULL REFERENCES users(id),
    atribuido_para          TEXT NOT NULL REFERENCES users(id),
    customer_id             TEXT REFERENCES customers(id) ON DELETE SET NULL,
    status                  TEXT NOT NULL CHECK(status IN ('aberta','em_andamento','finalizada')) DEFAULT 'aberta',
    data_prazo              TEXT,
    descricao_conclusao     TEXT,
    grupo_id                TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now')),
    finalizada_em           TEXT
);

CREATE INDEX IF NOT EXISTS idx_delegated_tasks_atribuido ON delegated_tasks(atribuido_para);
CREATE INDEX IF NOT EXISTS idx_delegated_tasks_status ON delegated_tasks(status);
CREATE INDEX IF NOT EXISTS idx_delegated_tasks_grupo ON delegated_tasks(grupo_id);

CREATE INDEX IF NOT EXISTS idx_customers_responsavel ON customers(responsavel_id);
CREATE INDEX IF NOT EXISTS idx_deals_customer ON deals(customer_id);
CREATE INDEX IF NOT EXISTS idx_deals_user ON deals(user_id);
CREATE INDEX IF NOT EXISTS idx_deals_etapa_atualizada ON deals(etapa_atualizada_em);
CREATE INDEX IF NOT EXISTS idx_deals_created_at ON deals(created_at);
CREATE INDEX IF NOT EXISTS idx_deals_prevista_fechamento ON deals(data_prevista_fechamento);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_data_lembrete ON tasks(data_lembrete);
CREATE INDEX IF NOT EXISTS idx_tasks_executado_em ON tasks(executado_em);
CREATE INDEX IF NOT EXISTS idx_customers_created_at ON customers(created_at);
CREATE INDEX IF NOT EXISTS idx_insights_customer ON ai_insights(customer_id);

-- Evita alerta duplicado do mesmo tipo, não lido, para o mesmo cliente
CREATE UNIQUE INDEX IF NOT EXISTS uq_insight_ativo_por_tipo
ON ai_insights(customer_id, tipo_alerta)
WHERE lido = 0;
