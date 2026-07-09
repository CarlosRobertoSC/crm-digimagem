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
    whatsapp_id         TEXT UNIQUE,
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
