"""
CRM-Digimagem — Backend
Flask + SQLite. Sem dependências externas além do que já acompanha o Flask.

Como rodar:
    pip install flask --break-system-packages   # se ainda não tiver
    python3 app.py
Depois abra http://localhost:5000

Login de teste (criados no seed):
    admin1@digimagem.com   / admin123     (Admin Master 1)
    admin2@digimagem.com   / admin123     (Admin Master 2)
    carlos.vendas@lojadigimagem.com.br / vendas123   (Vendedor)
    ana@lojadigimagem.com.br           / vendas123   (Vendedora)
    tiago@lojadigimagem.com.br         / vendas123   (Vendedor)
"""

import sqlite3
import os
import uuid
import json
import time
import threading
import base64
from collections import defaultdict, deque
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone, date
from functools import wraps

from flask import Flask, request, jsonify, g, send_from_directory, Response
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

DB_PATH = "crm.db"
SECRET_KEY = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao-para-algo-aleatorio")
if SECRET_KEY == "troque-esta-chave-em-producao-para-algo-aleatorio":
    print("[AVISO] Usando SECRET_KEY padrão de desenvolvimento. Defina a variável de "
          "ambiente SECRET_KEY com um valor aleatório antes de expor este app na internet.")
TOKEN_MAX_AGE = 60 * 60 * 24 * 7  # 7 dias

# O Assistente de Vendas é 100% GRATUITO: um motor de regras que roda localmente sobre
# os dados do seu próprio CRM (etapa do funil, tempo parado, tarefas pendentes, status
# do cliente). Não há nenhuma chamada a API externa nem a serviços pagos — não vai gerar
# custo nenhum, em nenhuma hipótese, agora ou depois.

serializer = URLSafeTimedSerializer(SECRET_KEY)
app = Flask(__name__, static_folder="static", static_url_path="")


# ------------------------------------------------------------------
# Infra de banco
# ------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def new_id():
    return uuid.uuid4().hex


def now_iso():
    return datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def row_to_dict(row):
    return dict(row) if row else None


# ------------------------------------------------------------------
# Auth / RBAC
# ------------------------------------------------------------------
def make_token(user_id):
    return serializer.dumps({"uid": user_id})


def verify_token(token):
    try:
        data = serializer.loads(token, max_age=TOKEN_MAX_AGE)
        return data.get("uid")
    except (BadSignature, SignatureExpired):
        return None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "").strip()
        uid = verify_token(token) if token else None
        if not uid:
            return jsonify({"error": "Não autenticado. Faça login novamente."}), 401
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE id = ? AND ativo = 1", (uid,)
        ).fetchone()
        if not user:
            return jsonify({"error": "Usuário não encontrado ou inativo."}), 401
        g.current_user = row_to_dict(user)
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if g.current_user["role"] != "admin":
            return jsonify({"error": "Apenas administradores podem executar esta ação."}), 403
        return fn(*args, **kwargs)
    return wrapper


def audit(acao, entidade, entidade_id=None, detalhes=None):
    db = get_db()
    db.execute(
        "INSERT INTO audit_log (id, user_id, acao, entidade, entidade_id, detalhes) VALUES (?,?,?,?,?,?)",
        (new_id(), g.current_user["id"], acao, entidade, entidade_id,
         json.dumps(detalhes) if detalhes else None),
    )


def _ultimo_dia_mes(ano, mes):
    if mes == 12:
        return date(ano, 12, 31)
    return date(ano, mes + 1, 1) - timedelta(days=1)


def resolve_period(tipo, offset=0, data_inicio=None, data_fim=None):
    """Resolve um período de datas a partir do tipo escolhido pelo usuário
    (quinzenal | mensal | trimestral | personalizado) e um deslocamento inteiro
    (offset) para navegar entre períodos anteriores/seguintes. Retorna (inicio, fim)
    como objetos date. Levanta ValueError se os parâmetros forem inválidos."""
    hoje = datetime.now(timezone.utc).replace(tzinfo=None).date()
    offset = int(offset or 0)

    if tipo == "personalizado":
        if not data_inicio or not data_fim:
            raise ValueError("Informe data_inicio e data_fim para o período personalizado.")
        inicio = datetime.strptime(data_inicio, "%Y-%m-%d").date()
        fim = datetime.strptime(data_fim, "%Y-%m-%d").date()
        if fim < inicio:
            raise ValueError("data_fim não pode ser anterior a data_inicio.")
        return inicio, fim

    if tipo == "quinzenal":
        quinzena_atual = 0 if hoje.day <= 15 else 1
        indice = (hoje.year * 24 + (hoje.month - 1) * 2 + quinzena_atual) + offset
        ano2 = indice // 24
        resto = indice % 24
        mes2 = resto // 2 + 1
        quinzena2 = resto % 2
        if quinzena2 == 0:
            return date(ano2, mes2, 1), date(ano2, mes2, 15)
        return date(ano2, mes2, 16), _ultimo_dia_mes(ano2, mes2)

    if tipo == "mensal":
        indice = (hoje.year * 12 + (hoje.month - 1)) + offset
        ano2 = indice // 12
        mes2 = indice % 12 + 1
        return date(ano2, mes2, 1), _ultimo_dia_mes(ano2, mes2)

    if tipo == "trimestral":
        trimestre_atual = (hoje.month - 1) // 3
        indice = (hoje.year * 4 + trimestre_atual) + offset
        ano2 = indice // 4
        trimestre2 = indice % 4
        mes_inicio = trimestre2 * 3 + 1
        mes_fim = mes_inicio + 2
        return date(ano2, mes_inicio, 1), _ultimo_dia_mes(ano2, mes_fim)

    raise ValueError("tipo de período inválido. Use: quinzenal, mensal, trimestral ou personalizado.")


def parse_period_from_request():
    """Lê os parâmetros de período da query string e devolve (inicio_str, fim_str)
    prontos para usar em cláusulas SQL BETWEEN — ou (None, None) se nenhum período
    foi pedido (relatório mostra a situação atual, sem filtro de data)."""
    tipo = request.args.get("periodo")
    if not tipo:
        return None, None
    offset = request.args.get("offset", 0)
    data_inicio = request.args.get("data_inicio")
    data_fim = request.args.get("data_fim")
    inicio, fim = resolve_period(tipo, offset, data_inicio, data_fim)
    return inicio.strftime("%Y-%m-%d"), fim.strftime("%Y-%m-%d")


def report_scope_clause(field="user_id"):
    """Regra de visibilidade dos relatórios: vendedor só vê o próprio; admin vê o
    próprio por padrão, um vendedor específico via ?vendedor_id=, ou todo mundo via
    ?scope=all. Retorna (clause, params)."""
    if g.current_user["role"] != "admin":
        return f" AND {field} = ?", [g.current_user["id"]]
    if request.args.get("scope") == "all":
        return "", []
    vendedor_id = request.args.get("vendedor_id")
    if vendedor_id:
        return f" AND {field} = ?", [vendedor_id]
    return f" AND {field} = ?", [g.current_user["id"]]


def scope_filter_clause(field="responsavel_id"):
    """Retorna (clause, params) para restringir vendedor aos próprios registros.
    Admin só vê tudo se pedir explicitamente ?scope=all."""
    if g.current_user["role"] == "admin" and request.args.get("scope") == "all":
        return "", []
    if g.current_user["role"] == "admin":
        # admin sem scope=all → vê os dados como se fosse ele mesmo (padrão "meus dados")
        return f" AND {field} = ?", [g.current_user["id"]]
    return f" AND {field} = ?", [g.current_user["id"]]


def active_admin_count(db, exclude_user_id=None):
    q = "SELECT COUNT(*) c FROM users WHERE role='admin' AND ativo=1"
    params = []
    if exclude_user_id:
        q += " AND id != ?"
        params.append(exclude_user_id)
    return db.execute(q, params).fetchone()["c"]


# ------------------------------------------------------------------
# Motor de Alertas (regras sobre dados estruturados — sem leitura de conversas)
# ------------------------------------------------------------------
def _int_or_none(v):
    """Converte para inteiro positivo, ou None (usado no ciclo de recompra)."""
    try:
        n = int(str(v).strip())
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _hoje_mais_dias(dias):
    return (datetime.now(timezone.utc) + timedelta(days=dias)).strftime("%Y-%m-%d")


