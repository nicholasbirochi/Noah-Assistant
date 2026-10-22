"""Responder uma pendência retomando a própria conversa, sem editar nada.

A mensagem vai pelo stdin (um texto que comece com ``-`` nunca vira flag) e o
comando é uma lista de argumentos, sem shell. As travas de leitura são as da
própria CLI: modo ``plan`` + só Read/Grep/Glob no Claude; sandbox somente
leitura no Codex. Decisão em docs/ADR-0002.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from central.fontes import Pendencia

TIMEOUT_S = 15 * 60
MAX_SIMULTANEAS = 2
MAX_TEXTO = 4000
MAX_JOBS_GUARDADOS = 30

# Variáveis que um Claude Code pai injeta no ambiente; herdadas, fariam a CLI
# filha se comportar como sessão aninhada.
_PREFIXOS_DO_PAI = ("CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_AGENT_SDK_")
_VARIAVEIS_DO_PAI = {"CLAUDE_PID", "CLAUDE_EFFORT"}

# CLI que vem dentro do app. É a mesma versão que gravou as sessões, então conhece
# o modelo configurado; um `codex` antigo no PATH recusa modelos novos.
CLI_DO_APP = {"codex": Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex")}


class RespostaRecusada(Exception):
    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem


def binario(nome: str) -> str | None:
    """Caminho da CLI: ``NOAH_<NOME>_BIN``, a CLI do app, o PATH e ~/.local/bin."""
    explicito = os.environ.get(f"NOAH_{nome.upper()}_BIN")
    if explicito:
        return explicito
    do_app = CLI_DO_APP.get(nome)
    if do_app and do_app.is_file() and os.access(do_app, os.X_OK):
        return str(do_app)
    achado = shutil.which(nome)
    if achado:
        return achado
    local = Path.home() / ".local" / "bin" / nome
    return str(local) if local.is_file() and os.access(local, os.X_OK) else None


def comando(p: Pendencia, executavel: str) -> list[str]:
    if p.fonte == "claude":
        return [
            executavel, "-p", "--resume", p.id,
            "--permission-mode", "plan",
            "--tools", "Read,Grep,Glob",
            "--strict-mcp-config",
            "--output-format", "text",
        ]
    if p.fonte == "codex":
        return [
            executavel, "exec", "resume",
            "-c", 'sandbox_mode="read-only"',
            "-c", 'approval_policy="never"',
            "--skip-git-repo-check",
            p.id, "-",
        ]
    raise RespostaRecusada(400, "Esta pendência não aceita resposta.")


def ambiente_filho(base: dict[str, str] | None = None) -> dict[str, str]:
    base = dict(os.environ if base is None else base)
    return {
        k: v for k, v in base.items()
        if k not in _VARIAVEIS_DO_PAI and not k.startswith(_PREFIXOS_DO_PAI)
    }


def executar(p: Pendencia, texto: str, *, timeout: float = TIMEOUT_S) -> str:
    """Roda a CLI e devolve a saída. Erros viram RuntimeError com o fim do stderr."""
    executavel = binario(p.fonte)
    if not executavel:
        raise RuntimeError(f"CLI do {p.fonte} não encontrada.")
    if not p.cwd or not Path(p.cwd).is_dir():
        raise RuntimeError("A pasta da conversa não existe mais.")
    try:
        feito = subprocess.run(
            comando(p, executavel),
            input=texto,
            capture_output=True,
            text=True,
            cwd=p.cwd,
            env=ambiente_filho(),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Sem resposta em {int(timeout // 60)} min.") from exc
    if feito.returncode != 0:
        fim = "\n".join((feito.stderr or feito.stdout or "").strip().splitlines()[-5:])
        raise RuntimeError(f"A CLI terminou com código {feito.returncode}." + (f"\n{fim}" if fim else ""))
    return (feito.stdout or "").strip()


@dataclass
class Job:
    id: str
    chave: str
    titulo: str
    fonte: str
    estado: str = "rodando"  # rodando | concluido | erro
    detalhe: str = ""
    inicio: float = field(default_factory=time.time)
    fim: float | None = None

    def para_json(self) -> dict:
        return {
            "id": self.id, "chave": self.chave, "titulo": self.titulo, "fonte": self.fonte,
            "estado": self.estado, "detalhe": self.detalhe,
            "inicio": self.inicio, "fim": self.fim,
        }


class Respostas:
    """Uma resposta por conversa por vez, no máximo ``MAX_SIMULTANEAS`` ao mesmo tempo."""

    def __init__(self, executor=executar, *, max_simultaneas: int = MAX_SIMULTANEAS):
        self._executor = executor
        self._max = max_simultaneas
        self._trava = threading.Lock()
        self._jobs: dict[str, Job] = {}

    def iniciar(self, p: Pendencia, texto: str) -> Job:
        texto = texto.strip()
        if not p.pode_responder:
            raise RespostaRecusada(400, "Esta pendência não aceita resposta.")
        if not texto:
            raise RespostaRecusada(400, "Escreva a resposta.")
        if len(texto) > MAX_TEXTO:
            raise RespostaRecusada(413, f"Resposta acima de {MAX_TEXTO} caracteres.")
        with self._trava:
            rodando = [j for j in self._jobs.values() if j.estado == "rodando"]
            if any(j.chave == p.chave for j in rodando):
                raise RespostaRecusada(409, "Já há uma resposta em andamento nesta conversa.")
            if len(rodando) >= self._max:
                raise RespostaRecusada(429, f"Já há {self._max} respostas em andamento.")
            job = Job(id=uuid.uuid4().hex[:12], chave=p.chave, titulo=p.titulo, fonte=p.fonte)
            self._jobs[job.id] = job
            self._podar()
        threading.Thread(target=self._rodar, args=(job, p, texto), daemon=True).start()
        return job

    def _rodar(self, job: Job, p: Pendencia, texto: str) -> None:
        try:
            saida = self._executor(p, texto)
            estado, detalhe = "concluido", saida
        except Exception as exc:  # noqa: BLE001 -- o erro vira estado visível na página
            estado, detalhe = "erro", str(exc) or exc.__class__.__name__
        with self._trava:
            job.estado, job.detalhe, job.fim = estado, detalhe[-2000:], time.time()

    def _podar(self) -> None:
        terminados = sorted((j for j in self._jobs.values() if j.estado != "rodando"), key=lambda j: j.inicio)
        while len(self._jobs) > MAX_JOBS_GUARDADOS and terminados:
            self._jobs.pop(terminados.pop(0).id)

    def lista(self) -> list[dict]:
        with self._trava:
            return [j.para_json() for j in sorted(self._jobs.values(), key=lambda j: j.inicio, reverse=True)]

    def ocupadas(self) -> set[str]:
        with self._trava:
            return {j.chave for j in self._jobs.values() if j.estado == "rodando"}
