"""Busca local BM25 no Cérebro -- SOMENTE LEITURA, sem modelo de embedding.

Por que existe: o `buscar --trechos` da CLI do cofre pontua por contagem de
ocorrências literais (com um único grupo de aliases, edita/modifica) e mostra
no máximo 4 linhas por nota. Para o Noah isso perdia variações morfológicas
("modificação" x "modificar") e cortava o contexto. Aqui:

- ranking BM25 (k1=1.2, b=0.75) com radical leve em português e um punhado
  de grupos de sinônimos (peso reduzido para a expansão);
- título da nota pesa mais que o corpo; seções "estado atual" pesam mais e
  "histórico" menos, como na CLI;
- trechos maiores: até `linhas_por_nota` linhas pertinentes por nota, cada uma
  com uma linha de contexto antes e depois, fundidas em blocos contíguos;
- o orçamento de caracteres é dividido entre as notas: primeiro garante uma
  linha de cada nota (em ordem de relevância) e só depois usa a folga para
  ampliar os trechos das mais relevantes.

Espelha os filtros da CLI do cofre (pastas ocultas, symlinks, Templates, Logs,
saídas do Graphify, status arquivado/obsoleto, filtro --projeto). Se o cofre
não tiver o protocolo, levanta `CofreInvalido` e quem chama cai na CLI, que
continua sendo a fonte oficial das mensagens de erro.

Nunca grava nada: só lê `.md` com `read_text`.
"""

from __future__ import annotations

import math
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Mesmos nomes da CLI do cofre (.cerebro/cerebro.py); duplicados de propósito
# porque o Noah não importa código do cofre, só o chama por subprocess.
PROTOCOLO = "00 - Regras para Agentes/Protocolo dos Agentes.md"
LOGS = "06 - Logs de Tarefas"
TEMPLATES = "07 - Templates"
SAIDAS = "03 - Graphify e Mapas de Projeto/Saídas do Graphify"

K1, B = 1.2, 0.75
PESO_TITULO = 3
PESO_SINONIMO = 0.5
_MAX_BYTES_NOTA = 200_000  # como a CLI: pontua o início de notas enormes

_STOPWORDS = frozenset(
    "a o as os um uma uns umas de do da dos das em no na nos nas por para pra com sem "
    "e ou que se ao aos à às é são ser foi como mais menos muito já não sim mas sobre "
    "entre até seu sua seus suas meu minha isso isto esse essa este esta qual quais "
    "quando onde porque the of to in and or for is on with".split()
)

# Sufixos do mais longo para o mais curto; o radical mantém ao menos 4 letras.
_SUFIXOS = (
    "amentos", "imentos", "amento", "imento", "amente", "mente", "acoes", "icoes",
    "acao", "icao", "ados", "adas", "idos", "idas", "ado", "ada", "ido", "ida",
    "ando", "endo", "indo", "aram", "eram", "iram", "ou", "ar", "er", "ir",
    "as", "es", "os", "a", "e", "o", "s",
)

# Grupos pequenos e verificáveis; cada palavra é reduzida ao radical abaixo.
_SINONIMOS_BRUTOS = (
    ("edita", "modifica", "altera", "muda", "ajusta"),
    ("apaga", "exclui", "remove", "deleta"),
    ("busca", "pesquisa", "procura", "consulta"),
    ("erro", "falha", "bug", "defeito"),
    ("rapido", "veloz", "latencia", "desempenho"),
)


def sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).casefold()


def radical(palavra: str) -> str:
    for sufixo in _SUFIXOS:
        if palavra.endswith(sufixo) and len(palavra) - len(sufixo) >= 4:
            return palavra[: -len(sufixo)]
    return palavra


_SINONIMOS: dict[str, frozenset[str]] = {}
for _grupo in _SINONIMOS_BRUTOS:
    _radicais = frozenset(radical(sem_acento(p)) for p in _grupo)
    for _r in _radicais:
        _SINONIMOS[_r] = _radicais