def run_alert_engine():
    db = get_db()

    # 1) Inatividade — clientes recorrentes/vip sem comprar há mais de 30 dias
    limite_inatividade = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)).strftime("%Y-%m-%d")
    inativos = db.execute("""
        SELECT * FROM customers
        WHERE status_fidelidade IN ('recorrente','vip')
          AND data_ultima_compra IS NOT NULL
          AND data_ultima_compra < ?
          AND ativo = 1
    """, (limite_inatividade,)).fetchall()
    for c in inativos:
        dias = (datetime.now(timezone.utc).replace(tzinfo=None) - datetime.strptime(c["data_ultima_compra"], "%Y-%m-%d")).days
        _upsert_insight(
            customer_id=c["id"], deal_id=None, user_id=c["responsavel_id"],
            tipo="inatividade", prioridade="urgente" if dias > 45 else "alta",
            descricao=f'{c["nome"]} está há {dias} dias sem comprar (cliente {c["status_fidelidade"]}).',
            dados_extra={"dias_sem_comprar": dias},
        )

    # 2) Abandono de funil — deals abertos parados há mais de 48h na mesma etapa
    limite_funil = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
    parados = db.execute("""
        SELECT d.*, c.nome as cliente_nome FROM deals d
        JOIN customers c ON c.id = d.customer_id
        WHERE d.status = 'aberto' AND d.etapa_atualizada_em < ? AND c.ativo = 1
    """, (limite_funil,)).fetchall()
    for d in parados:
        horas = int((datetime.now(timezone.utc).replace(tzinfo=None) - datetime.strptime(d["etapa_atualizada_em"], "%Y-%m-%d %H:%M:%S")).total_seconds() // 3600)
        _upsert_insight(
            customer_id=d["customer_id"], deal_id=d["id"], user_id=d["user_id"],
            tipo="abandono_funil", prioridade="urgente" if horas > 72 else "alta",
            descricao=f'Negócio "{d["titulo"]}" com {d["cliente_nome"]} parado em "{d["etapa_funil"]}" há {horas}h.',
            dados_extra={"horas_parado": horas, "etapa": d["etapa_funil"]},
        )

    # 3) Compromisso esquecido — tasks vencidas e não concluídas
    agora = now_iso()
    vencidas = db.execute("""
        SELECT t.*, c.nome as cliente_nome FROM tasks t
        LEFT JOIN customers c ON c.id = t.customer_id
        WHERE t.executado = 0 AND t.data_lembrete < ? AND (c.ativo = 1 OR c.ativo IS NULL)
    """, (agora,)).fetchall()
    for t in vencidas:
        nome_cliente = t["cliente_nome"] or "cliente"
        _upsert_insight(
            customer_id=t["customer_id"], deal_id=t["deal_id"], user_id=t["user_id"],
            tipo="compromisso_esquecido", prioridade="urgente",
            descricao=f'Compromisso não cumprido com {nome_cliente}: "{t["descricao"]}".',
            dados_extra={"task_id": t["id"]},
        )
        # escalonamento: se o compromisso venceu há mais de 24h, marca para admins verem também
        vencido_em = datetime.strptime(t["data_lembrete"], "%Y-%m-%d %H:%M:%S")
        if (datetime.now(timezone.utc).replace(tzinfo=None) - vencido_em) > timedelta(hours=24):
            db.execute(
                "UPDATE ai_insights SET escalado_admin = 1 WHERE customer_id = ? AND tipo_alerta = 'compromisso_esquecido' AND lido = 0",
                (t["customer_id"],),
            )

    # 4) Sugestão de conteúdo — clientes VIP sem alerta de fidelização recente
    vips = db.execute("SELECT * FROM customers WHERE status_fidelidade = 'vip' AND ativo = 1").fetchall()
    for c in vips:
        existe = db.execute("""
            SELECT 1 FROM ai_insights WHERE customer_id = ? AND tipo_alerta = 'sugestao_conteudo'
        """, (c["id"],)).fetchone()
        if not existe:
            _upsert_insight(
                customer_id=c["id"], deal_id=None, user_id=c["responsavel_id"],
                tipo="sugestao_conteudo", prioridade="media",
                descricao=f'{c["nome"]} é cliente VIP — considere enviar catálogo atualizado ou um mimo de fidelização.',
                dados_extra=None,
            )

    # 5) 🔁 Recompra programada — quando a data agendada do cliente chega, cria
    # automaticamente o novo negócio (valor ZERO, para o vendedor preencher ao
    # negociar) e um compromisso que aparece no 📌 do Feed de Alertas do
    # responsável. Antiduplicação: só gera se o cliente NÃO tiver nenhum
    # negócio aberto — o ciclo continua quando o negócio atual for fechado.
    hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    devidos = db.execute("""
        SELECT * FROM customers
        WHERE recompra_dias IS NOT NULL AND recompra_dias > 0
          AND proxima_recompra IS NOT NULL AND proxima_recompra <= ?
          AND ativo = 1 AND responsavel_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM deals d WHERE d.customer_id = customers.id AND d.status = 'aberto'
          )
    """, (hoje,)).fetchall()
    for c in devidos:
        did = new_id()
        db.execute("""
            INSERT INTO deals (id, customer_id, user_id, titulo, etapa_funil,
                               valor_estimado, status, origem_recompra)
            VALUES (?,?,?,?,'novo_lead',0,'aberto',1)
        """, (did, c["id"], c["responsavel_id"], "Recompra de insumos"))
        db.execute("""
            INSERT INTO deal_stage_history (id, deal_id, etapa_anterior, etapa_nova, user_id, data_transicao)
            VALUES (?,?,NULL,'novo_lead',?,?)
        """, (new_id(), did, c["responsavel_id"], now_iso()))
        db.execute("""
            INSERT INTO tasks (id, customer_id, deal_id, user_id, descricao, tipo_atividade, data_lembrete)
            VALUES (?,?,?,?,?,'follow_up',?)
        """, (new_id(), c["id"], did, c["responsavel_id"],
              f'🔁 Recompra programada: contatar {c["nome"]} para nova venda de insumos',
              (datetime.now(timezone.utc) + timedelta(hours=23)).strftime("%Y-%m-%d %H:%M:%S")))
        # desarma a agenda; o ciclo é reprogramado quando este negócio for fechado
        db.execute("UPDATE customers SET proxima_recompra = NULL WHERE id = ?", (c["id"],))
        audit("create", "deals", did, {"origem": "recompra_programada", "customer_id": c["id"]})

    db.commit()


def _upsert_insight(customer_id, deal_id, user_id, tipo, prioridade, descricao, dados_extra):
    db = get_db()
    existente = db.execute("""
        SELECT id FROM ai_insights WHERE customer_id = ? AND tipo_alerta = ? AND lido = 0
    """, (customer_id, tipo)).fetchone()
    if existente:
        return  # já existe alerta ativo desse tipo para esse cliente — não duplica
    db.execute("""
        INSERT INTO ai_insights (id, customer_id, deal_id, user_id, tipo_alerta, prioridade, descricao_insight, dados_extra)
        VALUES (?,?,?,?,?,?,?,?)
    """, (new_id(), customer_id, deal_id, user_id, tipo, prioridade, descricao,
          json.dumps(dados_extra) if dados_extra else None))


# ------------------------------------------------------------------
# Assistente de Vendas — motor de regras 100% local e gratuito.
# Não chama nenhuma API externa nem serviço pago: só lê os dados que já
# estão no seu banco (etapa do funil, tempo parado, tarefas, cliente) e
# aplica um checklist de boas práticas de vendas.
# ------------------------------------------------------------------
ETAPA_PESO = {
    "novo_lead": 15, "qualificacao": 35, "proposta_enviada": 55,
    "negociacao": 75, "fechado_ganho": 100, "fechado_perdido": 0,
}

DICAS_GERAIS = [
    "Responda leads novos em até algumas horas — a chance de conversão despenca depois do primeiro dia.",
    "Sempre marque um próximo passo com data antes de encerrar uma conversa com o cliente.",
    "Clientes VIP fecham mais rápido quando recebem algum diferencial exclusivo (condição, brinde, prioridade de agenda).",
    "Negócios parados há mais de 48h numa etapa quase sempre precisam de um empurrão ativo, não de esperar o cliente responder.",
    "Depois de enviar uma proposta, confirme em 24h se o cliente teve alguma dúvida — silêncio geralmente é objeção não dita.",
]


def _hours_since(iso_ts):
    dt = datetime.strptime(iso_ts, "%Y-%m-%d %H:%M:%S")
    return (datetime.now(timezone.utc).replace(tzinfo=None) - dt).total_seconds() / 3600


def build_deal_recommendation(deal, customer, tasks):
    """Retorna (score 0-100, lista de recomendações) para um negócio, sem nenhuma
    chamada externa — só regras sobre os dados estruturados do próprio negócio."""
    horas_parado = _hours_since(deal["etapa_atualizada_em"])
    horas_criado = _hours_since(deal["created_at"])
    etapa = deal["etapa_funil"]
    score = ETAPA_PESO.get(etapa, 20)

    tarefas_abertas = [t for t in tasks if not t["executado"]]
    tarefas_vencidas = [t for t in tarefas_abertas
                         if datetime.strptime(t["data_lembrete"], "%Y-%m-%d %H:%M:%S") < datetime.now(timezone.utc).replace(tzinfo=None)]

    recomendacoes = []

    if horas_parado > 96:
        score -= 30
        recomendacoes.append({"prioridade": "urgente",
            "texto": f"Parado há {int(horas_parado)}h nesta etapa — está bem acima do razoável. Retome contato hoje ou reavalie se este negócio ainda é viável."})
    elif horas_parado > 48:
        score -= 15
        recomendacoes.append({"prioridade": "alta",
            "texto": f"Parado há {int(horas_parado)}h na etapa atual (limite saudável: 48h). Faça contato ativo em vez de esperar o cliente responder."})

    if tarefas_vencidas:
        score -= 20
        recomendacoes.append({"prioridade": "urgente",
            "texto": f'Existe {len(tarefas_vencidas)} compromisso(s) vencido(s) com este cliente. Resolva isso antes de qualquer outra ação — é o que mais derruba confiança.'})
    elif not tarefas_abertas:
        score -= 10
        recomendacoes.append({"prioridade": "alta",
            "texto": "Não há nenhum próximo passo agendado para este negócio. Marque um follow-up agora — negócio sem próxima data tende a esfriar."})

    if etapa == "novo_lead" and horas_criado > 24:
        score -= 10
        recomendacoes.append({"prioridade": "alta",
            "texto": "Lead novo há mais de 24h sem avançar para qualificação. Priorize o primeiro contato — a taxa de resposta cai muito depois do primeiro dia."})

    if etapa == "proposta_enviada" and horas_parado > 24:
        recomendacoes.append({"prioridade": "media",
            "texto": "Proposta enviada há mais de 24h sem retorno. Confirme se o cliente teve alguma dúvida — silêncio costuma ser objeção de preço não dita."})

    if etapa == "negociacao":
        recomendacoes.append({"prioridade": "media",
            "texto": "Você está na reta final. Reforce os diferenciais do serviço e, se fizer sentido, ofereça uma condição para fechar ainda esta semana."})

    if customer["status_fidelidade"] == "vip":
        score += 10
        recomendacoes.append({"prioridade": "baixa",
            "texto": "Cliente VIP — considere um diferencial exclusivo (condição especial, prioridade de agenda ou um mimo) para acelerar a decisão."})

    if deal["valor_estimado"] and deal["valor_estimado"] >= 10000:
        recomendacoes.append({"prioridade": "baixa",
            "texto": "Negócio de ticket alto — vale a pena uma conversa por ligação ou vídeo em vez de só texto, para reduzir o risco de mal-entendido."})

    if not recomendacoes:
        recomendacoes.append({"prioridade": "baixa",
            "texto": "Este negócio está em dia: sem pendências vencidas e dentro do tempo esperado na etapa. Continue o ritmo combinado com o cliente."})

    score = max(0, min(100, round(score)))
    ordem_prioridade = {"urgente": 0, "alta": 1, "media": 2, "baixa": 3}
    recomendacoes.sort(key=lambda r: ordem_prioridade[r["prioridade"]])
    return score, recomendacoes


# ------------------------------------------------------------------
# Rate limiting do login — proteção contra força bruta.
# Em memória, o que é adequado ao deploy atual (1 worker no gunicorn).
# Se um dia escalar para múltiplos workers/instâncias, mover o estado
# para Redis ou equivalente.
# ------------------------------------------------------------------
LOGIN_MAX_FALHAS = 5            # tentativas erradas permitidas…
LOGIN_JANELA_SEGUNDOS = 15 * 60  # …dentro desta janela (15 min)
_login_falhas = defaultdict(deque)   # ip -> timestamps (monotonic) das falhas
_login_lock = threading.Lock()


def _client_ip():
    """IP real do cliente. Atrás do proxy do Render/Heroku ele vem no
    X-Forwarded-For (primeiro endereço da lista)."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "desconhecido"


def _login_bloqueado(ip):
    """Retorna quantos segundos faltam para o IP poder tentar de novo,
    ou 0 se ainda está dentro do limite."""
    agora = time.monotonic()
    with _login_lock:
        falhas = _login_falhas[ip]
        while falhas and agora - falhas[0] > LOGIN_JANELA_SEGUNDOS:
            falhas.popleft()
        if len(falhas) >= LOGIN_MAX_FALHAS:
            return int(LOGIN_JANELA_SEGUNDOS - (agora - falhas[0])) + 1
    return 0


def _login_registrar_falha(ip):
    with _login_lock:
        _login_falhas[ip].append(time.monotonic())


def _login_limpar(ip):
    with _login_lock:
        _login_falhas.pop(ip, None)


# ------------------------------------------------------------------
# Rotas — Auth
# ------------------------------------------------------------------
@app.post("/api/auth/login")
def login():
    ip = _client_ip()
    espera = _login_bloqueado(ip)
    if espera:
        minutos = max(1, -(-espera // 60))  # arredonda pra cima
        resp = jsonify({"error": f"Muitas tentativas de login. Aguarde {minutos} minuto(s) e tente novamente."})
        resp.headers["Retry-After"] = str(espera)
        return resp, 429
    body = request.get_json(force=True, silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    senha = body.get("senha") or ""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ? AND ativo = 1", (email,)).fetchone()
    if not user or not check_password_hash(user["senha_hash"], senha):
        _login_registrar_falha(ip)
        return jsonify({"error": "Email ou senha inválidos."}), 401
    _login_limpar(ip)
    token = make_token(user["id"])
    return jsonify({
        "token": token,
        "user": {"id": user["id"], "nome": user["nome"], "role": user["role"], "email": user["email"]},
    })


@app.get("/api/me")
@login_required
def me():
    u = g.current_user
    return jsonify({"id": u["id"], "nome": u["nome"], "role": u["role"], "email": u["email"]})


# ------------------------------------------------------------------
# Rotas — Dashboard (stats agregadas)
# ------------------------------------------------------------------
@app.get("/api/dashboard/stats")
@login_required
def dashboard_stats():
    run_alert_engine()
    db = get_db()
    clause, params = scope_filter_clause("user_id")

    # alertas urgentes visíveis no escopo do usuário
    if g.current_user["role"] == "admin" and request.args.get("scope") == "all":
        urgentes = db.execute(
            "SELECT COUNT(*) c FROM ai_insights WHERE lido = 0 AND prioridade = 'urgente'"
        ).fetchone()["c"]
        valor_aberto = db.execute(
            "SELECT COALESCE(SUM(valor_estimado),0) v FROM deals WHERE status='aberto'"
        ).fetchone()["v"]
        parados = db.execute(
            "SELECT COUNT(*) c FROM deals WHERE status='aberto' AND etapa_atualizada_em < ?",
            ((datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S"),)
        ).fetchone()["c"]
    else:
        uid = g.current_user["id"]
        urgentes = db.execute(
            "SELECT COUNT(*) c FROM ai_insights WHERE lido = 0 AND prioridade = 'urgente' AND user_id = ?", (uid,)
        ).fetchone()["c"]
        valor_aberto = db.execute(
            "SELECT COALESCE(SUM(valor_estimado),0) v FROM deals WHERE status='aberto' AND user_id = ?", (uid,)
        ).fetchone()["v"]
        parados = db.execute(
            "SELECT COUNT(*) c FROM deals WHERE status='aberto' AND user_id = ? AND etapa_atualizada_em < ?",
            (uid, (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S"))
        ).fetchone()["c"]

    return jsonify({"alertas_urgentes": urgentes, "valor_em_negociacao": valor_aberto, "deals_parados": parados})


# ------------------------------------------------------------------
# Rotas — Alertas (ai_insights)
# ------------------------------------------------------------------
@app.get("/api/insights")
@login_required
def list_insights():
    run_alert_engine()
    db = get_db()
    if g.current_user["role"] == "admin" and request.args.get("scope") == "all":
        rows = db.execute("""
            SELECT i.*, c.nome as cliente_nome, u.nome as vendedor_nome FROM ai_insights i
            JOIN customers c ON c.id = i.customer_id
            LEFT JOIN users u ON u.id = i.user_id
            WHERE i.lido = 0
            ORDER BY CASE i.prioridade WHEN 'urgente' THEN 0 WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END, i.created_at DESC
        """).fetchall()
    else:
        # Cada usuário só vê os próprios alertas — mesmo os escalados (compromisso vencido
        # há +24h) não vazam para outros vendedores; o admin já enxerga tudo via scope=all.
        rows = db.execute("""
            SELECT i.*, c.nome as cliente_nome FROM ai_insights i
            JOIN customers c ON c.id = i.customer_id
            WHERE i.lido = 0 AND i.user_id = ?
            ORDER BY CASE i.prioridade WHEN 'urgente' THEN 0 WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END, i.created_at DESC
        """, (g.current_user["id"],)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/insights/<insight_id>/read")
@login_required
def mark_insight_read(insight_id):
    db = get_db()
    existing = db.execute("SELECT * FROM ai_insights WHERE id = ?", (insight_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Alerta não encontrado."}), 404
    if g.current_user["role"] != "admin" and existing["user_id"] != g.current_user["id"]:
        return jsonify({"error": "Sem permissão para alterar este alerta."}), 403
    db.execute("UPDATE ai_insights SET lido = 1 WHERE id = ?", (insight_id,))
    audit("update", "ai_insights", insight_id, {"lido": True})
    db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------
# Rotas — Customers
# ------------------------------------------------------------------
@app.get("/api/customers")
@login_required
def list_customers():
    db = get_db()
    clause, params = scope_filter_clause("responsavel_id")
    params = list(params)
    filtro_ativo = "" if request.args.get("incluir_inativos") == "1" else " AND c.ativo = 1"

    # Busca livre (?q=) por nome, email, CPF/CNPJ, cidade, WhatsApp ou telefone.
    # Curingas do LIKE (% e _) são escapados para a busca ser sempre literal.
    filtro_busca = ""
    q = (request.args.get("q") or "").strip()
    if q:
        q_like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filtro_busca = (
            " AND (c.nome LIKE ? ESCAPE '\\' OR c.email LIKE ? ESCAPE '\\'"
            " OR c.cpf_cnpj LIKE ? ESCAPE '\\' OR c.cidade LIKE ? ESCAPE '\\'"
            " OR c.whatsapp_id LIKE ? ESCAPE '\\' OR c.telefone LIKE ? ESCAPE '\\')"
        )
        params += [q_like] * 6

    # Paginação opcional (?limit=&offset=). Sem limit, mantém o comportamento
    # atual de retornar tudo — os seletores de cliente do frontend dependem disso.
    try:
        limit = int(request.args.get("limit", 0))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        limit, offset = 0, 0
    clausula_limite = ""
    if limit > 0:
        clausula_limite = " LIMIT ? OFFSET ?"
        params += [limit, max(0, offset)]

    rows = db.execute(f"""
        SELECT c.*, u.nome as responsavel_nome FROM customers c
        LEFT JOIN users u ON u.id = c.responsavel_id
        WHERE 1=1 {clause}{filtro_ativo}{filtro_busca}
        ORDER BY c.nome{clausula_limite}
    """, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/customers/<customer_id>")
@login_required
def get_customer(customer_id):
    db = get_db()
    c = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not c:
        return jsonify({"error": "Cliente não encontrado."}), 404
    if g.current_user["role"] != "admin" and c["responsavel_id"] != g.current_user["id"]:
        return jsonify({"error": "Sem permissão para ver este cliente."}), 403
    deals = db.execute("SELECT * FROM deals WHERE customer_id = ? ORDER BY created_at DESC", (customer_id,)).fetchall()
    tasks = db.execute("SELECT * FROM tasks WHERE customer_id = ? ORDER BY data_lembrete", (customer_id,)).fetchall()
    insights = db.execute("SELECT * FROM ai_insights WHERE customer_id = ? AND lido = 0 ORDER BY created_at DESC", (customer_id,)).fetchall()
    audit("read", "customers", customer_id)
    db.commit()
    return jsonify({
        "customer": dict(c),
        "deals": [dict(d) for d in deals],
        "tasks": [dict(t) for t in tasks],
        "insights": [dict(i) for i in insights],
    })


@app.post("/api/customers")
@login_required
def create_customer():
    body = request.get_json(force=True, silent=True) or {}
    if not body.get("nome"):
        return jsonify({"error": "Nome é obrigatório."}), 400
    db = get_db()
    cid = new_id()
    # Vendedor só pode cadastrar cliente para si mesmo; só admin pode atribuir a outro usuário.
    responsavel_id = body.get("responsavel_id", g.current_user["id"])
    if g.current_user["role"] != "admin":
        responsavel_id = g.current_user["id"]
    recompra_dias = _int_or_none(body.get("recompra_dias"))
    db.execute("""
        INSERT INTO customers (id, nome, whatsapp_id, telefone, email, cpf_cnpj, endereco, cep,
            cidade, estado, data_ultima_compra, status_fidelidade, responsavel_id, origem, observacoes,
            recompra_dias, proxima_recompra)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (cid, body["nome"], body.get("whatsapp_id"), body.get("telefone"), body.get("email"),
          body.get("cpf_cnpj"), body.get("endereco"), body.get("cep"), body.get("cidade"), body.get("estado"),
          body.get("data_ultima_compra"), body.get("status_fidelidade", "novo"),
          responsavel_id, body.get("origem"), body.get("observacoes"),
          recompra_dias, _hoje_mais_dias(recompra_dias) if recompra_dias else None))
    audit("create", "customers", cid, body)
    db.commit()
    return jsonify({"id": cid}), 201


