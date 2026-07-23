"""Testa a v49: edição de quantidade e preço de item do orçamento.

Foco nos cenários que envolvem a liberação de preço (uso único, 7 dias),
que é onde estava a fricção: antes era preciso apagar e refazer o item.
"""
import os, sys, json, sqlite3, tempfile

DB = tempfile.mktemp(suffix=".db")
os.environ["CRM_DB_PATH"] = DB
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import app as A
A.init_db_if_needed()
cli = A.app.test_client()

def login(email, senha):
    r = cli.post("/api/auth/login", json={"email": email, "senha": senha})
    assert r.status_code == 200, r.get_json()
    return {"Authorization": "Bearer " + r.get_json()["token"]}

def q(sql, params=()):
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    r = [dict(x) for x in c.execute(sql, params).fetchall()]
    c.close(); return r

ok, fail = 0, 0
def check(nome, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  ✅ {nome}")
    else:    fail += 1; print(f"  ❌ {nome} {extra}")

hv = login("ana@lojadigimagem.com.br", "vendas123")
ha = login("admin1@digimagem.com", "admin123")

# O catálogo comercial vem da planilha, não do seed. Para o teste rodar em
# qualquer máquina (inclusive no CI, sem o .xlsx), cria-se um produto próprio
# com tabela e limite conhecidos. Se a planilha estiver ao lado, ela é usada.
XLSX = os.path.join(RAIZ, "Base_Comercial_Digimagem.xlsx")
if os.path.exists(XLSX):
    import io
    with open(XLSX, "rb") as f:
        r = cli.post("/api/base-comercial/importar", headers=ha,
                     data={"arquivo": (io.BytesIO(f.read()), "base.xlsx")},
                     content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    print("Planilha importada:", r.get_json())
else:
    c = sqlite3.connect(DB)
    c.execute("""INSERT INTO produtos (id, nome, ativo, categoria, equipamento, embalagem,
                 preco_tabela, preco_limite, ofertavel, desconto_valor)
                 VALUES ('p-teste','Papel de teste 15,2 x 186 m',1,'Papel','DX100','rolo',
                         500.0, 450.0, 1, 0)""")
    c.commit(); c.close()
    print("Produto de teste criado (planilha ausente).")

# --- cenário: produto com piso, negócio aberto da Ana ---
ana = q("SELECT id FROM users WHERE email='ana@lojadigimagem.com.br'")[0]["id"]
prod = q("""SELECT id, nome, preco_tabela, preco_limite FROM produtos
            WHERE ativo=1 AND ofertavel!=0 AND preco_limite IS NOT NULL
              AND preco_tabela > preco_limite LIMIT 1""")[0]
cust = q("SELECT id FROM customers WHERE responsavel_id=? LIMIT 1", (ana,))[0]["id"]
tabela, limite = prod["preco_tabela"], prod["preco_limite"]
print(f"\nProduto: {prod['nome']} · tabela {tabela} · limite {limite}")

r = cli.post("/api/deals", headers=hv, json={
    "titulo": "Teste v49", "customer_id": cust, "categoria": "padrao"})
deal = deal_1 = r.get_json()["id"]

def add(preco, qtd=2):
    return cli.post(f"/api/deals/{deal}/orcamento/itens", headers=hv,
                    json={"produto_id": prod["id"], "qtd": qtd, "preco_unit": preco,
                          "motivo": "teste"}).get_json()

def edit(item, **kw):
    return cli.put(f"/api/deals/{deal}/orcamento/itens/{item}", headers=hv, json=kw)

def item(iid):
    return q("SELECT * FROM deal_itens WHERE id=?", (iid,))[0]

def lib(lid):
    return q("SELECT * FROM liberacoes_preco WHERE id=?", (lid,))[0]

print("\n[1] Item abaixo do piso nasce pendente e gera pedido")
abaixo = round(limite - 10, 2)
i1 = add(abaixo)["id"]
it = item(i1)
check("aprovado = 0", it["aprovado"] == 0)
check("liberacao criada", it["liberacao_id"] is not None)
check("status pendente", lib(it["liberacao_id"])["status"] == "pendente")

print("\n[2] Admin aprova")
lid = it["liberacao_id"]
r = cli.post(f"/api/liberacoes/{lid}/decidir", headers=ha,
             json={"decisao": "aprovar", "preco_autorizado": abaixo})
check("aprovação aceita", r.status_code == 200, r.get_json())
check("item liberado", item(i1)["aprovado"] == 1)

print("\n[3] ⭐ Editar SÓ a quantidade preserva a liberação (o bug que motivou a v49)")
r = edit(i1, qtd=7)
it = item(i1)
check("HTTP 200", r.status_code == 200, r.get_json())
check("qtd atualizada para 7", it["qtd"] == 7, it["qtd"])
check("continua aprovado", it["aprovado"] == 1)
check("mesma liberacao_id", it["liberacao_id"] == lid)
check("liberação NÃO virou pendente", lib(lid)["status"] == "aprovada", lib(lid)["status"])
check("preço intocado", round(it["preco_unit"], 2) == abaixo)
check("nenhum pedido novo", len(q("SELECT id FROM liberacoes_preco WHERE deal_id=?", (deal,))) == 1)

print("\n[4] Aumento de quantidade com liberação fica no audit_log")
aud = q("""SELECT * FROM audit_log WHERE entidade='deal_itens' AND entidade_id=?
           AND acao='update' ORDER BY created_at DESC""", (i1,))
det = json.loads(aud[0]["detalhes"]) if aud else {}
check("registro de update existe", bool(aud))
check("marcado aumento_qtd_com_liberacao", det.get("aumento_qtd_com_liberacao") is True, det)
check("qtd registrada como 2 → 7", det.get("qtd") == "2 → 7", det)

print("\n[5] Valor do negócio sincronizado")
val = q("SELECT valor_estimado FROM deals WHERE id=?", (deal,))[0]["valor_estimado"]
check(f"valor = 7 × {abaixo}", round(val, 2) == round(7 * abaixo, 2), val)

print("\n[6] Baixar o preço ABAIXO do já autorizado exige novo pedido")
r = edit(i1, preco_unit=round(abaixo - 20, 2))
it = item(i1)
check("HTTP 200", r.status_code == 200, r.get_json())
check("volta a pendente", it["aprovado"] == 0)
check("novo pedido criado", it["liberacao_id"] != lid)
check("resposta sinaliza novo_pedido", r.get_json().get("novo_pedido") is True)
check("liberação antiga intacta", lib(lid)["status"] == "aprovada")
novo = it["liberacao_id"]

print("\n[7] Voltar para dentro da autonomia cancela o pedido pendente")
r = edit(i1, preco_unit=tabela)
it = item(i1)
check("aprovado sem pedir nada", it["aprovado"] == 1)
check("pedido pendente cancelado", lib(novo)["status"] == "cancelada", lib(novo)["status"])
check("admin não vê mais como pendente",
      len(q("SELECT id FROM liberacoes_preco WHERE deal_id=? AND status='pendente'", (deal,))) == 0)
check("usou_limite zerado no preço de tabela", it["usou_limite"] == 0)

print("\n[8] Preço abaixo do piso mas coberto pela própria liberação segue aprovado")
deal = cli.post("/api/deals", headers=hv, json={
    "titulo": "Teste v49 — cenário 8", "customer_id": cust, "categoria": "padrao"}).get_json()["id"]
i2 = add(tabela, qtd=1)["id"]                     # item limpo, preço cheio
cli.post(f"/api/deals/{deal}/liberacoes", headers=hv,
         json={"produto_id": prod["id"], "preco_pedido": abaixo, "motivo": "x"})
pend = q("SELECT id FROM liberacoes_preco WHERE deal_id=? AND status='pendente'", (deal,))[0]["id"]
cli.post(f"/api/liberacoes/{pend}/decidir", headers=ha,
         json={"decisao": "aprovar", "preco_autorizado": abaixo})
edit(i2, preco_unit=abaixo)                        # consome a liberação vigente
check("item aprovado ao consumir liberação", item(i2)["aprovado"] == 1)
check("liberação marcada como usada", lib(pend)["status"] == "usada", lib(pend)["status"])
meio = round(abaixo + 1, 2)                        # ainda abaixo do piso, acima do autorizado
if meio < limite:
    edit(i2, preco_unit=meio)
    check("preço acima do autorizado segue aprovado", item(i2)["aprovado"] == 1)
    check("sem pedido novo", item(i2)["liberacao_id"] == pend)

deal = deal_1                                     # volta ao negócio do i1
print("\n[9] Validações e permissões")
check("qtd zero recusada", edit(i1, qtd=0).status_code == 400)
check("qtd negativa recusada", edit(i1, qtd=-3).status_code == 400)
check("preço zero recusado", edit(i1, preco_unit=0).status_code == 400)
check("preço inválido recusado", edit(i1, preco_unit="abc").status_code == 400)
check("item inexistente → 404",
      cli.put(f"/api/deals/{deal}/orcamento/itens/nao-existe", headers=hv, json={"qtd": 2}).status_code == 404)
outro = login("tiago@lojadigimagem.com.br", "vendas123")
check("outro vendedor não edita (sigilo de carteira)",
      cli.put(f"/api/deals/{deal}/orcamento/itens/{i1}", headers=outro, json={"qtd": 9}).status_code in (403, 404))
check("sem token → 401",
      cli.put(f"/api/deals/{deal}/orcamento/itens/{i1}", json={"qtd": 9}).status_code == 401)

print("\n[10] Negócio fechado não aceita edição")
r = cli.post(f"/api/deals/{deal}/stage", headers=hv,
             json={"etapa_funil": "fechado_perdido", "motivo_perda": "preco"})
check("negócio movido para perdido", r.status_code == 200, r.get_json())
check("status realmente 'perdido'",
      q("SELECT status FROM deals WHERE id=?", (deal,))[0]["status"] != "aberto")
r = edit(i1, qtd=3)
check("negócio não-aberto recusado", r.status_code == 400, r.get_json())

print("\n[11] 🛡 Item que a edição deixou pendente continua travando o faturamento")
d2 = cli.post("/api/deals", headers=hv, json={
    "titulo": "Teste v49 — trava", "customer_id": cust, "categoria": "padrao"}).get_json()["id"]
deal = d2
i3 = add(tabela, qtd=1)["id"]                      # preço cheio: pode ganhar
r = cli.post(f"/api/deals/{d2}/stage", headers=hv, json={"etapa_funil": "fechado_ganho"})
check("com item aprovado, GANHO passa", r.status_code == 200, r.get_json())
cli.post(f"/api/deals/{d2}/stage", headers=hv, json={"etapa_funil": "negociacao"})
edit(i3, preco_unit=round(limite - 30, 2))         # edição derruba abaixo do piso
check("edição deixou o item pendente", item(i3)["aprovado"] == 0)
r = cli.post(f"/api/deals/{d2}/stage", headers=hv, json={"etapa_funil": "fechado_ganho"})
check("GANHO agora é bloqueado", r.status_code == 400, r.get_json())
check("negócio permanece aberto",
      q("SELECT status FROM deals WHERE id=?", (d2,))[0]["status"] == "aberto")

print("\n[12] 🔔 Contador de liberações pendentes")
d3 = cli.post("/api/deals", headers=hv, json={
    "titulo": "Teste v50 — contador", "customer_id": cust, "categoria": "padrao"}).get_json()["id"]
deal = d3
def pendentes(h):
    return cli.get("/api/liberacoes/pendentes", headers=h).get_json()["pendentes"]
base_admin, base_ana = pendentes(ha), pendentes(hv)
i4 = add(round(limite - 15, 2))["id"]              # gera um pedido
check("admin vê +1", pendentes(ha) == base_admin + 1, pendentes(ha))
check("vendedor vê o próprio +1", pendentes(hv) == base_ana + 1)
outro2 = login("tiago@lojadigimagem.com.br", "vendas123")
check("outro vendedor não vê pedido alheio", pendentes(outro2) == 0, pendentes(outro2))
lid4 = item(i4)["liberacao_id"]
cli.post(f"/api/liberacoes/{lid4}/decidir", headers=ha,
         json={"decisao": "aprovar", "preco_autorizado": round(limite - 15, 2)})
check("após decidir, volta ao valor anterior", pendentes(ha) == base_admin)
check("rota exige sessão", cli.get("/api/liberacoes/pendentes").status_code == 401)

print("\n[13] 🚫 Produto sem preço de tabela não pode ser vendido")
c = sqlite3.connect(DB)
c.execute("""INSERT INTO produtos (id, nome, ativo, ofertavel, desconto_valor)
             VALUES ('p-sem-preco', 'Instax (sem preço)', 1, 1, 0)""")
c.commit(); c.close()
o = cli.get(f"/api/deals/{deal}/orcamento", headers=hv).get_json()
check("some da lista do vendedor",
      not [x for x in o["produtos_disponiveis"] if x["id"] == "p-sem-preco"])
r = cli.post(f"/api/deals/{deal}/orcamento/itens", headers=hv,
             json={"produto_id": "p-sem-preco", "qtd": 1, "preco_unit": 1.0})
check("adicionar é recusado", r.status_code == 400, r.get_json())
check("erro explica o motivo", "preço de tabela" in (r.get_json().get("error") or ""))
check("nada foi gravado",
      len(q("SELECT id FROM deal_itens WHERE produto_id='p-sem-preco'")) == 0)
r = cli.post(f"/api/deals/{deal}/orcamento/itens", headers=ha,
             json={"produto_id": "p-sem-preco", "qtd": 1, "preco_unit": 1.0})
check("nem o admin escapa", r.status_code == 400, r.get_json())

print("\n[14] 🗑 Excluir produto usado em orçamento devolve mensagem, não erro 500")
usado = item(i4)["produto_id"]
r = cli.delete(f"/api/produtos/{usado}", headers=ha)
check("HTTP 400, não 500", r.status_code == 400, r.status_code)
check("cita itens de orçamento", "orçamento" in (r.get_json().get("error") or ""), r.get_json())
check("produto continua no catálogo", len(q("SELECT id FROM produtos WHERE id=?", (usado,))) == 1)
r = cli.delete("/api/produtos/p-sem-preco", headers=ha)
check("produto nunca usado ainda pode ser excluído", r.status_code == 200, r.get_json())
check("vendedor não exclui produto",
      cli.delete(f"/api/produtos/{usado}", headers=hv).status_code == 403)

print(f"\n{'='*46}\n  {ok} passaram · {fail} falharam\n{'='*46}")
sys.exit(1 if fail else 0)
