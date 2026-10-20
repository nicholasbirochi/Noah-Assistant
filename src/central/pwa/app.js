// Central de pendências: lista o que espera resposta (Claude Code, Codex, Noah)
// e responde retomando a conversa sem editar nada. Todo texto vindo do servidor
// entra na página por textContent -- nada de innerHTML com dado.
"use strict";

const API = "api/";
const CHAVE_TOKEN = "noah_central_token";
const CHAVE_FILTRO = "noah_central_filtro";
const FONTES = { claude: "Claude", codex: "Codex", noah: "Noah" };
const INTERVALO = 20000;
const INTERVALO_RESPONDENDO = 4000;
const JOB_VISIVEL_S = 600;

const $ = (id) => document.getElementById(id);
const rascunhos = new Map(); // chave -> texto ainda não enviado
const cartoes = new Map(); // chave -> {el, assinatura}
const expandidos = new Set();
let itens = [];
let jobs = [];
let filtro = lerLocal(CHAVE_FILTRO) || "todas";
let timer = null;
let carregando = false;

function lerLocal(chave) {
  try { return localStorage.getItem(chave); } catch { return null; }
}
function gravarLocal(chave, valor) {
  try {
    if (valor === null) localStorage.removeItem(chave); else localStorage.setItem(chave, valor);
  } catch { /* modo privado: segue sem guardar */ }
}

function el(tag, attrs = {}, ...filhos) {
  const no = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") no.className = v;
    else if (k.startsWith("on")) no.addEventListener(k.slice(2), v);
    else no.setAttribute(k, v === true ? "" : v);
  }
  for (const f of filhos.flat()) {
    if (f === null || f === undefined || f === false) continue;
    no.append(f instanceof Node ? f : document.createTextNode(String(f)));
  }
  return no;
}

function svg(caminho) {
  const ns = "http://www.w3.org/2000/svg";
  const s = document.createElementNS(ns, "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("fill", "none");
  s.setAttribute("stroke", "currentColor");
  s.setAttribute("stroke-width", "2.2");
  s.setAttribute("stroke-linecap", "round");
  s.setAttribute("stroke-linejoin", "round");
  s.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(ns, "path");
  p.setAttribute("d", caminho);
  s.append(p);
  return s;
}

function toast(texto) {
  const t = $("toast");
  t.textContent = texto;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 3500);
}

// -- markdown mínimo e seguro ------------------------------------------------

function inline(texto) {
  const partes = [];
  const re = /(`[^`\n]+`|\*\*[^*\n]+\*\*)/g;
  let ultimo = 0;
  for (const m of texto.matchAll(re)) {
    if (m.index > ultimo) partes.push(texto.slice(ultimo, m.index));
    const s = m[0];
    partes.push(s.startsWith("`") ? el("code", {}, s.slice(1, -1)) : el("strong", {}, s.slice(2, -2)));
    ultimo = m.index + s.length;
  }
  if (ultimo < texto.length) partes.push(texto.slice(ultimo));
  return partes;
}