@app.put("/api/customers/<customer_id>")
@login_required
def update_customer(customer_id):
    db = get_db()
    existing = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Cliente não encontrado."}), 404
    if g.current_user["role"] != "admin" and existing["responsavel_id"] != g.current_user["id"]:
        return jsonify({"error": "Sem permissão para editar este cliente."}), 403
    body = request.get_json(force=True, silent=True) or {}
    campos = ["nome", "whatsapp_id", "telefone", "email", "cpf_cnpj", "endereco", "cep",
              "cidade", "estado", "data_ultima_compra", "status_fidelidade", "observacoes", "ativo"]
    valores = {c: body.get(c, existing[c]) for c in campos}
    if "ativo" in body:
        valores["ativo"] = 1 if body.get("ativo") in (1, "1", True, "true") else 0
    if "recompra_dias" in body:
        novo_dias = _int_or_none(body.get("recompra_dias"))
        if novo_dias != existing["recompra_dias"]:
            # ligar ou alterar o ciclo reprograma o contato a partir de HOJE;
            # desligar (vazio/zero) limpa a agenda
            db.execute("UPDATE customers SET recompra_dias = ?, proxima_recompra = ? WHERE id = ?",
                       (novo_dias, _hoje_mais_dias(novo_dias) if novo_dias else None, customer_id))
    db.execute(f"""
        UPDATE customers SET {", ".join(f"{c} = ?" for c in campos)}, updated_at = ?
        WHERE id = ?
    """, (*valores.values(), now_iso(), customer_id))
    audit("update", "customers", customer_id, body)
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/customers/<customer_id>")
@login_required
def delete_customer(customer_id):
    db = get_db()
    existing = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Cliente não encontrado."}), 404
    if g.current_user["role"] != "admin" and existing["responsavel_id"] != g.current_user["id"]:
        return jsonify({"error": "Sem permissão para excluir este cliente."}), 403
    # Exclusão em cascata: negócios, compromissos e alertas ligados a este cliente somem
    # junto (definido via ON DELETE CASCADE no schema). Tarefas delegadas que citavam este
    # cliente são preservadas, só perdem o vínculo (ON DELETE SET NULL).
    db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    audit("delete", "customers", customer_id, {"nome": existing["nome"]})
    db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------
