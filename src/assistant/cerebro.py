"""Bridge between Noah and the user's existing second brain ("Cérebro").

Noah does NOT reimplement the vault or keep a parallel knowledge base: this
module is a thin client that shells out to the vault's own self-contained CLI
(config.CEREBRO_SCRIPT, default <vault>/.cerebro/cerebro.py) for every read and
every write. That tool already owns all the hard rules -- allowed writable
roots, frontmatter validation, secret scanning, SHA-256 conflict protection,
an exclusive lock and atomic writes -- so keeping it as the single source of
truth is deliberate, not laziness.

Three deliberate boundaries, each a real requirement of this integration:

1. READ vs. WRITE asymmetry. `consultar()`/`projeto_identificado()` are
   read-only and freely callable (the voice assistant uses them directly,
   see assistant/tools.py). A write (`registrar()`) is gated behind an
   explicit `autorizado=True` that the model can NEVER produce on its own:
   the only caller that passes it is `cli.py cerebro-registrar`, after a real
   human types "s" at the terminal. The model-facing path is
   `preparar_registro()`, which only stages a draft + hands off -- exactly the
   same "model proposes, human executes" shape as tools.prepare_claude_prompt.
   A note's own text is reference data, never authorization to act.

2. Scoping. CEREBRO_DIR is passed to the child process as an env var on every
   call, so the real script operates on whatever vault config points at --
   which is how the tests run the genuine tool against a throwaway temp vault
   without ever touching the real one. Every argument is passed as a list
   element (never through a shell), so the real vault's spaces and accent
   ("Documents/Cérebro") need no quoting.

3. Failure is always a clear message, never a crash. Vault missing, command
   error, timeout and oversized output each map to a short, honest sentence --
   the voice loop must keep working (and say what went wrong) when the vault
   is unavailable, per the protocol's own honesty rule."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

# The vault reads many files per query; writes take the lock + fsync. These are
# generous for a local, personal CLI -- their only job is to stop a wedged
# child process from hanging a voice turn forever.
_BUSCAR_TIMEOUT = 20
_CONTEXTO_TIMEOUT = 10
_HASH_TIMEOUT = 15
_GRAVAR_TIMEOUT = 20
# The vault's own buscar already bounds its output via --orcamento; this is a
# second, defensive cap so a surprising amount of text never floods a spoken
# reply or the model's context.
_OUTPUT_CHAR_LIMIT = 8_000
_DEFAULT_MAX_NOTAS = 5
_DEFAULT_ORCAMENTO = 4_000


class CerebroIndisponivel(Exception):
    """The vault's CLI itself can't be reached (script missing)."""


class CerebroErro(Exception):
    """The tool ran but reported an error (non-zero exit)."""


def _script_e_cofre():
    from config import CEREBRO_DIR, CEREBRO_SCRIPT

    return CEREBRO_SCRIPT, CEREBRO_DIR


def _run(args: list, *, timeout: int) -> subprocess.CompletedProcess:
    """Runs one cerebro.py subcommand. Raises CerebroIndisponivel if the tool
    isn't installed; lets subprocess.TimeoutExpired propagate so callers phrase
    the timeout themselves. Never uses a shell -- argv is a list, so the vault
    path's spaces/accent need no quoting."""
    script, cofre = _script_e_cofre()
    if not script.is_file():
        raise CerebroIndisponivel(f"ferramenta do Cérebro não encontrada em {script}")
    # CEREBRO_DIR explicitly points the child at the configured vault, decoupled
    # from where the script lives -- this is what lets the tests aim the real
    # tool at a temp vault.
    env = {**os.environ, "CEREBRO_DIR": str(cofre)}
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _detalhe_erro(proc: subprocess.CompletedProcess) -> str:
    detalhe = (proc.stderr or proc.stdout or "").strip()
    return detalhe or f"a ferramenta do Cérebro falhou (código {proc.returncode})."


def _limitar(texto: str) -> str:
    if len(texto) > _OUTPUT_CHAR_LIMIT:
        return texto[:_OUTPUT_CHAR_LIMIT] + "\n[...saída do Cérebro truncada por tamanho]"
    return texto