def tokens(texto: str) -> list[str]:
    return [
        radical(t)
        for t in re.findall(r"\w+", sem_acento(texto))
        if t not in _STOPWORDS and (len(t) > 1 or t.isdigit())
    ]


def termos_consulta(query: str) -> dict[str, float]:
    """Radicais da consulta com peso 1; sinônimos que não estavam nela, peso reduzido."""
    pesos: dict[str, float] = {}
    for t in tokens(query):
        pesos[t] = 1.0
    for t in list(pesos):
        for s in _SINONIMOS.get(t, ()):
            pesos.setdefault(s, PESO_SINONIMO)
    return pesos


class CofreInvalido(Exception):
    pass


# ------------------------------------------------------------------ leitura


def _separar(texto: str) -> tuple[dict, str, int]:
    """(metadados, corpo, nº de linhas do frontmatter). Tolerante: frontmatter
    malformado vira corpo, sem derrubar a busca."""
    if not texto.startswith("---\n"):
        return {}, texto, 0
    fim = texto.find("\n---\n", 3)
    if fim == -1:
        return {}, texto, 0
    bloco, corpo = texto[4:fim], texto[fim + 5 :]
    meta: dict = {}
    lista = None
    for linha in bloco.splitlines():
        item = re.match(r"^\s+-\s+(.*)$", linha)
        if item and lista:
            meta[lista].append(item.group(1).strip().strip("\"'"))
            continue
        par = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", linha)
        if not par:
            continue
        k, v = par.group(1), par.group(2).strip()
        lista = None
        if v == "":
            meta[k], lista = [], k
        elif v.startswith("[") and v.endswith("]"):
            meta[k] = [p.strip().strip("\"'") for p in v[1:-1].split(",") if p.strip()]
        else:
            meta[k] = v.strip("\"'")
    return meta, corpo, texto[: fim + 5].count("\n")


def _peso_linhas(corpo: str) -> list[tuple[str, float, str]]:
    """(seção, peso, linha) por linha; peso herdado: atual=1.5, comum=1, histórico=0.5."""
    secoes: list[tuple[int, str, float]] = []
    saida = []
    for linha in corpo.split("\n"):
        cab = re.match(r"^(#{1,6})\s+(.*)", linha)
        if cab:
            nivel, titulo = len(cab.group(1)), cab.group(2).strip()
            while secoes and secoes[-1][0] >= nivel:
                secoes.pop()
            peso = secoes[-1][2] if secoes else 1.0
            normal = sem_acento(titulo)
            if re.search(r"\b(estado atual|resumo atual|situacao atual|status atual)\b", normal):
                peso = 1.5
            elif re.search(r"\bhistoric[oa]s?\b", normal):
                peso = 0.5
            secoes.append((nivel, titulo, peso))
        sec, peso = (secoes[-1][1], secoes[-1][2]) if secoes else ("", 1.0)
        saida.append((sec, peso, linha))
    return saida


@dataclass
class Nota:
    caminho_rel: str
    tipo: str
    status: str
    projetos: str  # normalizado, para o filtro --projeto
    linhas: list[tuple[str, float, str]]  # (seção, peso, linha) do corpo
    deslocamento: int  # linhas do frontmatter, para numerar como no arquivo
    tf: Counter = field(default_factory=Counter)
    tamanho: float = 0.0
    linhas_tokens: list[set[str]] = field(default_factory=list)


_CACHE: dict[str, tuple[tuple[int, int], Nota]] = {}