# Rotas — Consulta externa de CNPJ e CEP (preenchimento automático)
# Usa BrasilAPI (dados da Receita Federal) e ViaCEP — ambas gratuitas,
# públicas e sem necessidade de chave de API. Nenhum custo envolvido.
# ------------------------------------------------------------------
def _http_get_json(url, timeout=6):
    """GET simples usando só a biblioteca padrão do Python (sem dependência
    nova). Levanta urllib.error.HTTPError em respostas 4xx/5xx."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "CRM-Digimagem/1.0 (contato@lojadigimagem.com.br)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


@app.get("/api/lookup/cnpj/<cnpj>")
@login_required
def lookup_cnpj(cnpj):
    digitos = "".join(c for c in cnpj if c.isdigit())
    if len(digitos) != 14:
        return jsonify({"error": "CNPJ precisa ter 14 dígitos."}), 400
    try:
        dados = _http_get_json(f"https://brasilapi.com.br/api/cnpj/v1/{digitos}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return jsonify({"error": "CNPJ não encontrado na Receita Federal."}), 404
        return jsonify({"error": "Não foi possível consultar o CNPJ agora. Tente novamente ou preencha manualmente."}), 502
    except Exception:
        return jsonify({"error": "Não foi possível consultar o CNPJ agora. Tente novamente ou preencha manualmente."}), 502

    endereco_partes = [dados.get("logradouro"), dados.get("numero")]
    if dados.get("complemento"):
        endereco_partes.append(dados["complemento"])
    endereco = ", ".join(p for p in endereco_partes if p) or None

    telefone = dados.get("ddd_telefone_1") or ""

    return jsonify({
        "nome": dados.get("nome_fantasia") or dados.get("razao_social"),
        "razao_social": dados.get("razao_social"),
        "endereco": endereco,
        "bairro": dados.get("bairro"),
        "cep": dados.get("cep"),
        "cidade": dados.get("municipio"),
        "estado": dados.get("uf"),
        "telefone": telefone,
        "situacao_cadastral": dados.get("descricao_situacao_cadastral"),
    })


@app.get("/api/lookup/cep/<cep>")
@login_required
def lookup_cep(cep):
    digitos = "".join(c for c in cep if c.isdigit())
    if len(digitos) != 8:
        return jsonify({"error": "CEP precisa ter 8 dígitos."}), 400
    try:
        dados = _http_get_json(f"https://viacep.com.br/ws/{digitos}/json/")
    except Exception:
        return jsonify({"error": "Não foi possível consultar o CEP agora. Tente novamente ou preencha manualmente."}), 502

    if dados.get("erro"):
        return jsonify({"error": "CEP não encontrado."}), 404

    endereco_partes = [dados.get("logradouro"), dados.get("bairro")]
    endereco = ", ".join(p for p in endereco_partes if p) or None

    return jsonify({
        "endereco": endereco,
        "cidade": dados.get("localidade"),
        "estado": dados.get("uf"),
    })


# ------------------------------------------------------------------
# Rotas — Deals / Funil
# ------------------------------------------------------------------
ETAPAS = ["novo_lead", "qualificacao", "proposta_enviada", "negociacao", "fechado_ganho", "fechado_perdido"]
ETAPAS_ABERTAS = ["novo_lead", "qualificacao", "proposta_enviada", "negociacao"]
ETAPA_LABEL_BACKEND = {
    "novo_lead": "Novo Lead", "qualificacao": "Qualificação",
    "proposta_enviada": "Proposta Enviada", "negociacao": "Negociação",
}


@app.get("/api/deals")
@login_required
def list_deals():
    db = get_db()
    clause, params = scope_filter_clause("user_id")
    rows = db.execute(f"""
        SELECT d.*, c.nome as cliente_nome, u.nome as vendedor_nome,
               (SELECT COUNT(*) FROM deal_notes n WHERE n.deal_id = d.id) as notas_count
        FROM deals d
        JOIN customers c ON c.id = d.customer_id
        LEFT JOIN users u ON u.id = d.user_id
        WHERE 1=1 {clause}
        ORDER BY d.created_at DESC
    """, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/deals")
@login_required
def create_deal():
    body = request.get_json(force=True, silent=True) or {}
    for f in ("customer_id", "titulo"):
        if not body.get(f):
            return jsonify({"error": f"Campo '{f}' é obrigatório."}), 400
    db = get_db()

    cliente = db.execute("SELECT * FROM customers WHERE id = ?", (body["customer_id"],)).fetchone()
    if not cliente:
        return jsonify({"error": "Cliente não encontrado."}), 404
    if g.current_user["role"] != "admin" and cliente["responsavel_id"] != g.current_user["id"]:
        return jsonify({"error": "Você só pode criar negócios para os seus próprios clientes."}), 403

    # Vendedor só pode criar negócio para si mesmo; só admin pode atribuir a outro usuário.
    user_id = body.get("user_id", g.current_user["id"])
    if g.current_user["role"] != "admin":
        user_id = g.current_user["id"]

    did = new_id()
    etapa_inicial = body.get("etapa_funil", "novo_lead")
    db.execute("""
        INSERT INTO deals (id, customer_id, user_id, titulo, etapa_funil, valor_estimado, status, data_prevista_fechamento)
        VALUES (?,?,?,?,?,?,'aberto',?)
    """, (did, body["customer_id"], user_id, body["titulo"],
          etapa_inicial, body.get("valor_estimado", 0), body.get("data_prevista_fechamento")))
    db.execute("""
        INSERT INTO deal_stage_history (id, deal_id, etapa_anterior, etapa_nova, user_id, data_transicao)
        VALUES (?,?,NULL,?,?,?)
    """, (new_id(), did, etapa_inicial, user_id, now_iso()))
    audit("create", "deals", did, body)
    db.commit()
    return jsonify({"id": did}), 201


MOTIVOS_PERDA_VALIDOS = (
    "preco", "concorrente", "falta_funcionalidade", "sumiu_no_show",
    "sem_orcamento", "timing_errado", "outro",
)


@app.post("/api/deals/<deal_id>/stage")
@login_required
def move_deal_stage(deal_id):
    db = get_db()
    existing = db.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Negócio não encontrado."}), 404
    if g.current_user["role"] != "admin" and existing["user_id"] != g.current_user["id"]:
        return jsonify({"error": "Sem permissão para alterar este negócio."}), 403
    body = request.get_json(force=True, silent=True) or {}
    nova_etapa = body.get("etapa_funil")
    if nova_etapa not in ETAPAS:
        return jsonify({"error": "Etapa inválida."}), 400

    status = "aberto"
    motivo_perda = existing["motivo_perda"]
    motivo_perda_detalhe = existing["motivo_perda_detalhe"]
    if nova_etapa not in ("fechado_ganho", "fechado_perdido"):
        # Movimentação para etapa aberta (inclui reabertura): o motivo da
        # perda sai do negócio — ele permanece registrado no marco "Perdido"
        # da linha do tempo (deal_stage_history.motivo_perda).
        motivo_perda, motivo_perda_detalhe = None, None
    if nova_etapa == "fechado_ganho":
        status = "ganho"
        motivo_perda, motivo_perda_detalhe = None, None
    elif nova_etapa == "fechado_perdido":
        status = "perdido"
        motivo_perda = body.get("motivo_perda")
        if motivo_perda not in MOTIVOS_PERDA_VALIDOS:
            return jsonify({"error": "Informe o motivo da perda para registrar este negócio como perdido."}), 400
        motivo_perda_detalhe = body.get("motivo_perda_detalhe")

    db.execute("""
        UPDATE deals SET etapa_funil = ?, status = ?, etapa_atualizada_em = ?, updated_at = ?,
            motivo_perda = ?, motivo_perda_detalhe = ?
        WHERE id = ?
    """, (nova_etapa, status, now_iso(), now_iso(), motivo_perda, motivo_perda_detalhe, deal_id))

    db.execute("""
        INSERT INTO deal_stage_history (id, deal_id, etapa_anterior, etapa_nova, user_id,
                                        motivo_perda, motivo_perda_detalhe, data_transicao)
        VALUES (?,?,?,?,?,?,?,?)
    """, (new_id(), deal_id, existing["etapa_funil"], nova_etapa, g.current_user["id"],
          motivo_perda if nova_etapa == "fechado_perdido" else None,
          motivo_perda_detalhe if nova_etapa == "fechado_perdido" else None,
          now_iso()))

    # 🔁 Recompra programada: ao FECHAR o negócio (ganho ou perdido), agenda o
    # próximo contato do cliente para daqui a N dias. O motor de alertas criará
    # o novo negócio e o compromisso quando a data chegar.
    if nova_etapa in ("fechado_ganho", "fechado_perdido"):
        cli = db.execute("SELECT recompra_dias FROM customers WHERE id = ?",
                         (existing["customer_id"],)).fetchone()
        if cli and cli["recompra_dias"]:
            db.execute("UPDATE customers SET proxima_recompra = ? WHERE id = ?",
                       (_hoje_mais_dias(cli["recompra_dias"]), existing["customer_id"]))

    audit("update", "deals", deal_id, {"nova_etapa": nova_etapa, "motivo_perda": motivo_perda})
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/deals/<deal_id>/reabrir")
@login_required
def reopen_deal(deal_id):
    """Reabre um negócio marcado como perdido: ele volta ao funil na etapa
    em que estava antes de ser perdido (fallback: negociação). O motivo da
    perda continua registrado no marco 'Perdido' da linha do tempo — nada
    da história se perde. Permissão: dono do negócio ou admin."""
    db = get_db()
    existing = db.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Negócio não encontrado."}), 404
    if g.current_user["role"] != "admin" and existing["user_id"] != g.current_user["id"]:
        return jsonify({"error": "Sem permissão para alterar este negócio."}), 403
    if existing["status"] != "perdido":
        return jsonify({"error": "Só é possível reabrir negócios marcados como perdidos."}), 400

    ultima_perda = db.execute("""
        SELECT * FROM deal_stage_history
        WHERE deal_id = ? AND etapa_nova = 'fechado_perdido'
        ORDER BY data_transicao DESC, rowid DESC LIMIT 1
    """, (deal_id,)).fetchone()

    # Volta para a etapa em que o negócio estava quando foi perdido
    etapa_retorno = "negociacao"
    if ultima_perda and ultima_perda["etapa_anterior"] in ETAPAS             and ultima_perda["etapa_anterior"] not in ("fechado_ganho", "fechado_perdido"):
        etapa_retorno = ultima_perda["etapa_anterior"]

    # Perdas registradas antes do motivo ser gravado no marco: preserva o
    # motivo no próprio marco antes de limpá-lo do negócio.
    if ultima_perda and not ultima_perda["motivo_perda"] and existing["motivo_perda"]:
        db.execute("""UPDATE deal_stage_history SET motivo_perda = ?, motivo_perda_detalhe = ?
                      WHERE id = ?""",
                   (existing["motivo_perda"], existing["motivo_perda_detalhe"], ultima_perda["id"]))

    db.execute("""
        UPDATE deals SET etapa_funil = ?, status = 'aberto', etapa_atualizada_em = ?, updated_at = ?,
            motivo_perda = NULL, motivo_perda_detalhe = NULL
        WHERE id = ?
    """, (etapa_retorno, now_iso(), now_iso(), deal_id))
    db.execute("""
        INSERT INTO deal_stage_history (id, deal_id, etapa_anterior, etapa_nova, user_id, data_transicao)
        VALUES (?,?,?,?,?,?)
    """, (new_id(), deal_id, "fechado_perdido", etapa_retorno, g.current_user["id"], now_iso()))
    audit("update", "deals", deal_id, {"acao": "reabrir", "etapa_retorno": etapa_retorno})
    db.commit()
    return jsonify({"ok": True, "etapa_funil": etapa_retorno})


@app.get("/api/deals/<deal_id>")
@login_required
def get_deal(deal_id):
    db = get_db()
    d = db.execute("""
        SELECT deals.*, customers.nome as cliente_nome FROM deals
        JOIN customers ON customers.id = deals.customer_id
        WHERE deals.id = ?
    """, (deal_id,)).fetchone()
    if not d:
        return jsonify({"error": "Negócio não encontrado."}), 404
    if g.current_user["role"] != "admin" and d["user_id"] != g.current_user["id"]:
        return jsonify({"error": "Sem permissão para ver este negócio."}), 403
    return jsonify(dict(d))


# ------------------------------------------------------------------
# Rotas — Histórico da Negociação (conversas + mudanças de etapa)
# Regra de visibilidade: vendedor só acessa o histórico dos PRÓPRIOS
# negócios; admin acessa o histórico de qualquer negócio, inclusive
# os de outros administradores. As notas são imutáveis (sem edição ou
# exclusão) para o histórico ser um registro confiável do que ocorreu.
# ------------------------------------------------------------------
def _deal_permitido_ou_erro(deal_id):
    """Carrega o negócio (com nomes de cliente e vendedor) e aplica a
    regra de visibilidade. Retorna (deal, None) ou (None, resposta_erro)."""
    db = get_db()
    d = db.execute("""
        SELECT d.*, c.nome as cliente_nome, u.nome as vendedor_nome
        FROM deals d
        JOIN customers c ON c.id = d.customer_id
        LEFT JOIN users u ON u.id = d.user_id
        WHERE d.id = ?
    """, (deal_id,)).fetchone()
    if not d:
        return None, (jsonify({"error": "Negócio não encontrado."}), 404)
    if g.current_user["role"] != "admin" and d["user_id"] != g.current_user["id"]:
        return None, (jsonify({"error": "Sem permissão para acessar o histórico deste negócio."}), 403)
    return d, None


@app.get("/api/deals/<deal_id>/historico")
@login_required
def deal_historico(deal_id):
    d, erro = _deal_permitido_ou_erro(deal_id)
    if erro:
        return erro
    db = get_db()
    notas = db.execute("""
        SELECT n.*, u.nome as autor_nome, u.role as autor_role FROM deal_notes n
        LEFT JOIN users u ON u.id = n.user_id
        WHERE n.deal_id = ?
    """, (deal_id,)).fetchall()
    etapas = db.execute("""
        SELECT h.*, u.nome as autor_nome FROM deal_stage_history h
        LEFT JOIN users u ON u.id = h.user_id
        WHERE h.deal_id = ?
    """, (deal_id,)).fetchall()
    eventos = (
        [{"tipo": "nota", "id": n["id"], "conteudo": n["conteudo"], "etapa_funil": n["etapa_funil"],
          "autor_nome": n["autor_nome"], "autor_id": n["user_id"], "autor_role": n["autor_role"],
          "nota_tipo": n["tipo"], "tem_anexo": bool(n["tem_anexo"]), "data": n["created_at"]}
         for n in notas]
        + [{"tipo": "etapa", "etapa_anterior": e["etapa_anterior"], "etapa_nova": e["etapa_nova"],
            "autor_nome": e["autor_nome"], "data": e["data_transicao"],
            "motivo_perda": e["motivo_perda"], "motivo_perda_detalhe": e["motivo_perda_detalhe"]}
           for e in etapas]
    )
    eventos.sort(key=lambda ev: (ev["data"], 0 if ev["tipo"] == "etapa" else 1))
    return jsonify({"deal": dict(d), "eventos": eventos})


@app.post("/api/deals/<deal_id>/notas")
@login_required
def add_deal_nota(deal_id):
    d, erro = _deal_permitido_ou_erro(deal_id)
    if erro:
        return erro
    body = request.get_json(force=True, silent=True) or {}
    conteudo = (body.get("conteudo") or "").strip()
    tipo = body.get("tipo") or "nota"
    if tipo not in ("nota", "whatsapp"):
        return jsonify({"error": "Tipo de nota inválido."}), 400
    anexo = body.get("anexo") or None

    if not conteudo and not anexo:
        return jsonify({"error": "Escreva o que foi conversado ou anexe um print antes de salvar."}), 400
    # Conversa colada do WhatsApp pode ser longa; anotação comum é mais curta.
    limite = 20000 if tipo == "whatsapp" else 4000
    if len(conteudo) > limite:
        return jsonify({"error": f"O texto é longo demais (máximo de {limite} caracteres para este tipo de nota)."}), 400

    dados_anexo, mime_anexo, nome_anexo = None, None, None
    if anexo:
        mime_anexo = (anexo.get("mime") or "").lower()
        if mime_anexo not in ANEXO_MIMES_PERMITIDOS:
            return jsonify({"error": "O anexo precisa ser uma imagem PNG, JPEG ou WebP."}), 400
        try:
            dados_anexo = base64.b64decode(anexo.get("dados_base64") or "", validate=True)
        except Exception:
            return jsonify({"error": "Não foi possível ler o anexo enviado."}), 400
        if not dados_anexo or len(dados_anexo) > ANEXO_TAMANHO_MAX:
            return jsonify({"error": "O anexo precisa ter no máximo 2 MB."}), 400
        nome_anexo = (anexo.get("nome") or "anexo")[:120]

    db = get_db()
    nid = new_id()
    # A nota fica carimbada com a etapa em que o negócio está AGORA —
    # assim o histórico mostra o que foi conversado em cada fase da venda.
    db.execute("""
        INSERT INTO deal_notes (id, deal_id, user_id, etapa_funil, conteudo, tipo, tem_anexo)
        VALUES (?,?,?,?,?,?,?)
    """, (nid, deal_id, g.current_user["id"], d["etapa_funil"], conteudo, tipo, 1 if dados_anexo else 0))
    if dados_anexo:
        db.execute("INSERT INTO deal_note_anexos (note_id, mime, nome_arquivo, dados) VALUES (?,?,?,?)",
                   (nid, mime_anexo, nome_anexo, dados_anexo))
    audit("create", "deal_notes", nid, {"deal_id": deal_id, "tipo": tipo, "tem_anexo": bool(dados_anexo)})
    db.commit()
    return jsonify({"id": nid}), 201


ANEXO_MIMES_PERMITIDOS = {"image/png", "image/jpeg", "image/webp"}
ANEXO_TAMANHO_MAX = 2 * 1024 * 1024  # 2 MB


@app.get("/api/deals/<deal_id>/notas/<note_id>/anexo")
@login_required
def get_deal_nota_anexo(deal_id, note_id):
    """Serve o print anexado a uma nota, com a MESMA regra de visibilidade
    do histórico (vendedor: só os próprios negócios; admin: todos)."""
    d, erro = _deal_permitido_ou_erro(deal_id)
    if erro:
        return erro
    db = get_db()
    row = db.execute("""
        SELECT a.mime, a.dados FROM deal_note_anexos a
        JOIN deal_notes n ON n.id = a.note_id
        WHERE a.note_id = ? AND n.deal_id = ?
    """, (note_id, deal_id)).fetchone()
    if not row:
        return jsonify({"error": "Anexo não encontrado."}), 404
    return Response(row["dados"], mimetype=row["mime"],
                    headers={"Cache-Control": "private, max-age=300"})


@app.put("/api/deals/<deal_id>")
@login_required
def update_deal(deal_id):
    db = get_db()
    existing = db.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Negócio não encontrado."}), 404
    if g.current_user["role"] != "admin" and existing["user_id"] != g.current_user["id"]:
        return jsonify({"error": "Sem permissão para editar este negócio."}), 403
    body = request.get_json(force=True, silent=True) or {}
    titulo = body.get("titulo", existing["titulo"])
    valor = body.get("valor_estimado", existing["valor_estimado"])
    data_prevista = body.get("data_prevista_fechamento", existing["data_prevista_fechamento"])
    db.execute("""
        UPDATE deals SET titulo = ?, valor_estimado = ?, data_prevista_fechamento = ?, updated_at = ?
        WHERE id = ?
    """, (titulo, valor, data_prevista, now_iso(), deal_id))
    audit("update", "deals", deal_id, body)
    db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------
# Rotas — Assistente de Vendas (motor de regras gratuito, sem API externa)
# ------------------------------------------------------------------
@app.get("/api/assistant/overview")
@login_required
def assistant_overview():
    db = get_db()
    clause, params = scope_filter_clause("user_id")
    deals = db.execute(f"""
        SELECT deals.*, customers.nome as cliente_nome, customers.status_fidelidade, u.nome as vendedor_nome
        FROM deals
        JOIN customers ON customers.id = deals.customer_id
        LEFT JOIN users u ON u.id = deals.user_id
        WHERE deals.status = 'aberto' {clause}
        ORDER BY deals.created_at DESC
    """, params).fetchall()

    resultado = []
    for d in deals:
        customer = db.execute("SELECT * FROM customers WHERE id = ?", (d["customer_id"],)).fetchone()
        tasks = db.execute("SELECT * FROM tasks WHERE deal_id = ?", (d["id"],)).fetchall()
        score, recomendacoes = build_deal_recommendation(d, customer, tasks)
        resultado.append({
            "deal_id": d["id"], "titulo": d["titulo"], "cliente_nome": d["cliente_nome"],
            "vendedor_nome": d["vendedor_nome"],
            "customer_id": d["customer_id"], "etapa_funil": d["etapa_funil"],
            "valor_estimado": d["valor_estimado"], "score": score,
            "top_recomendacao": recomendacoes[0]["texto"] if recomendacoes else None,
            "qtd_recomendacoes": len(recomendacoes),
        })

    resultado.sort(key=lambda r: r["score"], reverse=True)
    prontos = [r for r in resultado if r["score"] >= 70]
    em_risco = [r for r in resultado if r["score"] < 40]

    return jsonify({
        "total_negocios_abertos": len(resultado),
        "prontos_para_fechar": prontos[:5],
        "em_risco": em_risco[:5],
        "todos": resultado,
        "dicas_gerais": DICAS_GERAIS,
    })


@app.get("/api/assistant/deals/<deal_id>")
@login_required
def assistant_deal_detail(deal_id):
    db = get_db()
    d = db.execute("""
        SELECT deals.*, customers.nome as cliente_nome FROM deals
        JOIN customers ON customers.id = deals.customer_id
        WHERE deals.id = ?
    """, (deal_id,)).fetchone()
    if not d:
        return jsonify({"error": "Negócio não encontrado."}), 404
    if g.current_user["role"] != "admin" and d["user_id"] != g.current_user["id"]:
        return jsonify({"error": "Sem permissão para ver este negócio."}), 403
    customer = db.execute("SELECT * FROM customers WHERE id = ?", (d["customer_id"],)).fetchone()
    tasks = db.execute("SELECT * FROM tasks WHERE deal_id = ?", (d["id"],)).fetchall()
    score, recomendacoes = build_deal_recommendation(d, customer, tasks)
    return jsonify({
        "deal_id": d["id"], "titulo": d["titulo"], "cliente_nome": d["cliente_nome"],
        "score": score, "recomendacoes": recomendacoes,
    })


# ------------------------------------------------------------------
# Rotas — Tasks
# ------------------------------------------------------------------
@app.get("/api/tasks")
@login_required
def list_tasks():
    db = get_db()
    clause, params = scope_filter_clause("user_id")
    rows = db.execute(f"""
        SELECT t.*, c.nome as cliente_nome, u.nome as vendedor_nome FROM tasks t
        LEFT JOIN customers c ON c.id = t.customer_id
        LEFT JOIN users u ON u.id = t.user_id
        WHERE 1=1 {clause}
        ORDER BY t.executado ASC, t.data_lembrete ASC
    """, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/tasks")
@login_required
def create_task():
    body = request.get_json(force=True, silent=True) or {}
    if not body.get("descricao") or not body.get("data_lembrete"):
        return jsonify({"error": "descricao e data_lembrete são obrigatórios."}), 400
    db = get_db()

    # Se a tarefa está vinculada a um cliente ou negócio, ele precisa pertencer ao usuário
    # (a não ser que seja admin) — evita plantar compromissos na carteira de outro vendedor.
    if body.get("customer_id") and g.current_user["role"] != "admin":
        cliente = db.execute("SELECT * FROM customers WHERE id = ?", (body["customer_id"],)).fetchone()
        if not cliente or cliente["responsavel_id"] != g.current_user["id"]:
            return jsonify({"error": "Você só pode criar compromissos para os seus próprios clientes."}), 403
    if body.get("deal_id") and g.current_user["role"] != "admin":
        deal = db.execute("SELECT * FROM deals WHERE id = ?", (body["deal_id"],)).fetchone()
        if not deal or deal["user_id"] != g.current_user["id"]:
            return jsonify({"error": "Você só pode criar compromissos para os seus próprios negócios."}), 403

    # Vendedor só pode criar compromisso para si mesmo; só admin pode atribuir a outro usuário.
    user_id = body.get("user_id", g.current_user["id"])
    if g.current_user["role"] != "admin":
        user_id = g.current_user["id"]

    tid = new_id()
    tipo_atividade = body.get("tipo_atividade", "outro")
    if tipo_atividade not in ("reuniao", "proposta", "follow_up", "ligacao", "email", "outro"):
        tipo_atividade = "outro"
    db.execute("""
        INSERT INTO tasks (id, deal_id, customer_id, user_id, descricao, tipo_atividade, data_lembrete)
        VALUES (?,?,?,?,?,?,?)
    """, (tid, body.get("deal_id"), body.get("customer_id"), user_id,
          body["descricao"], tipo_atividade, body["data_lembrete"]))
    audit("create", "tasks", tid, body)
    db.commit()
    return jsonify({"id": tid}), 201


@app.post("/api/tasks/<task_id>/complete")
@login_required
def complete_task(task_id):
    db = get_db()
    existing = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Compromisso não encontrado."}), 404
    if g.current_user["role"] != "admin" and existing["user_id"] != g.current_user["id"]:
        return jsonify({"error": "Sem permissão para concluir este compromisso."}), 403
    body = request.get_json(force=True, silent=True) or {}
    nota = (body.get("nota_conclusao") or "").strip() or None
    if nota and len(nota) > 2000:
        return jsonify({"error": "A anotação é longa demais (máximo de 2.000 caracteres)."}), 400
    db.execute("UPDATE tasks SET executado = 1, executado_em = ?, nota_conclusao = ? WHERE id = ?",
               (now_iso(), nota, task_id))
    audit("update", "tasks", task_id, {"executado": True, "com_nota": bool(nota)})
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/tasks/excluir")
@login_required
def delete_completed_tasks():
    """Exclui em lote compromissos JÁ CONCLUÍDOS — limpeza da lista e do
    banco. Vendedor só exclui os próprios; admin exclui qualquer um.
    Compromissos pendentes nunca são excluídos por esta rota (a cláusula
    executado = 1 garante isso mesmo se o id de um pendente for enviado)."""
    body = request.get_json(force=True, silent=True) or {}
    ids = body.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "Informe a lista de compromissos a excluir."}), 400
    if len(ids) > 500:
        return jsonify({"error": "Exclua no máximo 500 compromissos por vez."}), 400
    db = get_db()
    placeholders = ",".join("?" * len(ids))
    params = list(ids)
    filtro_dono = ""
    if g.current_user["role"] != "admin":
        filtro_dono = " AND user_id = ?"
        params.append(g.current_user["id"])
    cur = db.execute(
        f"DELETE FROM tasks WHERE id IN ({placeholders}) AND executado = 1{filtro_dono}",
        params,
    )
    audit("delete", "tasks", "lote", {"solicitadas": len(ids), "excluidas": cur.rowcount})
    db.commit()
    return jsonify({"excluidas": cur.rowcount})


# ------------------------------------------------------------------
# Rotas — Users (admin)
# ------------------------------------------------------------------
@app.get("/api/users")
@login_required
@admin_required
def list_users():
    db = get_db()
    rows = db.execute("SELECT id, nome, email, role, ativo FROM users ORDER BY nome").fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/users")
@login_required
@admin_required
def create_user():
    body = request.get_json(force=True, silent=True) or {}
    for f in ("nome", "email", "senha", "role"):
        if not body.get(f):
            return jsonify({"error": f"Campo '{f}' é obrigatório."}), 400
    if body["role"] not in ("admin", "vendedor"):
        return jsonify({"error": "role inválida."}), 400
    db = get_db()
    uid = new_id()
    try:
        db.execute("""
            INSERT INTO users (id, nome, email, senha_hash, role) VALUES (?,?,?,?,?)
        """, (uid, body["nome"], body["email"].lower(), generate_password_hash(body["senha"]), body["role"]))
    except sqlite3.IntegrityError:
        return jsonify({"error": "Já existe um usuário com esse email."}), 409
    audit("create", "users", uid, {"nome": body["nome"], "role": body["role"]})
    db.commit()
    return jsonify({"id": uid}), 201


@app.delete("/api/users/<user_id>")
@login_required
@admin_required
def deactivate_user(user_id):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        return jsonify({"error": "Usuário não encontrado."}), 404
    if target["role"] == "admin" and target["ativo"] == 1:
        if active_admin_count(db, exclude_user_id=user_id) < 2:
            return jsonify({"error": "O sistema deve manter no mínimo 2 administradores ativos."}), 409
    db.execute("UPDATE users SET ativo = 0 WHERE id = ?", (user_id,))
    audit("delete", "users", user_id)
    db.commit()
    return jsonify({"ok": True})


@app.put("/api/users/<user_id>")
@login_required
@admin_required
def update_user(user_id):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        return jsonify({"error": "Usuário não encontrado."}), 404
    body = request.get_json(force=True, silent=True) or {}

    nome = body.get("nome", target["nome"])
    email = (body.get("email", target["email"]) or "").lower()
    role = body.get("role", target["role"])
    ativo_raw = body.get("ativo", target["ativo"])
    ativo = 1 if ativo_raw in (1, "1", True, "true") else 0

    if role not in ("admin", "vendedor"):
        return jsonify({"error": "role inválida."}), 400

    # Se isso tira o usuário da condição de admin ativo, valida a trava dos 2 admins
    deixa_de_ser_admin_ativo = target["role"] == "admin" and target["ativo"] == 1 and (role != "admin" or ativo == 0)
    if deixa_de_ser_admin_ativo and active_admin_count(db, exclude_user_id=user_id) < 2:
        return jsonify({"error": "O sistema deve manter no mínimo 2 administradores ativos."}), 409

    updates = {"nome": nome, "email": email, "role": role, "ativo": ativo}
    if body.get("senha"):
        updates["senha_hash"] = generate_password_hash(body["senha"])

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    try:
        db.execute(f"UPDATE users SET {set_clause}, updated_at = ? WHERE id = ?",
                   (*updates.values(), now_iso(), user_id))
    except sqlite3.IntegrityError:
        return jsonify({"error": "Já existe um usuário com esse email."}), 409

    audit("update", "users", user_id, {k: v for k, v in body.items() if k != "senha"})
    db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------
# Rotas — Tarefas Delegadas (admin atribui, vendedor conduz o fluxo)
# ------------------------------------------------------------------
DELEGATED_STATUS = ("aberta", "em_andamento", "finalizada")


@app.get("/api/delegated-tasks")
@login_required
def list_delegated_tasks():
    db = get_db()
    base_query = """
        SELECT dt.*, u.nome as atribuido_nome, cr.nome as criado_por_nome, c.nome as cliente_nome
        FROM delegated_tasks dt
        JOIN users u ON u.id = dt.atribuido_para
        JOIN users cr ON cr.id = dt.criado_por
        LEFT JOIN customers c ON c.id = dt.customer_id
    """
    if g.current_user["role"] == "admin":
        atribuido = request.args.get("atribuido_para")
        if atribuido:
            rows = db.execute(base_query + " WHERE dt.atribuido_para = ? ORDER BY dt.created_at DESC",
                               (atribuido,)).fetchall()
        else:
            rows = db.execute(base_query + " ORDER BY dt.created_at DESC").fetchall()
    else:
        rows = db.execute(base_query + " WHERE dt.atribuido_para = ? ORDER BY dt.created_at DESC",
                           (g.current_user["id"],)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/delegated-tasks")
@login_required
@admin_required
def create_delegated_task():
    body = request.get_json(force=True, silent=True) or {}
    if not body.get("titulo"):
        return jsonify({"error": "titulo é obrigatório."}), 400
    db = get_db()

    # Delegação em grupo: 'vendedores' (só a equipe de vendas) ou 'todos'
    # (equipe completa, incluindo administradores). Cada pessoa recebe a
    # própria cópia, identificada pelo mesmo grupo_id, e conduz o fluxo
    # de forma independente. 'atribuir_todos' é aceito por compatibilidade
    # com a versão anterior (equivale a 'vendedores').
    equipe = body.get("atribuir_equipe") or ("vendedores" if body.get("atribuir_todos") else None)
    if equipe:
        if equipe not in ("vendedores", "todos"):
            return jsonify({"error": "Grupo inválido: use 'vendedores' ou 'todos'."}), 400
        if equipe == "todos":
            destinatarios = db.execute("SELECT id FROM users WHERE ativo = 1").fetchall()
        else:
            destinatarios = db.execute(
                "SELECT id FROM users WHERE role = 'vendedor' AND ativo = 1"
            ).fetchall()
        if not destinatarios:
            return jsonify({"error": "Não há usuários ativos para atribuir a tarefa."}), 400
        grupo_id = new_id()
        ids_criados = []
        for u in destinatarios:
            tid = new_id()
            db.execute("""
                INSERT INTO delegated_tasks (id, titulo, descricao, criado_por, atribuido_para, customer_id, data_prazo, grupo_id)
                VALUES (?,?,?,?,?,?,?,?)
            """, (tid, body["titulo"], body.get("descricao"), g.current_user["id"], u["id"],
                  body.get("customer_id"), body.get("data_prazo"), grupo_id))
            ids_criados.append(tid)
        audit("create", "delegated_tasks", grupo_id, {**body, "equipe": equipe, "qtd": len(ids_criados)})
        db.commit()
        return jsonify({"grupo_id": grupo_id, "ids": ids_criados, "qtd_atribuidos": len(ids_criados)}), 201

    if not body.get("atribuido_para"):
        return jsonify({"error": "Escolha um responsável ou uma das opções de equipe."}), 400
    destino = db.execute("SELECT id FROM users WHERE id = ? AND ativo = 1",
                         (body["atribuido_para"],)).fetchone()
    if not destino:
        return jsonify({"error": "Responsável inválido ou inativo."}), 400
    tid = new_id()
    db.execute("""
        INSERT INTO delegated_tasks (id, titulo, descricao, criado_por, atribuido_para, customer_id, data_prazo)
        VALUES (?,?,?,?,?,?,?)
    """, (tid, body["titulo"], body.get("descricao"), g.current_user["id"], body["atribuido_para"],
          body.get("customer_id"), body.get("data_prazo")))
    audit("create", "delegated_tasks", tid, body)
    db.commit()
    return jsonify({"id": tid}), 201


@app.put("/api/delegated-tasks/<task_id>")
@login_required
@admin_required
def update_delegated_task(task_id):
    db = get_db()
    t = db.execute("SELECT * FROM delegated_tasks WHERE id = ?", (task_id,)).fetchone()
    if not t:
        return jsonify({"error": "Tarefa não encontrada."}), 404
    body = request.get_json(force=True, silent=True) or {}
    titulo = body.get("titulo", t["titulo"])
    descricao = body.get("descricao", t["descricao"])
    atribuido = body.get("atribuido_para", t["atribuido_para"])
    prazo = body.get("data_prazo", t["data_prazo"])
    db.execute("""
        UPDATE delegated_tasks SET titulo=?, descricao=?, atribuido_para=?, data_prazo=?, updated_at=?
        WHERE id=?
    """, (titulo, descricao, atribuido, prazo, now_iso(), task_id))
    audit("update", "delegated_tasks", task_id, body)
    db.commit()
    return jsonify({"ok": True})


@app.put("/api/delegated-tasks/<task_id>/status")
@login_required
def update_delegated_task_status(task_id):
    db = get_db()
    t = db.execute("SELECT * FROM delegated_tasks WHERE id = ?", (task_id,)).fetchone()
    if not t:
        return jsonify({"error": "Tarefa não encontrada."}), 404
    if g.current_user["role"] != "admin" and t["atribuido_para"] != g.current_user["id"]:
        return jsonify({"error": "Sem permissão para atualizar esta tarefa."}), 403

    body = request.get_json(force=True, silent=True) or {}
    novo_status = body.get("status")
    if novo_status not in DELEGATED_STATUS:
        return jsonify({"error": "Status inválido."}), 400

    descricao_conclusao = body.get("descricao_conclusao", t["descricao_conclusao"])
    if novo_status == "finalizada" and not (descricao_conclusao or "").strip():
        return jsonify({"error": "Descreva brevemente o que foi feito para finalizar a tarefa."}), 400

    finalizada_em = now_iso() if novo_status == "finalizada" else t["finalizada_em"]
    db.execute("""
        UPDATE delegated_tasks SET status = ?, descricao_conclusao = ?, finalizada_em = ?, updated_at = ?
        WHERE id = ?
    """, (novo_status, descricao_conclusao, finalizada_em, now_iso(), task_id))
    audit("update", "delegated_tasks", task_id, {"status": novo_status})
    db.commit()
    return jsonify({"ok": True})


@app.get("/api/lembretes")
@login_required
def list_lembretes():
    """Lembretes pessoais de tarefas para o Feed de Alertas. São SEMPRE do
    próprio usuário logado — por isso as regras de visibilidade se resolvem
    sozinhas: vendedor vê os próprios compromissos e as tarefas que o admin
    delegou a ele; admin vê as suas (inclusive as trocadas entre admins);
    ninguém vê lembrete de outra pessoa.
    - Compromissos: os que vencem nas próximas 24h. Os já vencidos NÃO
      entram aqui — viram o alerta 'compromisso esquecido' pelo motor de
      alertas, sem duplicar.
    - Delegadas: pendentes com prazo até amanhã, incluindo as vencidas
      (que o motor de alertas não cobre)."""
    db = get_db()
    uid = g.current_user["id"]
    agora = now_iso()
    limite_24h = (datetime.now(timezone.utc) + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    compromissos = db.execute("""
        SELECT t.*, c.nome as cliente_nome FROM tasks t
        LEFT JOIN customers c ON c.id = t.customer_id
        WHERE t.user_id = ? AND t.executado = 0
          AND t.data_lembrete > ? AND t.data_lembrete <= ?
        ORDER BY t.data_lembrete
    """, (uid, agora, limite_24h)).fetchall()
    ate_amanha = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    delegadas = db.execute("""
        SELECT dt.*, cr.nome as criado_por_nome, c.nome as cliente_nome
        FROM delegated_tasks dt
        JOIN users cr ON cr.id = dt.criado_por
        LEFT JOIN customers c ON c.id = dt.customer_id
        WHERE dt.atribuido_para = ? AND dt.status != 'finalizada'
          AND dt.data_prazo IS NOT NULL AND dt.data_prazo <= ?
        ORDER BY dt.data_prazo
    """, (uid, ate_amanha)).fetchall()
    return jsonify({
        "hoje": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "compromissos": [dict(r) for r in compromissos],
        "delegadas": [dict(r) for r in delegadas],
    })


# ------------------------------------------------------------------
# Rotas — Relatórios Gerenciais
# Regra de visibilidade: vendedor só vê o próprio relatório (a API nem aceita
# vendedor_id/scope=all de quem não é admin). Admin vê o próprio por padrão,
# um vendedor específico via ?vendedor_id=, ou todo mundo via ?scope=all.
# ------------------------------------------------------------------
ORIGENS_VALIDAS = ("Outbound", "LinkedIn", "Indicações", "Eventos", "Inbound", "Outro")

MOTIVO_PERDA_LABEL = {
    "preco": "Preço", "concorrente": "Concorrente", "falta_funcionalidade": "Falta de funcionalidade/serviço",
    "sumiu_no_show": "Sumiu/não respondeu (no-show)", "sem_orcamento": "Sem orçamento",
    "timing_errado": "Timing errado", "outro": "Outro",
}

ETAPA_PROBABILIDADE = {"novo_lead": 0.15, "qualificacao": 0.35, "proposta_enviada": 0.55, "negociacao": 0.75}


@app.get("/api/reports/pipeline")
@login_required
def report_pipeline():
    db = get_db()
    campo_data = request.args.get("campo_data")  # "criacao" | "previsao" | None (foto atual)
    clause, params = report_scope_clause("user_id")

    filtro_data = ""
    if campo_data in ("criacao", "previsao"):
        try:
            inicio, fim = parse_period_from_request()
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if inicio and fim:
            col = "created_at" if campo_data == "criacao" else "data_prevista_fechamento"
            filtro_data = f" AND {col} BETWEEN ? AND ?"
            params = params + [inicio, fim + " 23:59:59"]

    rows = db.execute(f"""
        SELECT etapa_funil, COUNT(*) as quantidade, COALESCE(SUM(valor_estimado),0) as valor_total
        FROM deals WHERE status = 'aberto' {clause}{filtro_data}
        GROUP BY etapa_funil
    """, params).fetchall()
    por_etapa = {r["etapa_funil"]: dict(r) for r in rows}
    resultado = []
    for etapa in ETAPAS_ABERTAS:
        r = por_etapa.get(etapa, {"quantidade": 0, "valor_total": 0})
        qtd = r["quantidade"]
        resultado.append({
            "etapa": etapa, "etapa_label": ETAPA_LABEL_BACKEND[etapa],
            "quantidade": qtd, "valor_total": r["valor_total"],
            "ticket_medio": (r["valor_total"] / qtd) if qtd else 0,
        })
    return jsonify({"etapas": resultado})


@app.get("/api/reports/desempenho-equipe")
@login_required
def report_desempenho_equipe():
    db = get_db()
    try:
        inicio, fim = parse_period_from_request()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not inicio:
        return jsonify({"error": "Informe o parâmetro 'periodo' para este relatório."}), 400
    clause, params = report_scope_clause("user_id")

    rows = db.execute(f"""
        SELECT deals.*, u.nome as vendedor_nome FROM deals
        LEFT JOIN users u ON u.id = deals.user_id
        WHERE status IN ('ganho','perdido') AND etapa_atualizada_em BETWEEN ? AND ? {clause}
    """, [inicio, fim + " 23:59:59"] + params).fetchall()

    por_vendedor = {}
    for d in rows:
        vid = d["user_id"]
        if vid not in por_vendedor:
            por_vendedor[vid] = {
                "vendedor_id": vid, "vendedor_nome": d["vendedor_nome"],
                "ganhos": 0, "perdidos": 0, "valor_ganho_total": 0.0, "valor_perdido_total": 0.0,
                "_dias_ciclo": [],
            }
        v = por_vendedor[vid]
        criado = datetime.strptime(d["created_at"], "%Y-%m-%d %H:%M:%S")
        fechado = datetime.strptime(d["etapa_atualizada_em"], "%Y-%m-%d %H:%M:%S")
        if d["status"] == "ganho":
            v["ganhos"] += 1
            v["valor_ganho_total"] += d["valor_estimado"] or 0
            v["_dias_ciclo"].append((fechado - criado).total_seconds() / 86400)
        else:
            v["perdidos"] += 1
            v["valor_perdido_total"] += d["valor_estimado"] or 0

    resultado = []
    for v in por_vendedor.values():
        total = v["ganhos"] + v["perdidos"]
        dias = v.pop("_dias_ciclo")
        resultado.append({
            **v,
            "taxa_conversao": round(v["ganhos"] / total * 100, 1) if total else 0,
            "ciclo_medio_dias": round(sum(dias) / len(dias), 1) if dias else None,
            "ticket_medio_ganho": round(v["valor_ganho_total"] / v["ganhos"], 2) if v["ganhos"] else 0,
        })
    resultado.sort(key=lambda r: r["valor_ganho_total"], reverse=True)
    return jsonify({"periodo": {"inicio": inicio, "fim": fim}, "vendedores": resultado})


@app.get("/api/reports/motivos-perda")
@login_required
def report_motivos_perda():
    db = get_db()
    try:
        inicio, fim = parse_period_from_request()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not inicio:
        return jsonify({"error": "Informe o parâmetro 'periodo' para este relatório."}), 400
    clause, params = report_scope_clause("user_id")

    rows = db.execute(f"""
        SELECT motivo_perda, COUNT(*) as quantidade, COALESCE(SUM(valor_estimado),0) as valor_total
        FROM deals
        WHERE status = 'perdido' AND etapa_atualizada_em BETWEEN ? AND ? {clause}
        GROUP BY motivo_perda
        ORDER BY quantidade DESC
    """, [inicio, fim + " 23:59:59"] + params).fetchall()

    total_perdidos = sum(r["quantidade"] for r in rows)
    resultado = [{
        "motivo": r["motivo_perda"] or "nao_informado",
        "motivo_label": MOTIVO_PERDA_LABEL.get(r["motivo_perda"], "Não informado"),
        "quantidade": r["quantidade"], "valor_total": r["valor_total"],
        "percentual": round(r["quantidade"] / total_perdidos * 100, 1) if total_perdidos else 0,
    } for r in rows]
    return jsonify({"periodo": {"inicio": inicio, "fim": fim}, "total_perdidos": total_perdidos, "motivos": resultado})


@app.get("/api/reports/atividades")
@login_required
def report_atividades():
    db = get_db()
    try:
        inicio, fim = parse_period_from_request()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not inicio:
        return jsonify({"error": "Informe o parâmetro 'periodo' para este relatório."}), 400
    clause_tasks, params_tasks = report_scope_clause("user_id")
    clause_hist, params_hist = report_scope_clause("user_id")

    reunioes_agendadas = db.execute(f"""
        SELECT user_id, COUNT(*) c FROM tasks
        WHERE tipo_atividade = 'reuniao' AND created_at BETWEEN ? AND ? {clause_tasks}
        GROUP BY user_id
    """, [inicio, fim + " 23:59:59"] + params_tasks).fetchall()

    reunioes_realizadas = db.execute(f"""
        SELECT user_id, COUNT(*) c FROM tasks
        WHERE tipo_atividade = 'reuniao' AND executado = 1 AND executado_em BETWEEN ? AND ? {clause_tasks}
        GROUP BY user_id
    """, [inicio, fim + " 23:59:59"] + params_tasks).fetchall()

    follow_ups = db.execute(f"""
        SELECT user_id, COUNT(*) c FROM tasks
        WHERE tipo_atividade = 'follow_up' AND executado = 1 AND executado_em BETWEEN ? AND ? {clause_tasks}
        GROUP BY user_id
    """, [inicio, fim + " 23:59:59"] + params_tasks).fetchall()

    propostas = db.execute(f"""
        SELECT user_id, COUNT(*) c FROM deal_stage_history
        WHERE etapa_nova = 'proposta_enviada' AND data_transicao BETWEEN ? AND ? {clause_hist}
        GROUP BY user_id
    """, [inicio, fim + " 23:59:59"] + params_hist).fetchall()

    usuarios = {u["id"]: u["nome"] for u in db.execute("SELECT id, nome FROM users").fetchall()}
    por_vendedor = {}

    def _acumular(rows, campo):
        for r in rows:
            vid = r["user_id"]
            if vid not in por_vendedor:
                por_vendedor[vid] = {
                    "vendedor_id": vid, "vendedor_nome": usuarios.get(vid, "—"),
                    "reunioes_agendadas": 0, "reunioes_realizadas": 0,
                    "propostas_enviadas": 0, "follow_ups_realizados": 0,
                }
            por_vendedor[vid][campo] = r["c"]

    _acumular(reunioes_agendadas, "reunioes_agendadas")
    _acumular(reunioes_realizadas, "reunioes_realizadas")
    _acumular(propostas, "propostas_enviadas")
    _acumular(follow_ups, "follow_ups_realizados")

    resultado = sorted(por_vendedor.values(), key=lambda r: r["vendedor_nome"] or "")
    return jsonify({"periodo": {"inicio": inicio, "fim": fim}, "vendedores": resultado})


@app.get("/api/reports/forecast")
@login_required
def report_forecast():
    db = get_db()
    try:
        inicio, fim = parse_period_from_request()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not inicio:
        return jsonify({"error": "Informe o parâmetro 'periodo' — o forecast é filtrado pela data prevista de fechamento."}), 400
    clause, params = report_scope_clause("user_id")

    rows = db.execute(f"""
        SELECT deals.*, c.nome as cliente_nome, u.nome as vendedor_nome FROM deals
        JOIN customers c ON c.id = deals.customer_id
        LEFT JOIN users u ON u.id = deals.user_id
        WHERE status = 'aberto' AND data_prevista_fechamento BETWEEN ? AND ? {clause}
        ORDER BY data_prevista_fechamento
    """, [inicio, fim] + params).fetchall()

    negocios = []
    valor_bruto_total = 0.0
    valor_ponderado_total = 0.0
    for d in rows:
        prob = ETAPA_PROBABILIDADE.get(d["etapa_funil"], 0)
        ponderado = (d["valor_estimado"] or 0) * prob
        valor_bruto_total += d["valor_estimado"] or 0
        valor_ponderado_total += ponderado
        negocios.append({
            "deal_id": d["id"], "titulo": d["titulo"], "cliente_nome": d["cliente_nome"],
            "vendedor_nome": d["vendedor_nome"], "etapa_funil": d["etapa_funil"],
            "valor_estimado": d["valor_estimado"], "probabilidade": prob, "valor_ponderado": round(ponderado, 2),
            "data_prevista_fechamento": d["data_prevista_fechamento"],
        })
    return jsonify({
        "periodo": {"inicio": inicio, "fim": fim},
        "valor_bruto_total": valor_bruto_total, "valor_ponderado_total": round(valor_ponderado_total, 2),
        "quantidade": len(negocios), "negocios": negocios,
    })


@app.get("/api/reports/origem-leads")
@login_required
def report_origem_leads():
    db = get_db()
    try:
        inicio, fim = parse_period_from_request()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not inicio:
        return jsonify({"error": "Informe o parâmetro 'periodo' para este relatório."}), 400
    clause, params = report_scope_clause("responsavel_id")

    clientes = db.execute(f"""
        SELECT id, origem FROM customers
        WHERE created_at BETWEEN ? AND ? {clause}
    """, [inicio, fim + " 23:59:59"] + params).fetchall()

    por_origem = {}
    for c in clientes:
        origem = c["origem"] or "Não informado"
        por_origem.setdefault(origem, {"origem": origem, "quantidade_leads": 0, "customer_ids": []})
        por_origem[origem]["quantidade_leads"] += 1
        por_origem[origem]["customer_ids"].append(c["id"])

    for origem, dados in por_origem.items():
        ids = dados.pop("customer_ids")
        if not ids:
            dados["quantidade_ganhos"] = 0
            dados["valor_total_ganho"] = 0
            dados["ticket_medio"] = 0
            continue
        placeholders = ",".join("?" for _ in ids)
        ganhos = db.execute(f"""
            SELECT COUNT(*) qtd, COALESCE(SUM(valor_estimado),0) valor
            FROM deals WHERE status = 'ganho' AND customer_id IN ({placeholders})
        """, ids).fetchone()
        dados["quantidade_ganhos"] = ganhos["qtd"]
        dados["valor_total_ganho"] = ganhos["valor"]
        dados["ticket_medio"] = round(ganhos["valor"] / ganhos["qtd"], 2) if ganhos["qtd"] else 0

    resultado = sorted(por_origem.values(), key=lambda r: r["valor_total_ganho"], reverse=True)
    return jsonify({"periodo": {"inicio": inicio, "fim": fim}, "origens": resultado})


# ------------------------------------------------------------------
# Rotas — Canal de notificação WhatsApp (apenas número de saída, sem leitura)
# ------------------------------------------------------------------
@app.get("/api/whatsapp/channels")
@login_required
def list_whatsapp_channels():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM whatsapp_notification_channels WHERE user_id = ? ORDER BY created_at DESC",
        (g.current_user["id"],)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/whatsapp/channels")
@login_required
def create_whatsapp_channel():
    body = request.get_json(force=True, silent=True) or {}
    numero = (body.get("numero_whatsapp") or "").strip()
    if not numero:
        return jsonify({"error": "Informe o número de WhatsApp."}), 400
    db = get_db()
    cid = new_id()
    db.execute("""
        INSERT INTO whatsapp_notification_channels (id, user_id, numero_whatsapp, provedor)
        VALUES (?,?,?,?)
    """, (cid, g.current_user["id"], numero, body.get("provedor", "whatsapp_cloud_api")))
    audit("create", "whatsapp_notification_channels", cid, body)
    db.commit()
    return jsonify({"id": cid}), 201


@app.delete("/api/whatsapp/channels/<channel_id>")
@login_required
def delete_whatsapp_channel(channel_id):
    db = get_db()
    db.execute(
        "DELETE FROM whatsapp_notification_channels WHERE id = ? AND user_id = ?",
        (channel_id, g.current_user["id"])
    )
    audit("delete", "whatsapp_notification_channels", channel_id)
    db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------
# Frontend estático
# ------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "dashboard.html")


# ------------------------------------------------------------------
# Bootstrap: cria schema + seed se o banco não existir
# ------------------------------------------------------------------
def migrate_missing_columns(conn):
    """Adiciona colunas novas em bancos criados por versões anteriores do app,
    sem apagar nenhum dado já cadastrado."""
    tabelas_e_colunas = {
        "customers": {
            "cpf_cnpj": "TEXT", "endereco": "TEXT", "cep": "TEXT", "cidade": "TEXT", "estado": "TEXT",
            "ativo": "INTEGER NOT NULL DEFAULT 1",
        },
        "delegated_tasks": {
            "grupo_id": "TEXT",
        },
        "deals": {
            "data_prevista_fechamento": "TEXT", "motivo_perda": "TEXT", "motivo_perda_detalhe": "TEXT",
        },
        "tasks": {
            "tipo_atividade": "TEXT NOT NULL DEFAULT 'outro'",
            "nota_conclusao": "TEXT",
        },
        "deal_notes": {
            "tipo": "TEXT NOT NULL DEFAULT 'nota'",
            "tem_anexo": "INTEGER NOT NULL DEFAULT 0",
        },
        "deal_stage_history": {
            "motivo_perda": "TEXT",
            "motivo_perda_detalhe": "TEXT",
        },
        "customers": {
            "recompra_dias": "INTEGER",
            "proxima_recompra": "TEXT",
        },
        "deals": {
            "origem_recompra": "INTEGER NOT NULL DEFAULT 0",
        },
    }
    for tabela, colunas in tabelas_e_colunas.items():
        colunas_existentes = {row["name"] for row in conn.execute(f"PRAGMA table_info({tabela})").fetchall()}
        for coluna, tipo in colunas.items():
            if coluna not in colunas_existentes:
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")


def init_db_if_needed():
    fresh = False
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    with open("schema.sql", encoding="utf-8") as f:
        conn.executescript(f.read())
    migrate_missing_columns(conn)
    already_seeded = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] > 0
    if not already_seeded:
        fresh = True
        seed(conn)
    conn.commit()
    conn.close()
    return fresh


def seed(conn):
    def uid():
        return uuid.uuid4().hex

    admin1, admin2 = uid(), uid()
    carlos_vendas, ana, tiago = uid(), uid(), uid()

    conn.execute("INSERT INTO users (id, nome, email, senha_hash, role) VALUES (?,?,?,?,?)",
                 (admin1, "Admin Master 1", "admin1@digimagem.com", generate_password_hash("admin123"), "admin"))
    conn.execute("INSERT INTO users (id, nome, email, senha_hash, role) VALUES (?,?,?,?,?)",
                 (admin2, "Admin Master 2", "admin2@digimagem.com", generate_password_hash("admin123"), "admin"))
    conn.execute("INSERT INTO users (id, nome, email, senha_hash, role) VALUES (?,?,?,?,?)",
                 (carlos_vendas, "Carlos", "carlos.vendas@lojadigimagem.com.br", generate_password_hash("vendas123"), "vendedor"))
    conn.execute("INSERT INTO users (id, nome, email, senha_hash, role) VALUES (?,?,?,?,?)",
                 (ana, "Ana", "ana@lojadigimagem.com.br", generate_password_hash("vendas123"), "vendedor"))
    conn.execute("INSERT INTO users (id, nome, email, senha_hash, role) VALUES (?,?,?,?,?)",
                 (tiago, "Tiago", "tiago@lojadigimagem.com.br", generate_password_hash("vendas123"), "vendedor"))

    def add_customer(nome, whatsapp, status, dias_sem_comprar, responsavel, origem="Indicações"):
        cid = uid()
        data_compra = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=dias_sem_comprar)).strftime("%Y-%m-%d") if dias_sem_comprar is not None else None
        conn.execute("""
            INSERT INTO customers (id, nome, whatsapp_id, data_ultima_compra, status_fidelidade, responsavel_id, origem)
            VALUES (?,?,?,?,?,?,?)
        """, (cid, nome, whatsapp, data_compra, status, responsavel, origem))
        return cid

    joao = add_customer("João Pereira", "5548999990001", "vip", 18, carlos_vendas, "Indicações")
    studio_nova = add_customer("Studio Nova", "5548999990002", "recorrente", 46, ana, "LinkedIn")
    bruno = add_customer("Bruno Lima", "5548999990003", "novo", None, carlos_vendas, "Inbound")
    fernanda = add_customer("Fernanda Dias", "5548999990004", "novo", None, ana, "Outbound")
    atelie = add_customer("Ateliê Prime", "5548999990005", "vip", 5, tiago, "Eventos")
    ricardo = add_customer("Ricardo Alves", "5548999990006", "novo", None, tiago, "LinkedIn")
    perdida1 = add_customer("Contatos Perdidos ME", "5548999990007", "perdido", None, carlos_vendas, "Outbound")
    ganha1 = add_customer("Foto Prime Estúdio", "5548999990008", "recorrente", None, tiago, "Indicações")

    def add_deal(customer_id, user_id, titulo, etapa, valor, horas_parado=0, status="aberto",
                 motivo_perda=None, dias_previsao=None, dias_atras_fechamento=None):
        did = uid()
        if dias_atras_fechamento is not None:
            etapa_ts = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=dias_atras_fechamento)).strftime("%Y-%m-%d %H:%M:%S")
            criado_ts = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=dias_atras_fechamento + 12)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            etapa_ts = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=horas_parado)).strftime("%Y-%m-%d %H:%M:%S")
            criado_ts = etapa_ts
        previsao = (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=dias_previsao)).strftime("%Y-%m-%d") if dias_previsao is not None else None
        conn.execute("""
            INSERT INTO deals (id, customer_id, user_id, titulo, etapa_funil, valor_estimado, status,
                etapa_atualizada_em, created_at, data_prevista_fechamento, motivo_perda)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (did, customer_id, user_id, titulo, etapa, valor, status, etapa_ts, criado_ts, previsao, motivo_perda))
        conn.execute("""
            INSERT INTO deal_stage_history (id, deal_id, etapa_anterior, etapa_nova, user_id, data_transicao)
            VALUES (?,?,NULL,?,?,?)
        """, (uid(), did, etapa, user_id, criado_ts))
        if etapa != "novo_lead" and dias_atras_fechamento is None:
            # registra também a passagem por "proposta_enviada" pra alimentar o relatório de atividades
            conn.execute("""
                INSERT INTO deal_stage_history (id, deal_id, etapa_anterior, etapa_nova, user_id, data_transicao)
                VALUES (?,?,?,?,?,?)
            """, (uid(), did, "novo_lead", etapa, user_id, etapa_ts))
        return did

    deal_joao = add_deal(joao, carlos_vendas, "Ensaio corporativo — João Pereira", "qualificacao", 7400, horas_parado=52, dias_previsao=10)
    add_deal(bruno, carlos_vendas, "Pacote casamento — Bruno Lima", "proposta_enviada", 6200, horas_parado=61, dias_previsao=5)
    add_deal(studio_nova, ana, "Contrato mensal — Studio Nova", "negociacao", 12000, horas_parado=10, dias_previsao=15)
    add_deal(fernanda, ana, "Book individual — Fernanda Dias", "novo_lead", 3200, horas_parado=6)
    add_deal(atelie, tiago, "Catálogo produtos — Ateliê Prime", "negociacao", 18500, horas_parado=20, dias_previsao=8)
    add_deal(ricardo, tiago, "Ensaio família — Ricardo Alves", "novo_lead", 5900, horas_parado=2)
    # Negócios já fechados, pra alimentar os relatórios de Desempenho, Motivos de Perda e Origem de Leads
    add_deal(perdida1, carlos_vendas, "Cobertura evento — Contatos Perdidos ME", "fechado_perdido", 4500,
              status="perdido", motivo_perda="preco", dias_atras_fechamento=6)
    add_deal(ganha1, tiago, "Ensaio produtos — Foto Prime Estúdio", "fechado_ganho", 8900,
              status="ganho", dias_atras_fechamento=3)

    # task vencida (compromisso esquecido) ligada ao João Pereira
    conn.execute("""
        INSERT INTO tasks (id, deal_id, customer_id, user_id, descricao, tipo_atividade, data_lembrete, executado)
        VALUES (?,?,?,?,?,'follow_up',?,0)
    """, (uid(), deal_joao, joao, carlos_vendas, 'Retornar contato — "te ligo na terça"',
          (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")))

    # task futura, ainda não vencida
    conn.execute("""
        INSERT INTO tasks (id, deal_id, customer_id, user_id, descricao, tipo_atividade, data_lembrete, executado)
        VALUES (?,?,?,?,?,'proposta',?,0)
    """, (uid(), None, atelie, tiago, "Enviar proposta revisada",
          (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")))

    # reunião já realizada, pra alimentar o Relatório de Atividades Comerciais
    conn.execute("""
        INSERT INTO tasks (id, deal_id, customer_id, user_id, descricao, tipo_atividade, data_lembrete, executado, executado_em)
        VALUES (?,?,?,?,?,'reuniao',?,1,?)
    """, (uid(), deal_joao, joao, carlos_vendas, "Reunião de diagnóstico com o cliente",
          (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
          (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")))

    # follow-up já realizado
    conn.execute("""
        INSERT INTO tasks (id, deal_id, customer_id, user_id, descricao, tipo_atividade, data_lembrete, executado, executado_em)
        VALUES (?,?,?,?,?,'follow_up',?,1,?)
    """, (uid(), None, ganha1, tiago, "Follow-up pós-fechamento",
          (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
          (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")))

    conn.commit()


# Roda sempre que o módulo é carregado — tanto no `python app.py` local quanto
# quando o Gunicorn importa `app` em produção (Gunicorn nunca executa o bloco
# `if __name__ == "__main__":` abaixo, então a inicialização precisa estar aqui fora).
_fresh_db = init_db_if_needed()
if _fresh_db:
    print("Banco criado e populado com dados de exemplo (crm.db).")

if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5000))
    modo_debug = os.environ.get("FLASK_DEBUG") == "1"
    print(f"CRM-Digimagem rodando em http://localhost:{porta}")
    app.run(debug=modo_debug, host="0.0.0.0", port=porta, use_reloader=False)
