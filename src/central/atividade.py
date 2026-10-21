"""Aba Central do app Noah: quem está ativo agora, só leitura e só dado real.

Três fontes, cada uma lida sem efeito colateral:

* Ollama (``/api/tags`` e ``/api/ps``): que modelo está instalado e qual está
  carregado na memória neste instante.
* O cofre do Cérebro: notas por pasta (00 a 07) e as notas mexidas por último.
* ``.cerebro/uso-auxiliares.jsonl``: cada chamada a um auxiliar (Qwen,
  Nemotron, Copilot). O registro não diz QUEM chamou (Claude ou Codex), então a
  central também não diz -- mostra o modelo usado e o tipo da tarefa.

Do ``auxiliares.json`` só saem os dois booleanos de habilitação; chaves e
keychain nunca são lidos. Uma fonte que falha vira ``falhas`` e a lista dela
fica vazia, nunca um número chutado.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen

import config

# Espelho de ROUTES em .cerebro/auxiliares.py (ordem de tentativa por tipo).
ROTAS: dict[str, tuple[str, ...]] = {
    "mecanica": ("qwen2.5-coder:7b", "qwen2.5-coder:14b", "nemotron", "copilot"),
    "codigo": ("qwen2.5-coder:14b", "qwen3-coder:30b", "qwen2.5-coder:7b", "copilot", "nemotron"),
    "analise": ("qwen3-coder:30b", "nemotron", "qwen2.5-coder:14b", "copilot"),
}

# Auxiliares remotos: não passam pelo Ollama, só pela habilitação no auxiliares.json.
REMOTOS = {
    "nemotron": ("Nemotron", "NVIDIA, gratuito", "nemotron_habilitado"),
    "copilot": ("Copilot", "GitHub Copilot CLI", "copilot_habilitado"),
}

JANELA_USO_S = 24 * 3600
MAX_EVENTOS = 30
MAX_NOTAS_RECENTES = 8
# Itens por nível na árvore de cada pasta (os mexidos por último primeiro).
MAX_ITENS_POR_PASTA = 40
TIMEOUT_OLLAMA_S = 1.5

LerJson = Callable[[str], dict]


def _ler_url(url: str) -> dict:
    with urlopen(url, timeout=TIMEOUT_OLLAMA_S) as resp:  # noqa: S310 -- só o host local do Ollama
        return json.loads(resp.read() or b"{}")


def _instante(texto: str) -> float | None:
    try:
        return datetime.fromisoformat(texto).timestamp()
    except (TypeError, ValueError):
        return None


def ler_ollama(ler: LerJson = _ler_url, host: str | None = None) -> dict | None:
    """``{instalados, carregados}`` ou None se o Ollama não responder."""
    base = (host or config.OLLAMA_HOST).rstrip("/")
    try:
        tags = ler(f"{base}/api/tags")
        ps = ler(f"{base}/api/ps")
    except (URLError, OSError, ValueError):
        return None
    return {
        "instalados": sorted(m.get("name", "") for m in tags.get("models", []) if m.get("name")),
        "carregados": sorted(m.get("name", "") for m in ps.get("models", []) if m.get("name")),
    }


def ler_uso(arquivo: Path) -> list[dict]:
    """Chamadas registradas pelos auxiliares, mais antigas primeiro. Linha ruim é pulada."""
    chamadas = []
    try:
        linhas = arquivo.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for linha in linhas:
        try:
            dado = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if not isinstance(dado, dict):
            continue
        quando = _instante(dado.get("data"))
        if quando is None:
            continue
        provedor = dado.get("provider")
        modelo = dado.get("model") if provedor == "ollama" else provedor
        if not isinstance(modelo, str) or not modelo:
            continue
        chamadas.append({
            "quando": quando,
            "tipo": dado.get("tipo") if isinstance(dado.get("tipo"), str) else "",
            "modelo": modelo,
            "segundos": dado.get("elapsed_seconds") if isinstance(dado.get("elapsed_seconds"), (int, float)) else None,
        })
    return chamadas


def ler_habilitados(arquivo: Path) -> dict[str, bool]:
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(dados, dict):
        return {}
    return {chave: dados[campo] for chave, (_, _, campo) in REMOTOS.items() if isinstance(dados.get(campo), bool)}


def _oculto(caminho: Path, raiz: Path) -> bool:
    return any(parte.startswith(".") for parte in caminho.relative_to(raiz).parts)


def _arvore(pasta: Path, raiz: Path) -> list[dict]:
    """Subpastas e notas de uma pasta, aninhadas, só com nome e data (nunca o
    conteúdo das notas). Subpasta sem nota fica de fora."""
    itens = []
    for filho in pasta.iterdir():
        if _oculto(filho, raiz):
            continue
        if filho.is_dir():
            notas = [a.stat().st_mtime for a in filho.rglob("*.md") if not _oculto(a, raiz)]
            if notas:
                itens.append({"nome": filho.name, "tipo": "pasta", "notas": len(notas),
                              "atualizada_em": max(notas), "itens": _arvore(filho, raiz)})
        elif filho.suffix == ".md":
            itens.append({"nome": filho.stem, "tipo": "nota", "atualizada_em": filho.stat().st_mtime})
    itens.sort(key=lambda i: i["atualizada_em"], reverse=True)
    return itens[:MAX_ITENS_POR_PASTA]


def ler_cerebro(raiz: Path, *, agora: float) -> tuple[list[dict], list[dict]]:
    """Pastas numeradas do cofre (``NN - Nome``) com contagem de notas, a árvore
    de cada uma (para abrir no Fluxo) e as notas mexidas por último no cofre
    todo. Pastas ocultas (.cerebro, .obsidian) ficam de fora."""
    pastas, notas = [], []
    for pasta in sorted(p for p in raiz.iterdir() if p.is_dir() and p.name[:2].isdigit()):
        arquivos = [a for a in pasta.rglob("*.md") if not _oculto(a, raiz)]
        mtimes = [(a.stat().st_mtime, a) for a in arquivos]
        ultima = max(mtimes, default=None, key=lambda par: par[0])
        numero, _, nome = pasta.name.partition(" - ")
        pastas.append({
            "numero": numero,
            "nome": nome or pasta.name,
            "notas": len(arquivos),
            "atualizada_em": ultima[0] if ultima else None,
            "itens": _arvore(pasta, raiz),
        })
        notas.extend((m, numero, a.stem) for m, a in mtimes)
    notas.sort(reverse=True)
    recentes = [
        {"quando": m, "pasta": numero, "nota": nome}
        for m, numero, nome in notas[:MAX_NOTAS_RECENTES]
        if agora - m <= JANELA_USO_S * 7
    ]
    return pastas, recentes


def _modelos(ollama: dict | None, uso: list[dict], habilitados: dict[str, bool], agora: float) -> list[dict]:
    nomes = list(dict.fromkeys([*(ollama or {}).get("instalados", []),
                                *(m for rota in ROTAS.values() for m in rota)]))
    modelos = []
    for nome in nomes:
        chamadas = [c for c in uso if c["modelo"] == nome]
        remoto = REMOTOS.get(nome)
        modelos.append({
            "id": nome,
            "nome": remoto[0] if remoto else nome,
            "provedor": remoto[1] if remoto else "Ollama local",
            "local": remoto is None,
            # Remoto: habilitado vem do auxiliares.json; local: estar instalado no Ollama.
            "disponivel": habilitados.get(nome) if remoto else (nome in ollama["instalados"] if ollama else None),
            "carregado": (nome in ollama["carregados"]) if (ollama and not remoto) else False,
            "rotas": [tipo for tipo, rota in ROTAS.items() if nome in rota],
            "usos_24h": sum(1 for c in chamadas if agora - c["quando"] <= JANELA_USO_S),
            "ultimo_uso": max((c["quando"] for c in chamadas), default=None),
        })
    return modelos


def ler_atividade(*, cerebro_dir: Path | None = None, ler: LerJson = _ler_url,
                  agora: float | None = None) -> dict:
    agora = time.time() if agora is None else agora
    raiz = Path(cerebro_dir or config.CEREBRO_DIR)
    falhas = []

    ollama = ler_ollama(ler)
    if ollama is None:
        falhas.append("Ollama")
    uso = ler_uso(raiz / ".cerebro" / "uso-auxiliares.jsonl")
    habilitados = ler_habilitados(raiz / ".cerebro" / "auxiliares.json")
    try:
        pastas, recentes = ler_cerebro(raiz, agora=agora)
    except OSError:
        pastas, recentes = [], []
        falhas.append("Cérebro")

    eventos = [
        {"quando": c["quando"], "tipo": "auxiliar", "de": "agente", "para": c["modelo"],
         "texto": f"tarefa {c['tipo'] or 'sem tipo'} para {c['modelo']}"
                  + (f" ({c['segundos']:.0f} s)" if c["segundos"] is not None else "")}
        for c in uso
    ] + [
        {"quando": n["quando"], "tipo": "nota", "de": "agente", "para": "cerebro",
         "texto": f"{n['pasta']} · {n['nota']}"}
        for n in recentes
    ]
    eventos.sort(key=lambda e: e["quando"], reverse=True)

    return {
        "ollama": ollama is not None,
        "modelos": _modelos(ollama, uso, habilitados, agora),
        "rotas": {tipo: list(rota) for tipo, rota in ROTAS.items()},
        "cerebro": {"pastas": pastas},
        "eventos": eventos[:MAX_EVENTOS],
        "falhas": falhas,
    }