function blocos(texto) {
  const saida = [];
  const trechos = texto.split(/^```[^\n]*\n?/m);
  trechos.forEach((trecho, i) => {
    if (i % 2 === 1) {
      saida.push(el("pre", {}, el("code", {}, trecho.replace(/\n$/, ""))));
      return;
    }
    for (const bloco of trecho.split(/\n\s*\n/)) {
      const linhas = bloco.split("\n").filter((l) => l.trim());
      if (!linhas.length) continue;
      if (linhas.every((l) => /^\s*[-*•]\s+/.test(l))) {
        saida.push(el("ul", {}, linhas.map((l) => el("li", {}, inline(l.replace(/^\s*[-*•]\s+/, ""))))));
      } else if (linhas.every((l) => /^\s*\d+[.)]\s+/.test(l))) {
        saida.push(el("ol", {}, linhas.map((l) => el("li", {}, inline(l.replace(/^\s*\d+[.)]\s+/, ""))))));
      } else if (linhas.length === 1 && /^#{1,6}\s+/.test(linhas[0])) {
        saida.push(el("h3", {}, inline(linhas[0].replace(/^#{1,6}\s+/, ""))));
      } else {
        const p = el("p");
        linhas.forEach((l, j) => {
          if (j) p.append(el("br"));
          p.append(...inline(l.replace(/^#{1,6}\s+/, "")));
        });
        saida.push(p);
      }
    }
  });
  return saida;
}

// -- tempo relativo -------------------------------------------------------------

function haQuanto(iso) {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "agora";
  if (s < 3600) return `há ${Math.floor(s / 60)} min`;
  if (s < 86400) return `há ${Math.floor(s / 3600)} h`;
  const d = Math.floor(s / 86400);
  return d === 1 ? "ontem" : `há ${d} dias`;
}

// -- rede -------------------------------------------------------------------------

async function api(caminho, corpo) {
  const token = lerLocal(CHAVE_TOKEN);
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const opcoes = { headers, cache: "no-store" };
  if (corpo !== undefined) {
    opcoes.method = "POST";
    headers["Content-Type"] = "application/json";
    opcoes.body = JSON.stringify(corpo);
  }
  const r = await fetch(API + caminho, opcoes);
  let dados = {};
  try { dados = await r.json(); } catch { /* corpo vazio */ }
  if (r.status === 401) {
    pedirToken();
    throw new Error("Token ausente ou inválido.");
  }
  if (!r.ok) throw new Error(dados.erro || `Erro ${r.status}`);
  return dados;
}

function pedirToken() {
  $("token").hidden = false;
  $("lista").replaceChildren();
  cartoes.clear();
  setTimeout(() => $("campo-token").focus(), 50);
}

async function carregar({ manual = false } = {}) {
  if (carregando) return;
  carregando = true;
  $("atualizar").classList.add("girando");
  try {
    const dados = await api("pendencias");
    $("token").hidden = true;
    itens = dados.itens || [];
    jobs = dados.respondendo || [];
    desenharAvisos(dados.falhas || []);
    desenhar();
  } catch (e) {
    if ($("token").hidden) desenharAvisos([], e.message);
  } finally {
    carregando = false;
    $("atualizar").classList.remove("girando");
    agendar();
    if (manual) toast("Atualizado");
  }
}

function agendar() {
  clearTimeout(timer);
  if (document.hidden) return;
  const rodando = jobs.some((j) => j.estado === "rodando");
  timer = setTimeout(carregar, rodando ? INTERVALO_RESPONDENDO : INTERVALO);
}

// -- desenho ------------------------------------------------------------------------

function desenharAvisos(falhas, erro) {
  const caixa = $("avisos");
  caixa.replaceChildren();
  if (erro) caixa.append(el("div", { class: "aviso erro" }, `Não deu para atualizar: ${erro}`));
  if (falhas.length) caixa.append(el("div", { class: "aviso" }, `Fonte com problema (pulada): ${falhas.join(", ")}`));
}

function desenharChips() {
  const contagem = { todas: itens.length, claude: 0, codex: 0, noah: 0 };
  for (const i of itens) contagem[i.fonte] = (contagem[i.fonte] || 0) + 1;
  const opcoes = [["todas", "Todas"], ...Object.entries(FONTES)];
  $("chips").replaceChildren(...opcoes
    .filter(([k]) => k === "todas" || contagem[k] > 0 || filtro === k)
    .map(([k, rotulo]) => el("button", {
      class: "chip", type: "button", "aria-pressed": String(filtro === k),
      onclick: () => { filtro = k; gravarLocal(CHAVE_FILTRO, k); desenhar(); },
    }, k === "todas" ? null : el("span", { class: `ponto ${k}` }), rotulo, el("span", { class: "n" }, contagem[k]))));
  const c = $("contagem");
  c.textContent = itens.length;
  c.classList.toggle("zero", itens.length === 0);
  document.title = itens.length ? `(${itens.length}) Pendências` : "Pendências";
}

function desenharJobs() {
  const agora = Date.now() / 1000;
  const visiveis = jobs.filter((j) => j.estado === "rodando" || (j.fim && agora - j.fim < JOB_VISIVEL_S));
  $("andamento").replaceChildren(...visiveis.map((j) => {
    const estado = { rodando: "respondendo…", concluido: "respondeu", erro: "falhou" }[j.estado] || j.estado;
    const filhos = [
      j.estado === "rodando" ? el("span", { class: "pulso" }) : el("span", { class: `ponto ${j.fonte}` }),
      el("span", { class: "rotulo" }, `${FONTES[j.fonte] || j.fonte} · ${j.titulo}`),
      el("span", { class: "estado" }, estado),
    ];
    if (j.estado === "erro" && j.detalhe) {
      filhos.push(el("details", {}, el("summary", {}, "detalhe"), el("pre", {}, j.detalhe)));
    }
    return el("div", { class: `job ${j.estado}` }, filhos);
  }));
}

function assinatura(i) {
  return [i.versao, i.respondendo, expandidos.has(i.chave), i.titulo].join("|");
}

function desenhar() {
  desenharChips();
  desenharJobs();
  const lista = $("lista");
  const visiveis = itens.filter((i) => filtro === "todas" || i.fonte === filtro);
  if (!visiveis.length) {
    cartoes.clear();
    lista.replaceChildren(el("div", { class: "vazio" },
      el("strong", {}, "Nada esperando você"),
      itens.length ? "Nenhuma pendência neste filtro." : "Quando uma conversa terminar e esperar resposta, ela aparece aqui."));
    return;
  }
  const foco = document.activeElement;
  const novos = visiveis.map((i) => {
    const antigo = cartoes.get(i.chave);
    if (antigo && antigo.assinatura === assinatura(i)) {
      atualizarTempo(antigo.el, i);
      return antigo.el;
    }
    const cartao = criarCartao(i);
    cartoes.set(i.chave, { el: cartao, assinatura: assinatura(i) });
    return cartao;
  });
  const chaves = new Set(visiveis.map((i) => i.chave));
  for (const k of [...cartoes.keys()]) if (!chaves.has(k)) cartoes.delete(k);
  const atuais = [...lista.children];
  const mesmaOrdem = atuais.length === novos.length && atuais.every((n, idx) => n === novos[idx]);
  if (!mesmaOrdem) lista.replaceChildren(...novos);
  if (foco && foco !== document.activeElement && document.contains(foco)) foco.focus();
}

function atualizarTempo(cartao, i) {
  const t = cartao.querySelector(".tempo");
  if (t) t.textContent = haQuanto(i.quando);
}

function criarCartao(i) {
  const expandido = expandidos.has(i.chave);
  const msg = el("div", { class: `msg${expandido ? "" : " curta"}` }, blocos(i.mensagem));
  const cartao = el("article", { "data-chave": i.chave },
    el("div", { class: "meta" },
      el("span", { class: "fonte" }, el("span", { class: `ponto ${i.fonte}` }), FONTES[i.fonte] || i.fonte),
      el("span", { class: "projeto" }, i.projeto ? `· ${i.projeto}` : ""),
      el("span", { class: "tempo" }, haQuanto(i.quando))),
    el("h2", {}, i.titulo),
    msg);

  const mais = el("button", {
    class: "mais", type: "button", hidden: true,
    onclick: () => {
      if (expandidos.has(i.chave)) expandidos.delete(i.chave); else expandidos.add(i.chave);
      cartoes.delete(i.chave);
      desenhar();
    },
  }, expandido ? "ver menos" : "ver tudo");
  cartao.append(mais);
  requestAnimationFrame(() => { if (expandido || msg.scrollHeight > msg.clientHeight + 2) mais.hidden = false; });

  const dispensar = el("button", { class: "dispensar", type: "button", onclick: () => acaoDispensar(i) }, "Dispensar");

  if (!i.pode_responder) {
    cartao.append(el("div", { class: "rodape" }, el("span", { class: "nota" }, "Só leitura"), dispensar));
    return cartao;
  }
  if (i.respondendo) {
    cartao.append(el("div", { class: "respondendo" }, el("span", { class: "pulso" }), `${FONTES[i.fonte]} está respondendo…`));
    return cartao;
  }

  const campo = el("textarea", {
    rows: "1", placeholder: "Responder…", "aria-label": `Responder: ${i.titulo}`, maxlength: "4000",
    enterkeyhint: "send",
  });
  campo.value = rascunhos.get(i.chave) || "";
  const enviar = el("button", { class: "enviar", type: "submit", "aria-label": "Enviar", disabled: !campo.value.trim() },
    svg("M12 19V5M5 12l7-7 7 7"));
  const crescer = () => {
    // border-box: a altura inclui a borda, que o scrollHeight não conta.
    const borda = campo.offsetHeight - campo.clientHeight;
    campo.style.height = "auto";
    const alvo = campo.scrollHeight + borda;
    campo.style.height = `${Math.min(alvo, 180)}px`;
    campo.style.overflowY = alvo > 180 ? "auto" : "hidden";
  };
  campo.addEventListener("input", () => {
    rascunhos.set(i.chave, campo.value);
    enviar.disabled = !campo.value.trim();
    crescer();
  });
  campo.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); form.requestSubmit(); }
  });
  const form = el("form", { class: "responder", onsubmit: (e) => { e.preventDefault(); acaoResponder(i, campo, enviar); } },
    campo, enviar);
  requestAnimationFrame(crescer);
  cartao.append(form, el("div", { class: "rodape" },
    el("span", { class: "nota" }, "Responde sem editar arquivos"), dispensar));
  return cartao;
}

// -- ações ----------------------------------------------------------------------------

async function acaoResponder(i, campo, botao) {
  const texto = campo.value.trim();
  if (!texto) return;
  botao.disabled = true;
  campo.disabled = true;
  try {
    await api("responder", { fonte: i.fonte, id: i.id, texto });
    rascunhos.delete(i.chave);
    toast(`Enviado. ${FONTES[i.fonte]} está respondendo.`);
    cartoes.delete(i.chave);
    await carregar();
  } catch (e) {
    toast(e.message);
    botao.disabled = false;
    campo.disabled = false;
  }
}

async function acaoDispensar(i) {
  try {
    await api("dispensar", { fonte: i.fonte, id: i.id });
    itens = itens.filter((x) => x.chave !== i.chave);
    cartoes.delete(i.chave);
    desenhar();
  } catch (e) {
    toast(e.message);
  }
}

// -- início -----------------------------------------------------------------------------

$("form-token").addEventListener("submit", (e) => {
  e.preventDefault();
  const valor = $("campo-token").value.trim();
  if (!valor) return;
  gravarLocal(CHAVE_TOKEN, valor);
  $("campo-token").value = "";
  carregar();
});
$("atualizar").addEventListener("click", () => carregar({ manual: true }));
document.addEventListener("visibilitychange", () => {
  if (document.hidden) clearTimeout(timer); else carregar();
});
carregar();