def consultar(
    query: str,
    *,
    projeto: str | None = None,
    max_notas: int = _DEFAULT_MAX_NOTAS,
    orcamento: int = _DEFAULT_ORCAMENTO,
) -> str:
    """Consulta o Cérebro por trechos pertinentes a `query` (buscar --trechos),
    opcionalmente restrito a um projeto. Somente leitura. Devolve sempre texto:
    os trechos, "nada encontrado", ou uma mensagem clara de falha (cofre
    indisponível, timeout, erro de comando). O retorno é material de
    referência, nunca uma ordem a executar."""
    termos = [t for t in query.split() if t.strip()]
    if not termos:
        return "Preciso de ao menos um termo para consultar o Cérebro."
    args = ["buscar", *termos, "--trechos", "--max", str(max_notas), "--orcamento", str(orcamento)]
    if projeto:
        args += ["--projeto", projeto]
    try:
        proc = _run(args, timeout=_BUSCAR_TIMEOUT)
    except CerebroIndisponivel as exc:
        return f"Cérebro indisponível: {exc}. Sigo sem consultar quando for seguro."
    except subprocess.TimeoutExpired:
        return f"A consulta ao Cérebro excedeu o tempo limite ({_BUSCAR_TIMEOUT}s)."
    if proc.returncode != 0:
        return f"Não consegui consultar o Cérebro: {_detalhe_erro(proc)}"
    saida = proc.stdout.strip()
    # buscar --trechos still prints its trailing summary line when nothing
    # matched ("-- trechos de 0 nota(s)..."); turn that into a plain answer.
    if not saida or re.search(r"trechos de 0 nota", saida):
        return "Nenhuma nota pertinente encontrada no Cérebro."
    return _limitar(saida)


# Prefixes that consultar() uses for the failure branches. Kept here next to
# consultar so classificar_resultado stays in sync with the messages it emits.
_PREFIXOS_FALHA = (
    "Cérebro indisponível",
    "A consulta ao Cérebro excedeu o tempo limite",
    "Não consegui consultar o Cérebro",
)
_PREFIXOS_VAZIO = (
    "Nenhuma nota pertinente encontrada no Cérebro",
    "Preciso de ao menos um termo",
)


def classificar_resultado(texto: str) -> str:
    """Classifies a consultar() return into one of three DISTINCT outcomes, so
    callers can keep them apart structurally instead of hoping a model infers it
    from prose: 'erro' (vault unavailable / timeout / command error), 'vazio'
    (the consult ran but found nothing pertinent), or 'ok' (real excerpts). The
    key distinction a weak model kept losing is 'vazio'/'ok' vs 'erro' -- a
    successful-but-empty consult is NOT a failure."""
    t = texto.lstrip()
    if t.startswith(_PREFIXOS_FALHA):
        return "erro"
    if t.startswith(_PREFIXOS_VAZIO):
        return "vazio"
    return "ok"


