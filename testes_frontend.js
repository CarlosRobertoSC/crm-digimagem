/**
 * Testes de lógica do frontend — rodar com:  node testes_frontend.js
 *
 * O dashboard é um arquivo único sem módulos, então aqui as funções são
 * extraídas do HTML e avaliadas com um DOM e um api() falsos. Não substitui
 * o teste visual na tela (é ele que pega botão invisível, layout quebrado);
 * cobre o que dá para verificar sem navegador: o que é enviado ao servidor,
 * o que é barrado antes da rede e o que aparece escrito.
 */
const fs = require("fs");
const path = require("path");
const html = fs.readFileSync(path.join(__dirname, "static", "dashboard.html"), "utf8");

let ok = 0, fail = 0;
const check = (n, c, extra) => c ? (ok++, console.log("  ✅ " + n))
                                 : (fail++, console.log("  ❌ " + n, extra ?? ""));
function extrair(re, nome) {
  const m = html.match(re);
  if (!m) { console.error(`❌ não encontrei ${nome} no dashboard.html`); process.exit(1); }
  return m[0];
}

// ------------------------------------------------------------------
// Suíte 1 — edição de item do orçamento (v49)
// ------------------------------------------------------------------
async function suiteEdicaoItem() {
  const codigo = extrair(
    /function editarItemOrcamento[\s\S]*?\n}\n\nasync function salvarEdicaoItem[\s\S]*?\n}\n/,
    "salvarEdicaoItem");

  let chamadas, alertas, renderizou, badgeAtualizado, promptResposta, campos = {};
  global.ORC_DEAL_ID = "D1";
  global.ORC_EDIT_ID = "I1";
  global.renderOrcamento = async () => { renderizou = true; };
  global.atualizarBadgeLiberacoes = () => { badgeAtualizado = true; };
  global.alert = m => alertas.push(m);
  global.prompt = () => promptResposta;
  global.api = async (url, opts) => { chamadas.push({ url, ...opts, corpo: JSON.parse(opts.body) }); return {}; };
  global.document = { getElementById: id => campos[id] ?? null };
  eval(codigo);

  const item = { id: "I1", produto_id: "P1", preco_unit: 500, qtd: 2 };
  const prod = { id: "P1", preco_minimo: 450 };
  const cen = (qtd, preco, produto, admin = false) => {
    chamadas = []; alertas = []; renderizou = false; badgeAtualizado = false;
    campos = { edtQtd: { value: String(qtd) }, edtPreco: { value: String(preco) },
               orcErro: { textContent: "" } };
    global.ORC_ORCAMENTO = { admin, itens: [item], produtos_disponiveis: produto ? [produto] : [] };
  };

  console.log("\n📝 EDIÇÃO DE ITEM DO ORÇAMENTO\n");
  console.log("[A] Só quantidade: envia sem pedir motivo");
  cen(7, 500, prod); await salvarEdicaoItem("I1");
  check("uma chamada PUT", chamadas.length === 1 && chamadas[0].method === "PUT");
  check("URL correta", chamadas[0]?.url === "/deals/D1/orcamento/itens/I1", chamadas[0]?.url);
  check("qtd 7 no corpo", chamadas[0]?.corpo.qtd === 7);
  check("preço inalterado no corpo", chamadas[0]?.corpo.preco_unit === 500);
  check("NÃO pediu motivo", chamadas[0]?.corpo.motivo === undefined);
  check("re-renderizou", renderizou);
  check("nenhum alerta inesperado", alertas.length === 0, alertas);
  check("badge de liberações atualizado", badgeAtualizado);

  console.log("\n[B] Preço abaixo do piso: pede motivo e o envia");
  cen(2, 400, prod); promptResposta = "concorrência"; await salvarEdicaoItem("I1");
  check("motivo enviado", chamadas[0]?.corpo.motivo === "concorrência", chamadas[0]?.corpo);
  check("preço 400 no corpo", chamadas[0]?.corpo.preco_unit === 400);

  console.log("\n[C] Cancelar o prompt aborta o salvamento");
  cen(2, 400, prod); promptResposta = null; await salvarEdicaoItem("I1");
  check("nenhuma chamada feita", chamadas.length === 0);

  console.log("\n[D] Admin não é interrogado sobre motivo");
  cen(2, 400, prod, true); promptResposta = null; await salvarEdicaoItem("I1");
  check("salvou sem prompt", chamadas.length === 1 && chamadas[0].corpo.motivo === undefined);

  console.log("\n[E] Entradas inválidas são barradas antes da rede");
  cen(0, 500, prod); await salvarEdicaoItem("I1");
  check("qtd 0 barrada", chamadas.length === 0 && alertas.length === 1, alertas);
  cen(3, 0, prod); await salvarEdicaoItem("I1");
  check("preço 0 barrado", chamadas.length === 0 && alertas.length === 1, alertas);

  console.log("\n[F] Produto fora do catálogo não quebra o salvamento");
  cen(3, 100, null); await salvarEdicaoItem("I1");
  check("salvou sem estourar", chamadas.length === 1);
}

