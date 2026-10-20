"""Leitores das pendências: o que, no disco, está esperando uma resposta sua.

Só leitura e só local. Cada fonte é lida por código, sem modelo no caminho, então
nada é inventado: se um arquivo não segue o formato esperado, a linha (ou a
fonte inteira) é pulada -- falha fechada, nunca uma pendência chutada.

- Claude Code: ``~/.claude/projects/<pasta>/<sessão>.jsonl``. Pendente quando a
  última mensagem (fora de subagente) é do assistente, tem texto e terminou o
  turno (sem ``tool_use`` em aberto).
- Codex: ``~/.codex/sessions/AAAA/MM/DD/rollout-*.jsonl`` + títulos em
  ``~/.codex/session_index.jsonl``. Pendente quando o último evento de turno é
  ``task_complete`` com ``last_agent_message``. O Codex Desktop grava ``source``
  "vscode" e entra normalmente; conversas arquivadas (``archived_sessions``) ficam
  de fora, e o banco SQLite do Codex não é lido.
- Noah: os itens da presença (docs/ADR-0001), só leitura e só quando
  ``NOAH_PRESENCE_ENABLED=true``.

Sessões automáticas ficam de fora: ``claude -p`` (entrypoint ``sdk-*``),
``codex exec`` e subagentes do Codex. Decisão em docs/ADR-0002.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

DIAS_PADRAO = 3
MAX_ITENS = 40
BYTES_FIM = 512 * 1024  # só o fim do transcript é lido para achar a última mensagem
LIMITE_TEXTO = 8000
MAX_DISPENSADAS = 500

RAIZ_CLAUDE = Path.home() / ".claude" / "projects"
RAIZ_CODEX = Path.home() / ".codex"

_FIM_DE_TURNO_CLAUDE = {"end_turn", "stop_sequence", "max_tokens"}
_EVENTOS_DE_TURNO_CODEX = {"task_started", "task_complete", "turn_aborted"}


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
    cwd: str = ""  # usado só para retomar a conversa; não vai para a página

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


def _projeto(cwd: str) -> str:
    return Path(cwd).name if cwd else "?"


# -- Claude Code --------------------------------------------------------------

# Metadados que exigem varrer o arquivo inteiro (títulos, origem), guardados por
# (mtime, tamanho) para que a página possa atualizar a cada poucos segundos.
_cache_meta_claude: dict[Path, tuple[int, int, dict]] = {}
_trava_cache = threading.Lock()


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
            cwd=resposta["cwd"],
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