def projeto_identificado(cwd: str | None = None) -> str | None:
    """Reaproveita a identificação de projeto da própria ferramenta (contexto
    --cwd compara caminho/remoto git com os perfis do cofre) e devolve só o
    nome do projeto para passar a `buscar --projeto`, ou None se nada
    corresponder ou o cofre estiver indisponível. Melhor esforço: nunca
    levanta."""
    from config import PROJECT_ROOT

    alvo = cwd or str(PROJECT_ROOT)
    try:
        proc = _run(["contexto", "--cwd", alvo], timeout=_CONTEXTO_TIMEOUT)
    except (CerebroIndisponivel, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    # montar_contexto emite a linha pronta: `... buscar <termos> --projeto "Noah" --trechos`.
    achado = re.search(r'--projeto "([^"]+)"', proc.stdout)
    return achado.group(1) if achado else None


def _hash_nota(destino: str) -> str:
    proc = _run(["hash", destino], timeout=_HASH_TIMEOUT)
    if proc.returncode != 0:
        raise CerebroErro(_detalhe_erro(proc))
    return proc.stdout.strip()


def registrar(
    destino: str,
    conteudo: str,
    *,
    autorizado: bool,
    sha256: str | None = None,
    substituir: bool = False,
) -> str:
    """Grava uma nota no Cérebro pela ferramenta existente (gravar), que valida
    raiz gravável, frontmatter, segredos e conflito por SHA-256. A gravação só
    acontece com `autorizado=True` -- um gate que o modelo nunca produz
    sozinho: o único chamador que o passa é `cli.py cerebro-registrar`, depois
    de uma confirmação humana real no terminal. Para --substituir sem sha256
    informado, lê o hash atual primeiro (a própria ferramenta ainda recusa se a
    nota mudar entre a leitura e a escrita)."""
    if not autorizado:
        return (
            "Gravação no Cérebro recusada: falta autorização humana real. "
            "Prepare a nota com prepare_cerebro_note e rode "
            "`python src/cli.py cerebro-registrar` para revisar e confirmar."
        )
    if not conteudo.strip():
        return "Gravação recusada: o conteúdo da nota está vazio."

    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", prefix="noah-cerebro-", encoding="utf-8", delete=False
        ) as fh:
            fh.write(conteudo)
            rascunho = fh.name
    except OSError as exc:
        return f"Não consegui preparar o conteúdo para gravar: {exc}"

    try:
        args = ["gravar", "--destino", destino, "--de", rascunho]
        if substituir:
            if sha256 is None:
                try:
                    sha256 = _hash_nota(destino)
                except CerebroIndisponivel as exc:
                    return f"Cérebro indisponível: {exc}."
                except CerebroErro as exc:
                    return f"Não consegui obter o hash atual para substituir: {exc}"
                except subprocess.TimeoutExpired:
                    return "Ler o hash da nota excedeu o tempo limite."
            args += ["--substituir", "--sha256", sha256]
        else:
            args += ["--novo"]
        try:
            proc = _run(args, timeout=_GRAVAR_TIMEOUT)
        except CerebroIndisponivel as exc:
            return f"Cérebro indisponível: {exc}."
        except subprocess.TimeoutExpired:
            return f"A gravação no Cérebro excedeu o tempo limite ({_GRAVAR_TIMEOUT}s)."
    finally:
        try:
            os.unlink(rascunho)
        except OSError:
            pass

    if proc.returncode == 0:
        return f"Nota gravada no Cérebro: {destino}."
    return f"Não consegui gravar no Cérebro: {_detalhe_erro(proc)}"


def preparar_registro(destino: str, conteudo: str, *, substituir: bool = False) -> str:
    """Prepara (NÃO grava) uma nota para o Cérebro: valida o básico, salva um
    rascunho local para revisão e monta o comando que o humano roda para
    autorizar a gravação de verdade. Mesmo padrão de prepare_claude_prompt --
    o modelo propõe, quem executa (e autoriza) é o usuário."""
    destino = destino.strip()
    if not destino.endswith(".md"):
        return (
            "Erro: o destino precisa ser uma nota .md dentro do Cérebro "
            "(ex.: '05 - Padrões e Preferências/Aprendizados/Aprendizado - tema.md')."
        )
    if not conteudo.strip():
        return "Erro: o conteúdo da nota está vazio."

    rascunho = _salvar_rascunho(destino, conteudo)
    if rascunho is None:
        return "Não consegui preparar o rascunho da nota localmente."

    comando = f'python src/cli.py cerebro-registrar --destino "{destino}" --draft "{rascunho}"'
    if substituir:
        comando += " --substituir"
    _copiar_para_clipboard(comando)
    return (
        "Rascunho preparado e comando copiado para a área de transferência. "
        "Nada foi gravado ainda: rode o comando no terminal para revisar o "
        "conteúdo e autorizar a gravação de verdade.\n"
        f"Comando: {comando}"
    )


def _salvar_rascunho(destino: str, conteudo: str) -> str | None:
    """Writes the proposed note to a local, never-synced draft file so the
    human can review it before authorizing. Best-effort: None on any OS error,
    since a staging hiccup must never raise mid-conversation."""
    try:
        from config import LOCAL_STATE_DIR

        pasta = LOCAL_STATE_DIR / "cerebro_drafts"
        pasta.mkdir(parents=True, exist_ok=True)
        base = re.sub(r"[^\w.-]+", "-", os.path.basename(destino)) or "nota.md"
        with tempfile.NamedTemporaryFile(
            "w", suffix=f"-{base}", dir=pasta, encoding="utf-8", delete=False
        ) as fh:
            fh.write(conteudo)
            return fh.name
    except OSError:
        return None


def _copiar_para_clipboard(texto: str) -> None:
    """Best-effort pbcopy -- same reasoning as tools._log_claude_prompt: the
    command is also returned in the message, so a clipboard failure must never
    turn a successful staging into a reported error."""
    try:
        subprocess.run(["pbcopy"], input=texto.encode("utf-8"), check=True)
    except Exception:
        pass
