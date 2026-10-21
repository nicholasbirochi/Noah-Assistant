"""Leitores das pendências: o que, no disco, está esperando uma resposta sua.

Só leitura e só local. Cada fonte é lida por código, sem modelo no caminho, então
nada é inventado: se um arquivo não segue o formato esperado, a linha (ou a
fonte inteira) é pulada -- falha fechada, nunca uma pendência chutada.

- Claude Code: ``~/.claude/projects/<pasta>/<sessão>.jsonl``. Pendente quando a
  última mensagem (fora de subagente) é do assistente, tem texto e terminou o
  turno (sem ``tool_use`` em aberto). Os arquivos ``<sessão>/subagents/agent-*.jsonl``
  só acrescentam IDs quando ``sessionId``, ``agentId`` e ``isSidechain`` confirmam
  a relação; o conteúdo desses arquivos não entra no payload.
- Codex: ``~/.codex/sessions/AAAA/MM/DD/rollout-*.jsonl`` + títulos em
  ``~/.codex/session_index.jsonl``. Pendente quando o último evento de turno é
  ``task_complete`` com ``last_agent_message``. O Codex Desktop grava ``source``
  "vscode" e entra normalmente; conversas arquivadas (``archived_sessions``) ficam
  de fora, e o banco SQLite do Codex não é lido.
- Noah: os itens da presença (docs/ADR-0001), só leitura e só quando
  ``NOAH_PRESENCE_ENABLED=true``.

Sessões automáticas ficam de fora: ``claude -p`` (entrypoint ``sdk-*``),
``codex exec`` e subagentes do Codex. Decisão em docs/ADR-0002.

Cada item diz também se a última mensagem pede algo a você (``pergunta``) ou é só
uma resposta pronta, um relatório sem pergunta. O critério é textual e fica no fim
da mensagem (fora de blocos de código e links): um "?" ou um pedido explícito
("me avise", "aguardo", "let me know"...). Sem isso o item vira resposta pronta:
continua listado e respondível, só não conta como "esperando você" na ilha e nos
widgets. Itens do Noah são sempre pergunta (ação sugerida). Decisão em docs/ADR-0002.

Uma pergunta é ``simples`` quando dá para responder com um "sim": a última pergunta é
curta, de sim ou não ("posso seguir?", "quer que eu faça o push?", "should I...?"),
sem lista de opções e sem começar por "qual", "como", "o que"... Só nela aparece o
botão Aceitar; nas outras você escreve a resposta.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

DIAS_PADRAO = 3
MAX_ITENS = 40
BYTES_FIM = 512 * 1024  # só o fim do transcript é lido para achar a última mensagem
LIMITE_TEXTO = 8000
MAX_DISPENSADAS = 500
MAX_SUBAGENTES_SNAPSHOT = 20

RAIZ_CLAUDE = Path.home() / ".claude" / "projects"
RAIZ_CODEX = Path.home() / ".codex"

_FIM_DE_TURNO_CLAUDE = {"end_turn", "stop_sequence", "max_tokens"}
_EVENTOS_DE_TURNO_CODEX = {"task_started", "task_complete", "turn_aborted"}

# Quanto do fim da mensagem decide se ela é pergunta: o pedido costuma vir no
# último parágrafo, depois do relatório.
FIM_PERGUNTA = 400
_BLOCO_CODIGO = re.compile(r"```.*?(```|$)|`[^`\n]*`", re.S)
_LINK = re.compile(r"\S+://\S+")
_PEDIDOS = re.compile(
    r"\b(me (avise|diga|fala|confirme)|aguardo|confirm[ae] (se|que|antes)|"
    r"(voc[eê]|vc) (autoriza|aprova|prefere|quer)|posso (seguir|continuar|prosseguir|fazer)|"
    r"let me know|should i|do you want|would you like|want me to|shall i)\b",
    re.I,
)
# Pergunta simples (botão Aceitar): curta, de sim ou não, sem menu de opções.
MAX_PERGUNTA_SIMPLES = 200
_SIM_OU_NAO = re.compile(
    r"\b(posso|podemos|pode|devo|quer|autoriza|aprova|confirma|sigo|seguimos|"
    r"fa[cç]o|mando|envio|aplico|deixo|tudo bem|ok|"
    r"should i|shall i|can i|may i|do you want|would you like|want me to|"
    r"is it ok|okay to|proceed)\b",
    re.I,
)
_ABERTA = re.compile(
    r"^\W*((e|ent[aã]o|mas|and|so)\s+)?(qual|quais|como|quanto|quantos|quantas|onde|"
    r"quando|por ?qu[eê]|o que|quem|what|which|how|where|when|why|who)\b",
    re.I,
)
_OPCAO = re.compile(r"^\s*(\d+[.)]|[a-z][.)]|[-*•])\s+", re.M)
_FRASE = re.compile(r"[^.!?\n]+[.!?]*")


@dataclass(frozen=True)
class Pendencia:
    fonte: str  # "claude" | "codex" | "noah"
    id: str  # id da sessão (Claude/Codex) ou do item de presença
    titulo: str
    projeto: str
    quando: str  # ISO 8601 da última mensagem do agente ("" para o Noah)
    mensagem: str
    versao: str  # muda quando chega mensagem nova; "dispensar" vale só para esta
    pode_responder: bool = True
    pergunta: bool = True  # False: resposta pronta, sem nada pedido a você
    simples: bool = False  # pergunta de sim ou não: o app mostra o botão Aceitar
    cwd: str = ""  # usado só para retomar a conversa; não vai para a página
    subagentes: list[dict[str, str]] = field(default_factory=list)  # IDs, nunca o conteúdo das conversas

    @property
    def chave(self) -> str:
        return f"{self.fonte}:{self.id}"

    def para_json(self) -> dict:
        dados = asdict(self)
        dados.pop("cwd")
        dados["chave"] = self.chave
        return dados


# -- leitura de arquivo -----------------------------------------------------


def _linhas_do_fim(caminho: Path, limite: int = BYTES_FIM) -> list[dict]:
    with caminho.open("rb") as arquivo:
        arquivo.seek(0, os.SEEK_END)
        tamanho = arquivo.tell()
        inicio = max(0, tamanho - limite)
        arquivo.seek(inicio)
        dados = arquivo.read()
    linhas = dados.split(b"\n")
    if inicio > 0:
        linhas = linhas[1:]  # a primeira pode ter sido cortada no meio
    saida = []
    for linha in linhas:
        if not linha.strip():
            continue
        try:
            item = json.loads(linha)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(item, dict):
            saida.append(item)
    return saida


def _recentes(arquivos, dias: float, agora: float) -> list[Path]:
    corte = agora - dias * 86400
    saida = []
    for caminho in arquivos:
        try:
            if caminho.stat().st_mtime >= corte:
                saida.append(caminho)
        except OSError:
            continue
    return saida


def _cortar(texto: str) -> str:
    texto = texto.strip()
    return texto if len(texto) <= LIMITE_TEXTO else texto[:LIMITE_TEXTO].rstrip() + "…"


def e_pergunta(texto: str) -> bool:
    """A mensagem termina pedindo algo a você? Olha só o fim, sem código e links
    (um "?" de regex ou de URL não é pergunta)."""
    limpo = _LINK.sub(" ", _BLOCO_CODIGO.sub(" ", texto)).strip()
    if not limpo:
        return False
    fim = limpo[-FIM_PERGUNTA:]
    return "?" in fim or bool(_PEDIDOS.search(fim))


def e_simples(texto: str) -> bool:
    """A última pergunta dá para responder com um "sim"? Curta, de sim ou não e sem
    lista de opções. Na dúvida, não: aí o app pede uma resposta escrita."""
    limpo = _LINK.sub(" ", _BLOCO_CODIGO.sub(" ", texto)).strip()
    fim = limpo[-FIM_PERGUNTA:]
    if not fim or len(_OPCAO.findall(fim)) >= 3:
        return False
    frases = [f.strip() for f in _FRASE.findall(fim) if f.strip()]
    perguntas = [f for f in frases if f.endswith("?")]
    if len(perguntas) > 2:
        return False  # várias perguntas pedem resposta escrita
    if perguntas:
        alvo = perguntas[-1]
    elif frases and _PEDIDOS.search(frases[-1]):
        alvo = frases[-1]  # "Aguardo seu ok para o push."
    else:
        return False
    if len(alvo) > MAX_PERGUNTA_SIMPLES or _ABERTA.search(alvo):
        return False
    return bool(_SIM_OU_NAO.search(alvo) or _PEDIDOS.search(alvo))


def _projeto(cwd: str) -> str:
    return Path(cwd).name if cwd else "?"


# -- Claude Code --------------------------------------------------------------

# Metadados que exigem varrer o arquivo inteiro (títulos, origem), guardados por
# (mtime, tamanho) para que a página possa atualizar a cada poucos segundos.
_cache_meta_claude: dict[Path, tuple[int, int, dict]] = {}
_trava_cache = threading.Lock()


def _subagentes_claude(caminho: Path) -> list[dict[str, str]]:
    """Retorna só IDs verificados pela sessão pai, pasta e metadados do sidechain."""
    pasta = caminho.parent / caminho.stem / "subagents"
    saida = []
    for arquivo in sorted(pasta.glob("agent-*.jsonl")):
        try:
            with arquivo.open("rb") as f:
                primeira = None
                for _ in range(8):
                    linha = f.readline(65537)
                    if not linha:
                        break
                    if linha.strip():
                        primeira = linha
                        break
            if primeira is not None and len(primeira) > 65536:
                continue
            metadados = _campos_sidechain(primeira) if primeira else {}
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        agent_id = arquivo.stem.removeprefix("agent-")
        if (metadados.get("sessionId") != caminho.stem
                or metadados.get("agentId") != agent_id
                or metadados.get("isSidechain") is not True):
            continue
        saida.append({"id": agent_id})
    return saida


def _fim_string_json(linha: bytes, inicio: int) -> int:
    """Índice após string JSON, sem decodificar seu conteúdo."""
    i = inicio + 1
    while i < len(linha):
        if linha[i] == 0x5C:  # barra invertida
            i += 2
        elif linha[i] == 0x22:
            return i + 1
        else:
            i += 1
    raise ValueError("string JSON incompleta")


def _campos_sidechain(linha: bytes) -> dict:
    """Extrai só três campos escalares do objeto raiz; ignora message e demais valores."""
    campos = {b"sessionId", b"agentId", b"isSidechain"}
    extraidos = {}
    i = 0
    while i < len(linha) and linha[i] in b" \t\r\n":
        i += 1
    if i >= len(linha) or linha[i] != 0x7B:
        return extraidos
    i += 1
    fechado = False
    while i < len(linha):
        while i < len(linha) and linha[i] in b" \t\r\n,":
            i += 1
        if i >= len(linha):
            break
        if linha[i] == 0x7D:
            fechado = True
            i += 1
            break
        if linha[i] != 0x22:
            return {}
        fim_chave = _fim_string_json(linha, i)
        chave = json.loads(linha[i:fim_chave])
        i = fim_chave
        while i < len(linha) and linha[i] in b" \t\r\n": i += 1
        if i >= len(linha) or linha[i] != 0x3A:
            return {}
        i += 1
        while i < len(linha) and linha[i] in b" \t\r\n": i += 1
        inicio_valor = i
        if i < len(linha) and linha[i] == 0x22:
            i = _fim_string_json(linha, i)
        else:
            pilha = []
            em_string = False
            while i < len(linha):
                byte = linha[i]
                if em_string:
                    if byte == 0x5C: i += 1
                    elif byte == 0x22: em_string = False
                elif byte == 0x22: em_string = True
                elif byte in (0x7B, 0x5B): pilha.append(byte)
                elif byte in (0x7D, 0x5D):
                    if not pilha: break
                    pilha.pop()
                elif byte == 0x2C and not pilha: break
                i += 1
        if chave.encode("utf-8") in campos:
            try:
                extraidos[chave] = json.loads(linha[inicio_valor:i])
            except (ValueError, UnicodeDecodeError):
                return {}
        while i < len(linha) and linha[i] in b" \t\r\n": i += 1
        if i < len(linha) and linha[i] == 0x2C:
            i += 1
    return extraidos if fechado and not linha[i:].strip() else {}


def conversas_claude_com_subagentes(raiz: Path = RAIZ_CLAUDE, *, limite: int = 20,
                                    agora: float | None = None, janela_s: float = 600) -> list[dict]:
    """Sessões tocadas nos últimos 10 min com sidechains confirmados; só IDs/timestamps."""
    if not raiz.is_dir() or limite <= 0:
        return []
    candidatos = []
    corte = (time.time() if agora is None else agora) - janela_s
    for caminho in raiz.glob("*/*.jsonl"):
        try:
            quando = caminho.stat().st_mtime
            if quando < corte:
                continue
            agentes = _subagentes_claude(caminho)
            if not agentes:
                continue
        except OSError:
            continue
        candidatos.append((quando, caminho.stem, agentes[:MAX_SUBAGENTES_SNAPSHOT]))
    candidatos.sort(reverse=True)
    return [{"id": ident, "quando": quando, "subagentes": agentes}
            for quando, ident, agentes in candidatos[:limite]]


def _meta_claude(caminho: Path) -> dict:
    info = caminho.stat()
    with _trava_cache:
        guardado = _cache_meta_claude.get(caminho)
    if guardado and guardado[:2] == (info.st_mtime_ns, info.st_size):
        return guardado[2]
    meta = {"titulo": None, "titulo_ia": None, "entrypoint": None}
    with caminho.open("rb") as arquivo:
        for linha in arquivo:
            cabeca = linha[:48]
            if b'"custom-title"' in cabeca or b'"ai-title"' in cabeca:
                try:
                    item = json.loads(linha)
                except (ValueError, UnicodeDecodeError):
                    continue
                if item.get("type") == "custom-title" and isinstance(item.get("customTitle"), str):
                    meta["titulo"] = item["customTitle"]
                elif item.get("type") == "ai-title" and isinstance(item.get("aiTitle"), str):
                    meta["titulo_ia"] = item["aiTitle"]
            elif meta["entrypoint"] is None and b'"entrypoint":"' in linha:
                try:
                    meta["entrypoint"] = json.loads(linha).get("entrypoint")
                except (ValueError, UnicodeDecodeError, AttributeError):
                    pass
    with _trava_cache:
        _cache_meta_claude[caminho] = (info.st_mtime_ns, info.st_size, meta)
    return meta


def _ultima_resposta_claude(linhas: list[dict]) -> dict | None:
    """A última mensagem do assistente, se ela fechou o turno; senão None."""
    finais: list[dict] = []
    for item in reversed(linhas):
        if item.get("type") not in ("user", "assistant") or item.get("isSidechain") or item.get("isMeta"):
            continue
        mensagem = item.get("message")
        if not isinstance(mensagem, dict):
            continue
        if item["type"] == "user":
            if finais:
                break
            return None  # a vez é do agente (ou o usuário interrompeu)
        if finais and mensagem.get("id") != finais[0]["message"].get("id"):
            break
        finais.append(item)
    if not finais:
        return None
    ultima = finais[0]  # a linha mais recente
    if ultima["message"].get("stop_reason") not in _FIM_DE_TURNO_CLAUDE:
        return None
    textos = []
    for item in reversed(finais):  # volta à ordem original dos blocos
        for bloco in item["message"].get("content") or []:
            if not isinstance(bloco, dict):
                continue
            if bloco.get("type") == "tool_use":
                return None
            if bloco.get("type") == "text" and isinstance(bloco.get("text"), str):
                textos.append(bloco["text"])
    texto = "\n\n".join(t for t in textos if t.strip())
    if not texto:
        return None
    return {"texto": texto, "quando": ultima.get("timestamp") or "", "cwd": ultima.get("cwd") or ""}


def pendencias_claude(raiz: Path = RAIZ_CLAUDE, *, dias: float = DIAS_PADRAO, agora: float | None = None) -> list[Pendencia]:
    agora = time.time() if agora is None else agora
    if not raiz.is_dir():
        return []
    saida = []
    for caminho in _recentes(raiz.glob("*/*.jsonl"), dias, agora):
        try:
            resposta = _ultima_resposta_claude(_linhas_do_fim(caminho))
            if resposta is None:
                continue
            meta = _meta_claude(caminho)
        except OSError:
            continue
        if str(meta.get("entrypoint") or "").startswith("sdk"):
            continue  # claude -p / SDK: automação, não conversa sua
        saida.append(Pendencia(
            fonte="claude",
            id=caminho.stem,
            titulo=meta["titulo"] or meta["titulo_ia"] or "Conversa sem título",
            projeto=_projeto(resposta["cwd"]),
            quando=resposta["quando"],
            mensagem=_cortar(resposta["texto"]),
            versao=resposta["quando"],
            pergunta=e_pergunta(resposta["texto"]),
            simples=e_simples(resposta["texto"]),
            cwd=resposta["cwd"],
            subagentes=_subagentes_claude(caminho),
        ))
    return saida


# -- Codex ----------------------------------------------------------------------


def _titulos_codex(raiz: Path) -> dict[str, str]:
    titulos: dict[str, str] = {}
    indice = raiz / "session_index.jsonl"
    if not indice.is_file():
        return titulos
    with indice.open("rb") as arquivo:
        for linha in arquivo:
            try:
                item = json.loads(linha)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("thread_name"), str):
                titulos[item["id"]] = item["thread_name"]  # a entrada mais recente vence
    return titulos


def _meta_codex(caminho: Path) -> dict | None:
    with caminho.open("rb") as arquivo:
        primeira = arquivo.readline()
    try:
        item = json.loads(primeira)
    except (ValueError, UnicodeDecodeError):
        return None
    payload = item.get("payload") if isinstance(item, dict) else None
    if item.get("type") != "session_meta" or not isinstance(payload, dict):
        return None
    return payload


def _ultima_resposta_codex(linhas: list[dict]) -> dict | None:
    for item in reversed(linhas):
        payload = item.get("payload")
        if item.get("type") != "event_msg" or not isinstance(payload, dict):
            continue
        if payload.get("type") not in _EVENTOS_DE_TURNO_CODEX:
            continue
        texto = payload.get("last_agent_message")
        if payload["type"] != "task_complete" or not isinstance(texto, str) or not texto.strip():
            return None
        return {"texto": texto, "quando": item.get("timestamp") or ""}
    return None


def pendencias_codex(raiz: Path = RAIZ_CODEX, *, dias: float = DIAS_PADRAO, agora: float | None = None) -> list[Pendencia]:
    agora = time.time() if agora is None else agora
    sessoes = raiz / "sessions"
    if not sessoes.is_dir():
        return []
    titulos = None
    saida = []
    for caminho in _recentes(sessoes.glob("*/*/*/rollout-*.jsonl"), dias, agora):
        try:
            meta = _meta_codex(caminho)
            if meta is None:
                continue
            origem = meta.get("source")
            if not isinstance(origem, str) or origem == "exec":
                continue  # codex exec e subagentes (origem em objeto) ficam de fora
            resposta = _ultima_resposta_codex(_linhas_do_fim(caminho))
        except OSError:
            continue
        if resposta is None or not isinstance(meta.get("id"), str):
            continue
        if titulos is None:
            titulos = _titulos_codex(raiz)
        cwd = meta.get("cwd") if isinstance(meta.get("cwd"), str) else ""
        saida.append(Pendencia(
            fonte="codex",
            id=meta["id"],
            titulo=titulos.get(meta["id"]) or "Conversa sem título",
            projeto=_projeto(cwd),
            quando=resposta["quando"],
            mensagem=_cortar(resposta["texto"]),
            versao=resposta["quando"],
            pergunta=e_pergunta(resposta["texto"]),
            simples=e_simples(resposta["texto"]),
            cwd=cwd,
        ))
    return saida


# -- Noah -------------------------------------------------------------------------


def pendencias_noah() -> list[Pendencia]:
    from assistant import presence

    if not presence.is_enabled():
        return []
    saida = []
    for item in presence.build_presence_items():
        ident = "p-" + hashlib.sha1(f"{item.source}\n{item.why}".encode()).hexdigest()[:12]
        saida.append(Pendencia(
            fonte="noah",
            id=ident,
            titulo=item.source,
            projeto="Noah",
            quando="",
            mensagem=f"{item.why}\n\n→ {item.action}",
            versao=ident,
            pode_responder=False,
        ))
    return saida


# -- itens dispensados ------------------------------------------------------------


class Dispensadas:
    """Chave -> versão dispensada. Uma resposta nova muda a versão e o item volta.

    Fica em LOCAL_STATE_DIR (fora do repositório e da nuvem); um arquivo ilegível
    vale como vazio -- no pior caso o item reaparece, nunca some por engano."""

    def __init__(self, caminho: Path | None = None):
        if caminho is None:
            import config

            caminho = config.LOCAL_STATE_DIR / "central" / "dispensadas.json"
        self.caminho = caminho
        self._trava = threading.Lock()

    def carregar(self) -> dict[str, str]:
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(dados, dict):
            return {}
        return {k: v for k, v in dados.items() if isinstance(k, str) and isinstance(v, str)}

    def marcar(self, chave: str, versao: str) -> None:
        with self._trava:
            dados = self.carregar()
            dados.pop(chave, None)
            dados[chave] = versao
            while len(dados) > MAX_DISPENSADAS:
                dados.pop(next(iter(dados)))
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            fd, temporario = tempfile.mkstemp(dir=self.caminho.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as arquivo:
                json.dump(dados, arquivo, ensure_ascii=False)
            os.replace(temporario, self.caminho)


# -- lista completa ---------------------------------------------------------------


def listar(
    *,
    dias: float = DIAS_PADRAO,
    max_itens: int = MAX_ITENS,
    raiz_claude: Path = RAIZ_CLAUDE,
    raiz_codex: Path = RAIZ_CODEX,
    incluir_noah: bool = True,
    dispensadas: dict[str, str] | None = None,
    agora: float | None = None,
) -> tuple[list[Pendencia], list[str]]:
    """(pendências, fontes que falharam). Conversas da mais recente para a mais
    antiga; itens do Noah no fim. Uma fonte que falha é pulada e só nomeada."""
    fontes = [
        ("Claude", lambda: pendencias_claude(raiz_claude, dias=dias, agora=agora)),
        ("Codex", lambda: pendencias_codex(raiz_codex, dias=dias, agora=agora)),
    ]
    if incluir_noah:
        fontes.append(("Noah", pendencias_noah))
    itens: list[Pendencia] = []
    falhas: list[str] = []
    for nome, ler in fontes:
        try:
            itens.extend(ler())
        except Exception:  # noqa: BLE001 -- uma fonte quebrada não derruba as outras
            falhas.append(nome)
    dispensadas = dispensadas or {}
    itens = [i for i in itens if dispensadas.get(i.chave) != i.versao]
    conversas = sorted((i for i in itens if i.fonte != "noah"), key=lambda i: i.quando, reverse=True)
    noah = [i for i in itens if i.fonte == "noah"]
    return (conversas + noah)[:max_itens], falhas


def formatar_texto(itens: list[Pendencia], falhas: list[str]) -> str:
    """Versão para terminal (``python src/cli.py pendencias``): uma linha de
    cabeçalho por item e as três primeiras linhas da mensagem."""
    nomes = {"claude": "Claude", "codex": "Codex", "noah": "Noah"}
    blocos = []
    for i in itens:
        trecho = "\n".join(f"    {linha}" for linha in i.mensagem.strip().splitlines()[:3])
        blocos.append(f"[{nomes.get(i.fonte, i.fonte)}] {i.titulo} ({i.projeto})\n{trecho}")
    saida = "\n\n".join(blocos) if blocos else "Nada esperando resposta."
    if falhas:
        saida += f"\n\nFonte com problema (pulada): {', '.join(falhas)}"
    return saida