// ------------------------------------------------------------------
// Suíte 2 — contador de liberações no menu (v50)
// ------------------------------------------------------------------
async function suiteBadge() {
  const codigo = extrair(/let TIMER_LIBERACOES = null;[\s\S]*?\n}\n/, "atualizarBadgeLiberacoes");

  let resposta, erro;
  const badge = { textContent: "", title: "", _cls: new Set(),
    classList: { toggle(c, on) { on ? badge._cls.add(c) : badge._cls.delete(c); },
                 remove(c) { badge._cls.delete(c); }, has(c) { return badge._cls.has(c); } } };
  global.document = { getElementById: id => id === "badgeLiberacoes" ? badge : null };
  global.api = async () => { if (erro) throw new Error("rede"); return resposta; };
  eval(codigo);

  const cen = (p, role = "admin", falha = false) => {
    resposta = { pendentes: p }; erro = falha; global.CURRENT_USER = { role };
    badge._cls.clear(); badge.textContent = ""; badge.title = "";
  };

  console.log("\n\n🔔 CONTADOR DE LIBERAÇÕES NO MENU\n");
  console.log("[A] Admin com 3 pendentes");
  cen(3); await atualizarBadgeLiberacoes();
  check("badge visível", badge.classList.has("on"));
  check("mostra 3", badge.textContent === 3, badge.textContent);
  check("título fala em decisão dele", /aguardando sua decisão/.test(badge.title), badge.title);

  console.log("\n[B] Zero pendentes: badge some");
  cen(0); await atualizarBadgeLiberacoes();
  check("badge oculto", !badge.classList.has("on"));
  check("título neutro", /Nenhuma/.test(badge.title), badge.title);

  console.log("\n[C] Vendedor vê texto diferente");
  cen(2, "vendedor"); await atualizarBadgeLiberacoes();
  check("título fala do administrador", /aguardando o administrador/.test(badge.title), badge.title);

  console.log("\n[D] Muitos pendentes não estouram o layout");
  cen(1234); await atualizarBadgeLiberacoes();
  check("mostra 99+", badge.textContent === "99+", badge.textContent);

  console.log("\n[E] Falha de rede não deixa número velho na tela");
  cen(5); await atualizarBadgeLiberacoes();
  check("badge aceso antes", badge.classList.has("on"));
  erro = true; await atualizarBadgeLiberacoes();
  check("apaga em vez de mentir", !badge.classList.has("on"));

  console.log("\n[F] Sem sessão não consulta");
  global.CURRENT_USER = null; erro = false; resposta = { pendentes: 9 };
  badge._cls.clear(); badge.textContent = "";
  await atualizarBadgeLiberacoes();
  check("não fez nada", badge.textContent === "" && !badge.classList.has("on"));
}