def _ler_nota(base: Path, caminho: Path) -> Nota | None:
    try:
        st = caminho.stat()
    except OSError:
        return None
    chave = str(caminho)
    marca = (st.st_mtime_ns, st.st_size)
    if chave in _CACHE and _CACHE[chave][0] == marca:
        return _CACHE[chave][1]
    try:
        with caminho.open("r", encoding="utf-8") as f:
            texto = f.read(_MAX_BYTES_NOTA)
    except (OSError, UnicodeDecodeError):
        return None
    meta, corpo, deslocamento = _separar(texto)
    rel = unicodedata.normalize("NFC", str(caminho.relative_to(base)))
    projetos = meta.get("projeto") or []
    projetos = projetos if isinstance(projetos, list) else [projetos]
    nota = Nota(
        caminho_rel=rel,
        tipo=str(meta.get("tipo", "?")),
        status=str(meta.get("status", "?")),
        projetos=sem_acento(" ".join(projetos) + " " + caminho.stem),
        linhas=_peso_linhas(corpo),
        deslocamento=deslocamento,
    )
    tf: Counter = Counter()
    for t in tokens(caminho.stem):
        tf[t] += PESO_TITULO
    meta_texto = " ".join(
        " ".join(v) if isinstance(v, list) else str(v)
        for k, v in meta.items()
        if k not in ("criado_em", "atualizado_em", "caminho")
    )
    for t in tokens(meta_texto):
        tf[t] += 1
    for _, peso, linha in nota.linhas:
        ts = tokens(linha)
        nota.linhas_tokens.append(set(ts))
        for t in ts:
            tf[t] += peso
    nota.tf = tf
    nota.tamanho = sum(tf.values())
    _CACHE[chave] = (marca, nota)
    return nota


def _arquivos(base: Path):
    saidas = sem_acento(str(base / SAIDAS))
    for raiz, pastas, arquivos in os.walk(base):
        if sem_acento(raiz) == saidas or sem_acento(raiz).startswith(saidas + "/"):
            pastas[:] = []
            continue
        pastas[:] = sorted(
            p for p in pastas if not p.startswith(".") and not os.path.islink(os.path.join(raiz, p))
        )
        for nome in sorted(arquivos):
            caminho = Path(raiz) / nome
            if nome.endswith(".md") and not nome.startswith(".") and not caminho.is_symlink():
                yield caminho


def carregar(base: Path, *, projeto: str | None = None, incluir_logs: bool = False) -> list[Nota]:
    base = Path(base)
    if os.path.islink(base) or not (base / PROTOCOLO).is_file():
        raise CofreInvalido(f"cofre indisponível ou sem protocolo: {base}")
    filtro = sem_acento(projeto) if projeto else None
    resultado = []
    for caminho in _arquivos(base):
        rel = unicodedata.normalize("NFC", str(caminho.relative_to(base)))
        if rel.startswith(TEMPLATES + "/") or (rel.startswith(LOGS + "/") and not incluir_logs):
            continue
        nota = _ler_nota(base, caminho)
        if nota is None or nota.status in ("arquivado", "obsoleto"):
            continue
        if filtro and filtro not in nota.projetos:
            continue
        resultado.append(nota)
    return resultado


# ------------------------------------------------------------------ ranking


def ranquear(notas: list[Nota], pesos: dict[str, float]) -> list[tuple[float, Nota]]:
    if not notas or not pesos:
        return []
    n = len(notas)
    media = sum(nt.tamanho for nt in notas) / n or 1.0
    df = Counter()
    for nt in notas:
        for t in pesos:
            if nt.tf.get(t):
                df[t] += 1
    pontuadas = []
    for nt in notas:
        pontos = 0.0
        for t, w in pesos.items():
            f = nt.tf.get(t, 0.0)
            if not f:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            pontos += w * idf * f * (K1 + 1) / (f + K1 * (1 - B + B * nt.tamanho / media))
        if pontos > 0:
            pontuadas.append((pontos, nt))
    pontuadas.sort(key=lambda p: (-p[0], p[1].caminho_rel))
    return pontuadas


def _idf(notas: list[Nota], pesos: dict[str, float]) -> dict[str, float]:
    n, saida = len(notas), {}
    for t, w in pesos.items():
        d = sum(1 for nt in notas if nt.tf.get(t))
        saida[t] = w * math.log(1 + (n - d + 0.5) / (d + 0.5))
    return saida


