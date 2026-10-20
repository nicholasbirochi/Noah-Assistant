"""Sinal ao vivo do Cérebro: quem consultou ou registrou nos últimos minutos.

Só leitura e só local, como fontes.py, e sem modelo no caminho. Conta apenas
chamadas de ferramenta que executam a CLI do Cérebro -- texto que só menciona
``cerebro.py`` numa resposta não conta:

- Claude Code: blocos ``tool_use`` do assistente em ``~/.claude/projects``
  (conversa principal e subagentes).
- Codex: ``response_item`` do tipo ``function_call``, ``custom_tool_call`` ou
  ``local_shell_call`` em ``~/.codex/sessions``.
- Noah: o próprio Noah anota só o horário de cada consulta (sem os termos) em
  ``LOCAL_STATE_DIR/central/atividade_cerebro.jsonl``; ver
  ``registrar_consulta_noah``.

``cerebro.py buscar|contexto`` conta como consulta e ``cerebro.py gravar`` como
registro; cada ``auxiliares.py`` é uma tarefa delegada aos auxiliares locais. O
hook de início de sessão roda fora das ferramentas e não entra. Uma fonte que
falha sai em ``falhas`` e fica zerada -- nunca um número chutado.

Partes do Cérebro: cada uso diz também quais pastas do cofre (``00`` a ``07``)
foram tocadas, em ``partes`` (código da pasta -> quantas chamadas). Num
registro vale a pasta do ``--destino``; numa consulta, as pastas dos caminhos
de nota que a própria resposta da ferramenta trouxe (Claude: ``tool_result``
com o mesmo ``tool_use_id``; Codex: ``*_output`` com o mesmo ``call_id``). Só o
código da pasta sai daqui -- nunca termos, trechos ou nomes de nota.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from central.fontes import RAIZ_CLAUDE, RAIZ_CODEX, _linhas_do_fim, _recentes

JANELA_S = 600
CACHE_S = 5.0
MAX_EVENTOS_NOAH = 200

# Executar a CLI, não citá-la: um interpretador Python, o caminho do script
# (com ou sem aspas) e, para o Cérebro, o subcomando.
_PY = r"python[\d.]*\s+(?:\"[^\"]*|'[^']*|[^\s\"']*)"
_CEREBRO = re.compile(_PY + r"cerebro\.py[\"']?\s+(buscar|contexto|gravar)\b")
_AUXILIARES = re.compile(_PY + r"auxiliares\.py\b")
_TIPOS_CODEX = {"function_call", "custom_tool_call", "local_shell_call"}
_SAIDAS_CODEX = {"function_call_output", "custom_tool_call_output", "local_shell_call_output"}
# Pasta do cofre num caminho de nota: "03 - Graphify e Mapas de Projeto/...".
# Exige a barra depois do nome, para não pegar "02 - x" solto num texto.
_PASTA = re.compile(r"(?<![\w-])(0[0-7]) - [^/\n\r\"'`]{1,80}/")
_DESTINO = re.compile(r"--destino(?:=|\s+)[\"']?(0[0-7]) - ")


def _vazio_cerebro() -> dict:
    return {"consultas": 0, "registros": 0, "ultima": None, "partes": {}}


def _vazio_auxiliares() -> dict:
    return {"delegacoes": 0, "ultima": None}


def _quando(texto) -> float | None:
    if not isinstance(texto, str) or not texto:
        return None
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _textos(valor):
    """Cada string de um argumento de ferramenta; uma lista só de strings (argv)
    vira uma linha só, para que ``["python3", "cerebro.py", "buscar"]`` conte."""
    if isinstance(valor, str):
        yield valor
    elif isinstance(valor, list):
        if valor and all(isinstance(v, str) for v in valor):
            yield " ".join(valor)
        else:
            for v in valor:
                yield from _textos(v)
    elif isinstance(valor, dict):
        for v in valor.values():
            yield from _textos(v)


def pastas_citadas(conteudo) -> list[str]:
    """Códigos das pastas do cofre (``"00"`` a ``"07"``) nos caminhos de nota de
    uma saída do Cérebro, sem repetição e em ordem."""
    return sorted({codigo for texto in _textos(conteudo) for codigo in _PASTA.findall(texto)})


def _marcar(partes: dict, codigos) -> None:
    for codigo in set(codigos):
        partes[codigo] = partes.get(codigo, 0) + 1


def _somar(destino_cerebro: dict, destino_aux: dict, argumentos, quando: float) -> bool:
    """Soma a chamada e diz se ela consultou o Cérebro (então a resposta dela
    ainda vai dizer quais pastas foram lidas)."""
    consultou = False
    for texto in _textos(argumentos):
        for sub in _CEREBRO.findall(texto):
            destino_cerebro["registros" if sub == "gravar" else "consultas"] += 1
            destino_cerebro["ultima"] = max(destino_cerebro["ultima"] or 0, quando)
            consultou = consultou or sub != "gravar"
        if "gravar" in _CEREBRO.findall(texto):
            _marcar(destino_cerebro["partes"], _DESTINO.findall(texto))
        delegacoes = len(_AUXILIARES.findall(texto))
        if delegacoes:
            destino_aux["delegacoes"] += delegacoes
            destino_aux["ultima"] = max(destino_aux["ultima"] or 0, quando)
    return consultou


def _chamadas_claude(linha: dict):
    if linha.get("type") != "assistant":
        return
    mensagem = linha.get("message")
    blocos = mensagem.get("content") if isinstance(mensagem, dict) else None
    if not isinstance(blocos, list):
        return
    for bloco in blocos:
        if isinstance(bloco, dict) and bloco.get("type") == "tool_use":
            yield bloco.get("id"), bloco.get("input")


def _resultados_claude(linha: dict):
    if linha.get("type") != "user":
        return
    mensagem = linha.get("message")
    blocos = mensagem.get("content") if isinstance(mensagem, dict) else None
    if not isinstance(blocos, list):
        return
    for bloco in blocos:
        if isinstance(bloco, dict) and bloco.get("type") == "tool_result":
            yield bloco.get("tool_use_id"), bloco.get("content")


def _json_ou_texto(valor):
    if isinstance(valor, str):
        try:
            return json.loads(valor)  # o Codex guarda argumentos e saídas como JSON em texto
        except ValueError:
            pass
    return valor


def _payload_codex(linha: dict, tipos) -> dict | None:
    payload = linha.get("payload")
    if linha.get("type") != "response_item" or not isinstance(payload, dict):
        return None
    return payload if payload.get("type") in tipos else None


def _chamadas_codex(linha: dict):
    payload = _payload_codex(linha, _TIPOS_CODEX)
    if payload is None:
        return
    for campo in ("arguments", "input", "action"):
        valor = _json_ou_texto(payload.get(campo))
        if valor is not None:
            yield payload.get("call_id"), valor


def _resultados_codex(linha: dict):
    payload = _payload_codex(linha, _SAIDAS_CODEX)
    if payload is not None:
        yield payload.get("call_id"), _json_ou_texto(payload.get("output"))


def _contar(arquivos, chamadas, resultados, janela: float, agora: float) -> tuple[dict, dict]:
    cerebro, aux = _vazio_cerebro(), _vazio_auxiliares()
    corte = agora - janela
    for caminho in _recentes(arquivos, janela / 86400, agora):
        try:
            linhas = _linhas_do_fim(caminho)
        except OSError:
            continue
        pendentes = set()  # consultas da janela à espera da resposta da ferramenta
        for linha in linhas:
            quando = _quando(linha.get("timestamp"))
            if quando is None or quando < corte or quando > agora + 60:
                continue
            for ident, argumentos in chamadas(linha):
                if _somar(cerebro, aux, argumentos, quando) and isinstance(ident, str):
                    pendentes.add(ident)
            if pendentes:
                for ident, conteudo in resultados(linha):
                    if ident in pendentes:
                        pendentes.discard(ident)
                        _marcar(cerebro["partes"], pastas_citadas(conteudo))
    return cerebro, aux


def contar_claude(raiz: Path = RAIZ_CLAUDE, *, janela: float = JANELA_S, agora: float | None = None) -> tuple[dict, dict]:
    agora = time.time() if agora is None else agora
    if not raiz.is_dir():
        return _vazio_cerebro(), _vazio_auxiliares()
    arquivos = [*raiz.glob("*/*.jsonl"), *raiz.glob("*/*/subagents/*.jsonl")]
    return _contar(arquivos, _chamadas_claude, _resultados_claude, janela, agora)


def contar_codex(raiz: Path = RAIZ_CODEX, *, janela: float = JANELA_S, agora: float | None = None) -> tuple[dict, dict]:
    agora = time.time() if agora is None else agora
    sessoes = raiz / "sessions"
    if not sessoes.is_dir():
        return _vazio_cerebro(), _vazio_auxiliares()
    return _contar(sessoes.glob("*/*/*/rollout-*.jsonl"), _chamadas_codex, _resultados_codex, janela, agora)


# -- consultas do próprio Noah -----------------------------------------------------


def _arquivo_noah() -> Path:
    import config

    return config.LOCAL_STATE_DIR / "central" / "atividade_cerebro.jsonl"


_trava_noah = threading.Lock()


def registrar_consulta_noah(caminho: Path | None = None, *, agora: float | None = None, partes=()) -> None:
    """Anota o horário de uma consulta do Noah ao Cérebro e, se houver, os
    códigos das pastas que a resposta citou -- nunca os termos nem os trechos.
    Guarda as últimas MAX_EVENTOS_NOAH e nunca levanta: o sinal ao vivo não pode
    atrapalhar a consulta."""
    try:
        caminho = caminho or _arquivo_noah()
        registro = {"t": time.time() if agora is None else agora}
        codigos = sorted({c for c in partes if isinstance(c, str) and re.fullmatch(r"0[0-7]", c)})
        if codigos:
            registro["p"] = codigos
        evento = json.dumps(registro) + "\n"
        with _trava_noah:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            with caminho.open("a", encoding="utf-8") as arquivo:
                arquivo.write(evento)
            if caminho.stat().st_size > MAX_EVENTOS_NOAH * 2 * len(evento):
                linhas = caminho.read_text(encoding="utf-8").splitlines()[-MAX_EVENTOS_NOAH:]
                temporario = caminho.with_suffix(".tmp")
                temporario.write_text("\n".join(linhas) + "\n", encoding="utf-8")
                os.replace(temporario, caminho)
    except Exception:
        pass


def contar_noah(caminho: Path | None = None, *, janela: float = JANELA_S, agora: float | None = None) -> dict:
    agora = time.time() if agora is None else agora
    caminho = caminho or _arquivo_noah()
    cerebro = _vazio_cerebro()
    if not caminho.is_file():
        return cerebro
    for linha in _linhas_do_fim(caminho, 64 * 1024):
        quando = linha.get("t")
        if isinstance(quando, (int, float)) and agora - janela <= quando <= agora + 60:
            cerebro["consultas"] += 1
            cerebro["ultima"] = max(cerebro["ultima"] or 0, float(quando))
            codigos = linha.get("p")
            if isinstance(codigos, list):
                _marcar(cerebro["partes"], [c for c in codigos if isinstance(c, str) and re.fullmatch(r"0[0-7]", c)])
    return cerebro


# -- resumo para a rota ------------------------------------------------------------

_cache: tuple[float, dict] | None = None
_trava_cache = threading.Lock()


def ler_sinal(*, raiz_claude: Path = RAIZ_CLAUDE, raiz_codex: Path = RAIZ_CODEX,
              arquivo_noah: Path | None = None, janela: float = JANELA_S,
              agora: float | None = None, usar_cache: bool = True) -> dict:
    """{janela_s, cerebro: {claude, codex, noah}, auxiliares: {claude, codex}, falhas};
    cada uso do Cérebro traz consultas, registros, ultima e partes (pasta -> n).
    O app consulta a cada poucos segundos; o resultado fica em cache por CACHE_S."""
    global _cache
    agora = time.time() if agora is None else agora
    if usar_cache:
        with _trava_cache:
            if _cache and 0 <= agora - _cache[0] < CACHE_S:
                return _cache[1]
    resultado = {
        "janela_s": int(janela),
        "cerebro": {"claude": _vazio_cerebro(), "codex": _vazio_cerebro(), "noah": _vazio_cerebro()},
        "auxiliares": {"claude": _vazio_auxiliares(), "codex": _vazio_auxiliares()},
        "falhas": [],
    }
    for nome, contar, raiz in (("claude", contar_claude, raiz_claude), ("codex", contar_codex, raiz_codex)):
        try:
            resultado["cerebro"][nome], resultado["auxiliares"][nome] = contar(raiz, janela=janela, agora=agora)
        except Exception:
            resultado["falhas"].append("Claude Code" if nome == "claude" else "Codex")
    try:
        resultado["cerebro"]["noah"] = contar_noah(arquivo_noah, janela=janela, agora=agora)
    except Exception:
        resultado["falhas"].append("Noah")
    if usar_cache:
        with _trava_cache:
            _cache = (agora, resultado)
    return resultado