// ------------------------------------------------------------------
// Suíte 3 — renderização dos detalhes da auditoria (v51)
// ------------------------------------------------------------------
async function suiteAuditoria() {
  const codigo = extrair(
    /const AUDIT_ACAO_ROTULO[\s\S]*?\nfunction auditDetalhes\(d\) \{[\s\S]*?\n}\n/,
    "auditDetalhes");
  global.esc = t => String(t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  global.fmtPreco = v => "R$ " + Number(v).toFixed(2).replace(".", ",");
  eval(codigo);

  console.log("\n\n🗂 AUDITORIA — LEITURA DOS DETALHES\n");
  console.log("[A] O registro da v49 vira frase, não par chave-valor");
  let h = auditDetalhes({ aumento_qtd_com_liberacao: true, valor_adicional: 3010,
                          produto: "Papel Fuji", qtd: "2 → 9" });
  check("avisa do aumento com preço liberado", /quantidade aumentada em item com preço liberado/.test(h));
  check("mostra o valor adicional em reais", /R\$ 3010,00/.test(h), h);
  check("não repete a marca como chip", !/aumento_qtd_com_liberacao/.test(h));
  check("mantém os demais campos", /quantidade: <b>2 → 9<\/b>/.test(h), h);

  console.log("\n[B] Chaves técnicas viram português");
  h = auditDetalhes({ preco_autorizado: 430, abaixo_limite: true, para: "Tiago" });
  check("preco_autorizado → preço autorizado", /preço autorizado/.test(h));
  check("abaixo_limite → abaixo do limite", /abaixo do limite/.test(h));
  check("para → transferido para", /transferido para: <b>Tiago<\/b>/.test(h), h);
  check("booleano vira sim/não", /<b>sim<\/b>/.test(h));

  console.log("\n[C] Casos de borda não quebram a tela");
  check("detalhes nulo", auditDetalhes(null).includes("—"));
  check("detalhes vazio", typeof auditDetalhes({}) === "string");
  check("valor nulo vira travessão", /<b>—<\/b>/.test(auditDetalhes({ motivo_perda: null })));
  check("texto puro (registro antigo)", auditDetalhes("qualquer coisa") === "qualquer coisa");
  check("chave desconhecida é legível",
        /chave nova: <b>1<\/b>/.test(auditDetalhes({ chave_nova: 1 })), auditDetalhes({ chave_nova: 1 }));

  console.log("\n[D] Dinheiro aparece como dinheiro");
  h = auditDetalhes({ preco_autorizado: 600, preco_pedido: 600.5, valor_adicional: 3600 });
  check("valor redondo vira R$", /preço autorizado: <b>R\$ 600,00<\/b>/.test(h), h);
  check("valor quebrado também", /preço pedido: <b>R\$ 600,50<\/b>/.test(h), h);
  check("valor adicional em R$", /R\$ 3600,00/.test(h), h);
  h = auditDetalhes({ qtd: 16, produtos_novos: 74 });
  check("quantidade NÃO vira dinheiro", /quantidade: <b>16<\/b>/.test(h), h);
  check("contagem NÃO vira dinheiro", /produtos novos: <b>74<\/b>/.test(h), h);

  console.log("\n[E] Chaves acentuadas");
  h = auditDetalhes({ decisao: "aprovar", liberacao: null, condicoes: 8 });
  check("decisao → decisão", /decisão: <b>aprovar<\/b>/.test(h), h);
  check("liberacao → liberação", /liberação/.test(h), h);
  check("condicoes → condições", /condições: <b>8<\/b>/.test(h), h);

  console.log("\n[F] Conteúdo hostil é escapado");
  h = auditDetalhes({ nome: '<img src=x onerror=alert(1)>' });
  check("HTML não passa cru", !/<img/.test(h), h);
  check("vira entidade escapada", /&lt;img/.test(h));
}

(async () => {
  await suiteEdicaoItem();
  await suiteBadge();
  await suiteAuditoria();
  console.log(`\n${"=".repeat(46)}\n  ${ok} passaram · ${fail} falharam\n${"=".repeat(46)}`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error("❌ exceção:", e); process.exit(1); });