def trechos(nota: Nota, idf: dict[str, float], *, linhas_por_nota: int = 8, contexto: int = 1,
            largura: int = 240) -> tuple[list[str], int]:
    """Blocos com as linhas mais pertinentes (soma do idf dos termos distintos ×
    peso da seção) e `contexto` linhas vizinhas, na ordem do arquivo."""
    pontos = []
    for i, ts in enumerate(nota.linhas_tokens):
        s = sum(v for t, v in idf.items() if t in ts)
        if s > 0:
            pontos.append((s * nota.linhas[i][1], i))
    escolhidas = sorted(i for _, i in sorted(pontos, key=lambda p: (-p[0], p[1]))[:linhas_por_nota])
    mostrar: set[int] = set()
    for i in escolhidas:
        for j in range(i - contexto, i + contexto + 1):
            if 0 <= j < len(nota.linhas) and nota.linhas[j][2].strip():
                mostrar.add(j)
    saida, anterior, foco = [], None, set(escolhidas)
    for j in sorted(mostrar):
        if anterior is not None and j > anterior + 1:
            saida.append("      …")
        sec, _, linha = nota.linhas[j]
        texto = linha.strip()
        if len(texto) > largura:
            texto = texto[:largura] + "…"
        marca = ">" if j in foco else " "
        saida.append(f"    {marca} L{nota.deslocamento + j + 1} [{sec or '-'}] {texto}")
        anterior = j
    return saida, len(pontos)


def buscar(base: Path, query: str, *, projeto: str | None = None, max_notas: int = 5,
           orcamento: int = 4_000, linhas_por_nota: int = 8) -> str:
    """Saída no mesmo espírito da CLI (cabeçalho por nota + trechos + resumo
    `-- trechos de N nota(s)`), limitada ao orçamento de caracteres. Devolve ""
    quando nenhuma nota pontua."""
    pesos = termos_consulta(query)
    notas = carregar(base, projeto=projeto)
    ranking = ranquear(notas, pesos)
    if not ranking:
        return ""
    idf = _idf(notas, pesos)
    blocos: list[str] = []
    limite = max(orcamento - 120, 200)  # reserva para o resumo final
    vagas = min(max_notas, len(ranking))

    def custo(xs: list[str]) -> int:
        return sum(len(x) + 1 for x in xs)

    def bloco_de(pontos: float, nota: Nota, n_linhas: int, contexto: int) -> list[str]:
        linhas, n = trechos(nota, idf, linhas_por_nota=n_linhas, contexto=contexto)
        bloco = [f"{pontos:6.2f}  {nota.caminho_rel}  [{nota.tipo}/{nota.status}]"]
        bloco += linhas or ["      (só o nome ou os metadados correspondem)"]
        if n > n_linhas:
            bloco.append(f"      (+{n - n_linhas} linha(s) pertinentes nesta nota)")
        return bloco

    # Como na CLI, as notas mostradas são um prefixo da ordem de relevância.
    # Passo 1: o mínimo de cada uma (a linha mais pertinente, sem contexto)
    # enquanto couber -- a mais relevante sempre aparece, encurtada se preciso.
    escolhidas: list[tuple[float, Nota, list[str]]] = []
    usado = 0
    for pontos, nota in ranking[:vagas]:
        minimo = bloco_de(pontos, nota, 1, 0)
        if usado + custo(minimo) > limite:
            if escolhidas:
                break
            while len(minimo) > 2 and custo(minimo) > limite:
                minimo.pop()
        escolhidas.append((pontos, nota, minimo))
        usado += custo(minimo)
    # Passo 2: a sobra amplia os trechos, da mais relevante para a menos.
    folga = limite - usado
    variantes = [(n, 1) for n in range(linhas_por_nota, 0, -1)]
    for pontos, nota, minimo in escolhidas:
        bloco = minimo
        for n_linhas, contexto in variantes:
            candidato = bloco_de(pontos, nota, n_linhas, contexto)
            extra = custo(candidato) - custo(minimo)
            if extra <= folga:
                bloco, folga = candidato, folga - max(extra, 0)
                break
        blocos += bloco
    mostradas = len(escolhidas)
    omitidas = len(ranking) - mostradas
    resumo = f"-- trechos de {mostradas} nota(s), ranking BM25 local"
    if omitidas:
        resumo += f"; {omitidas} nota(s) menos relevante(s) omitida(s)"
    return "\n".join(blocos + [resumo + "."])
