"""First step toward the "Apple Private AI Cluster" blueprint's real
near-term goal: a local coding agent capable enough to replace
Claude/Codex for real engineering work, running through the same
LocalLLMProvider abstraction (assistant/providers.py) as the voice
assistant's own tool loop (assistant/llm_client.py) -- same pattern,
different model and a much narrower tool surface.

READ-ONLY, on purpose: no write_file/run_shell tool, and even the one
edit-shaped tool (propose_edit) never touches disk -- it reads the file,
validates a literal snippet the model supplies, and generates the diff
MECHANICALLY (difflib), returning it as a proposal for Nicholas to apply.
The model still only proposes; it was never granted permission to edit
originals. This replaced the earlier strategy where the model hand-wrote
the whole unified diff (whose main failure, measured, was diffs that
simply didn't apply -- wrong line numbers/context), moving the diff
syntax from the model to the program. Mirrors this project's own
established discipline (see sites/gupy.py, sites/infojobs.py -- every
mutating action sits behind an explicit confirmed=True/finalize=True
gate, tested live before ever being trusted) and the blueprint's own
"primeira execução = auditoria somente" rule. A real write/execute step
can be added later the same deliberate way every other real action in
this project was earned, not assumed safe by default.

Current model recommendation (2026-09-20, see
NOAH_Apple_Private_AI_Cluster_MASTER_v3.zip's own
07_MODEL_RUNTIME_STRATEGY.md for the full reasoning, confirmed live):
`qwen2.5-coder:14b` on the current 24 GB machine (~9 GB, fits
comfortably). None of the below is hardcoded here -- set
NOAH_MODEL_CODING in .env. run_coding_task() refuses to run with no
model configured rather than silently falling back to config.LOCAL_MODEL
(the voice assistant's own model, deliberately small/fast for
conversational latency -- see that constant's own comment -- not sized
or chosen for coding capability).

Two real candidates for the future 64 GB Mac mini were pulled onto THIS
machine already (2026-09-20, ~44GB combined, verified against Ollama's
own library pages directly -- not the AI-generated "best models" blog
posts that keep surfacing suspiciously-named entries), specifically so
the download doesn't have to happen again once the Mac mini exists --
Ollama's model storage (~/.ollama/models, content-addressed blobs +
manifests) is a plain directory copy away from being usable on another
Apple Silicon Mac, no re-pull needed:
- `qwen3-coder:30b` (19GB, MoE 30B total/3.3B active, 256K context) --
  the mature, code-specialized pick, unchanged from the original
  recommendation above.
- `nemotron-3.5-lightning:30b` (25GB, MoE 30B total/3B active, 1M
  context) -- NVIDIA, newer, marketed specifically as built "for the
  execution layer of always-on agents", i.e. aimed directly at the real
  failure mode found in scripts/benchmark_coding_agent.py's first run
  (qwen2.5-coder:14b often retrieves the right data via tools but fails
  the final precise-answer synthesis step) -- a real, targeted
  hypothesis to test once hardware allows, not a hunch.
Neither has been run on this 24GB machine -- 19-25GB of weights alone
leaves too little headroom here for KV cache + everything else already
resident; that test only makes sense on the Mac mini.

Workspace-scoped by design (a real, named concern in the blueprint's
own SECURITY/THREAT_MODEL.md -- path traversal): every tool here takes
a path relative to the given workspace root and refuses anything that
resolves outside it, the same deny-by-default principle as the
blueprint's own SECURITY/POLICY_BASELINE.yaml."""

from __future__ import annotations

import difflib
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

from assistant.providers import LocalLLMProvider, get_provider, recover_tool_call_from_content
from assistant.tool_schema import functions_to_tool_specs

MAX_TOOL_ITERATIONS = 12
_READ_FILE_CHAR_LIMIT = 20_000
_TEST_OUTPUT_CHAR_LIMIT = 4_000
_TEST_TIMEOUT_SECONDS = 120
_SEARCH_OUTPUT_CHAR_LIMIT = 4_000
_SEARCH_TIMEOUT_SECONDS = 30
_GIT_OUTPUT_CHAR_LIMIT = 4_000
_GIT_TIMEOUT_SECONDS = 15
# Real noise for a codebase-wide text search -- none of these ever hold
# source the agent should be reading, only generated/vendored output.
_SEARCH_EXCLUDE_DIRS = [".git", "__pycache__", ".venv", "node_modules", ".pytest_cache"]

_SYSTEM_PROMPT = """\
Você é um agente de coding local, rodando inteiramente na máquina do \
usuário (sem nenhuma chamada de rede externa). Sua tarefa é ajudar em \
tarefas reais de engenharia de software dentro do workspace indicado.

Nesta primeira versão você é SOMENTE LEITURA: pode listar diretórios, \
ler arquivos, buscar texto/padrões em vários arquivos de uma vez \
(search_text), consultar o histórico e as mudanças não commitadas do \
git (git_log/git_diff) e rodar a suíte de testes (pytest) -- nunca \
editar ou criar arquivos, nunca rodar comandos além desses. Se a tarefa \
pedida exigir escrever código, responda com a mudança proposta em \
texto (um trecho claro ou diff) para o usuário aplicar manualmente -- \
não finja que aplicou algo que não foi de fato escrito em disco.

Antes de concluir que não há testes, DESCUBRA a estrutura real: comece por \
list_directory(".") e por run_tests() SEM alvo (o pytest encontra os testes \
sozinho, inclusive em subpastas); se precisar, use search_text para achar \
arquivos de teste ("def test", test_*.py, *_test.py). NÃO presuma um diretório \
"tests/" nem desista depois de um único caminho que não existe -- explore a \
raiz primeiro, em poucas tentativas.

Quando indicar como validar, escreva um comando de terminal (por exemplo, \
`python -m pytest`), nunca um JSON de chamada de ferramenta.

Para PROPOR uma mudança de código, primeiro LEIA com read_file o arquivo que \
vai alterar. Depois, em vez de escrever o diff à mão, use a ferramenta \
propose_edit(path, original, replacement): `original` é o trecho LITERAL atual \
do arquivo (copiado exatamente, com a mesma indentação e as mesmas quebras de \
linha, e com contexto suficiente para aparecer uma única vez no arquivo) e \
`replacement` é o trecho que deve substituí-lo. O programa valida o caminho e o \
trecho e gera o diff unificado sozinho -- você NUNCA escreve a sintaxe do diff à \
mão. Para mudar mais de um arquivo, chame propose_edit uma vez por arquivo. Ela \
nunca grava nada em disco: é só uma proposta para o Nicholas aplicar. Na resposta \
final, mostre o(s) diff(s) que propose_edit devolveu.

Seja direto e técnico. Não invente conteúdo de arquivo que você não \
leu de verdade com read_file.

Responda exatamente o que foi perguntado, de forma direta e objetiva -- \
se a pergunta pede um dado específico (um nome de variável, um valor, \
uma linha), dê esse dado primeiro, sem um resumo geral do arquivo \
inteiro antes ou depois. Um resumo amplo só quando isso é literalmente \
o que foi pedido."""


class WorkspaceViolation(Exception):
    """Raised when a tool call tries to reach outside the workspace root."""


def _resolve_within_workspace(workspace: Path, relative_path: str) -> Path:
    candidate = (workspace / relative_path).resolve()
    if not candidate.is_relative_to(workspace):
        raise WorkspaceViolation(f"Caminho fora do workspace: {relative_path!r}")
    return candidate


def _gerar_diff_unificado(rel_path: str, antigo: str, novo: str) -> str:
    """Gera MECANICAMENTE (difflib, biblioteca padrão) um diff unificado que
    aplica com `git apply`: cabeçalhos `a/<path>`/`b/<path>` e hunks `@@` com as
    linhas de contexto reais e a numeração correta. O modelo nunca escreve o diff
    à mão (a principal causa, na avaliação anterior, de patches que não aplicavam)
    -- ele só fornece o trecho original e o substituto; o programa calcula o
    resto. splitlines(keepends=True) preserva as quebras de linha reais de cada
    linha, então o diff bate byte a byte com o arquivo em disco."""
    return "".join(
        difflib.unified_diff(
            antigo.splitlines(keepends=True),
            novo.splitlines(keepends=True),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
        )
    )


def make_tools(workspace: Path) -> list[Callable]:
    """Builds the read-only tool set bound to one specific workspace root
    -- a fresh closure per call so two concurrent tasks (different
    workspaces) never share or leak each other's path scoping."""

    def read_file(path: str) -> str:
        """Lê o conteúdo de um arquivo de texto dentro do workspace.

        Args:
            path: caminho relativo ao workspace (ex.: "src/config.py").
        """
        target = _resolve_within_workspace(workspace, path)
        if not target.is_file():
            return f"Arquivo não encontrado: {path}"
        try:
            return target.read_text(encoding="utf-8")[:_READ_FILE_CHAR_LIMIT]
        except UnicodeDecodeError:
            return f"Arquivo binário, não é possível ler como texto: {path}"

    def list_directory(path: str = ".") -> str:
        """Lista arquivos e subpastas de um diretório dentro do workspace.

        Args:
            path: caminho relativo ao workspace (padrão: raiz do workspace).
        """
        target = _resolve_within_workspace(workspace, path)
        if not target.is_dir():
            return f"Diretório não encontrado: {path}. Use list_directory('.') para ver a raiz do workspace."
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
        return "\n".join(entries) or "(vazio)"

    def run_tests(target: str = "") -> str:
        """Roda a suíte de testes (pytest) dentro do workspace -- somente
        leitura, nunca modifica nada.

        Args:
            target: caminho ou nó de teste específico (padrão: suíte inteira).
        """
        # sys.executable, not a bare "python3": run the tests with the SAME
        # interpreter that is running the agent (Noah's venv, which has pytest),
        # so they don't fail merely because the system python3 on PATH lacks it.
        args = [sys.executable, "-m", "pytest", "-q"]
        if target:
            alvo = _resolve_within_workspace(workspace, target)
            if not alvo.exists():
                # Don't run pytest on a guessed, missing path (it gives a cryptic
                # error the model read as "no tests"). Point back at discovery.
                return (
                    f"Caminho de teste não encontrado: {target}. Não presuma a estrutura -- "
                    "rode run_tests() SEM 'target' para a suíte inteira (o pytest acha os testes, "
                    "mesmo em subpastas), ou use list_directory('.') e search_text('def test')."
                )
            args.append(alvo.as_posix())
        try:
            result = subprocess.run(
                args, cwd=workspace, capture_output=True, text=True, timeout=_TEST_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired:
            return f"Testes excederam o tempo limite ({_TEST_TIMEOUT_SECONDS}s)."
        return (result.stdout + result.stderr)[-_TEST_OUTPUT_CHAR_LIMIT:]

    def search_text(pattern: str, path: str = ".") -> str:
        """Busca um texto ou expressão regular nos arquivos de um diretório
        do workspace (equivalente a um grep recursivo).

        Args:
            pattern: texto ou expressão regular (sintaxe grep) a buscar.
            path: diretório relativo ao workspace onde buscar (padrão: raiz do workspace).
        """
        target = _resolve_within_workspace(workspace, path)
        if not target.is_dir():
            return f"Diretório não encontrado: {path}"
        exclude_args = [arg for name in _SEARCH_EXCLUDE_DIRS for arg in ("--exclude-dir", name)]
        try:
            result = subprocess.run(
                ["grep", "-rn", *exclude_args, "-e", pattern, str(target)],
                capture_output=True,
                text=True,
                timeout=_SEARCH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return f"Busca excedeu o tempo limite ({_SEARCH_TIMEOUT_SECONDS}s)."
        # grep's own exit code: 0 = matches found, 1 = none found (not an
        # error), 2+ = a real error (bad pattern, unreadable path, etc.).
        if result.returncode not in (0, 1):
            return f"Erro na busca: {result.stderr.strip()}"
        matches = result.stdout.strip()
        return matches[:_SEARCH_OUTPUT_CHAR_LIMIT] if matches else "Nenhuma ocorrência encontrada."

    def git_log(max_count: int = 10) -> str:
        """Mostra o histórico recente de commits do workspace.

        Args:
            max_count: quantos commits mostrar, do mais recente pro mais antigo (padrão: 10).
        """
        try:
            result = subprocess.run(
                ["git", "log", f"-{max_count}", "--oneline"],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return f"git log excedeu o tempo limite ({_GIT_TIMEOUT_SECONDS}s)."
        if result.returncode != 0:
            return f"Não é um repositório git ou ocorreu um erro: {result.stderr.strip()}"
        return result.stdout.strip() or "(sem commits)"

    def git_diff(path: str = "") -> str:
        """Mostra as mudanças ainda não commitadas do workspace (git diff).

        Args:
            path: caminho relativo ao workspace pra restringir o diff (padrão: workspace inteiro).
        """
        args = ["git", "diff"]
        if path:
            args.append(_resolve_within_workspace(workspace, path).as_posix())
        try:
            result = subprocess.run(
                args, cwd=workspace, capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired:
            return f"git diff excedeu o tempo limite ({_GIT_TIMEOUT_SECONDS}s)."
        if result.returncode != 0:
            return f"Não é um repositório git ou ocorreu um erro: {result.stderr.strip()}"
        return (result.stdout.strip() or "(sem mudanças)")[:_GIT_OUTPUT_CHAR_LIMIT]

    def propose_edit(path: str, original: str, replacement: str) -> str:
        """Propõe uma edição de código de forma mecânica e segura, SEM NUNCA
        gravar em disco: você dá o caminho, o trecho ORIGINAL literal (copiado
        exatamente do arquivo, que você já leu com read_file) e o trecho
        SUBSTITUTO; o programa valida e gera o diff unificado sozinho.

        Prefira SEMPRE esta ferramenta a escrever um diff à mão. O trecho
        original precisa aparecer EXATAMENTE UMA VEZ no arquivo -- inclua linhas
        de contexto suficientes ao redor para que seja único. Em caso de sucesso,
        devolve o diff pronto para `git apply`; nenhuma mudança é escrita -- é só
        uma proposta para o Nicholas aplicar.

        Rejeita: caminho fora do workspace ou inexistente; trecho original que
        não aparece no arquivo (provavelmente copiado de memória, não do arquivo
        real); e trecho ambíguo, que aparece mais de uma vez.

        Args:
            path: caminho relativo ao workspace do arquivo a editar.
            original: trecho literal atual do arquivo, copiado exatamente (mesma
                indentação e quebras de linha), com contexto bastante para ser único.
            replacement: trecho que deve substituir o original.
        """
        target = _resolve_within_workspace(workspace, path)
        if not target.is_file():
            return (
                f"Arquivo não encontrado: {path}. Leia o arquivo com read_file antes "
                "de propor a edição."
            )
        try:
            conteudo = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"Arquivo binário, não é possível editar como texto: {path}"
        if not original:
            return "Trecho original vazio: forneça o texto literal atual que deve ser substituído."
        ocorrencias = conteudo.count(original)
        if ocorrencias == 0:
            return (
                f"Trecho original não encontrado em {path}. Ele precisa ser copiado "
                "EXATAMENTE do arquivo (mesma indentação e quebras de linha), não de "
                "memória. Releia com read_file e copie o trecho exato."
            )
        if ocorrencias > 1:
            return (
                f"Trecho original ambíguo em {path}: aparece {ocorrencias} vezes. "
                "Inclua mais linhas de contexto ao redor para que ele identifique um "
                "único lugar no arquivo."
            )
        if original == replacement:
            return "O trecho substituto é igual ao original -- não há mudança a propor."
        novo = conteudo.replace(original, replacement, 1)
        return _gerar_diff_unificado(path, conteudo, novo)

    return [read_file, list_directory, run_tests, search_text, git_log, git_diff, propose_edit]


# This recovery now lives in providers.py so llm_client.py can reuse the exact
# same implementation (passing its own, stricter set of eligible tool names --
# read-only only, since that surface also has data-mutating tools). The alias
# keeps this module's historical name, and every caller/test importing it from
# here, working unchanged. All of THIS agent's tools are read-only, so it keeps
# passing its whole tool set as eligible.
_recover_tool_call_from_content = recover_tool_call_from_content


def _recuperar_chamada(content: str, known_tool_names: set):
    """Recupera uma tool-call escrita como texto: o conteúdo INTEIRO (via
    providers.recover_tool_call_from_content) OU um bloco ```json ...``` embutido
    em prosa -- o modo como este modelo às vezes emite a chamada de investigação
    (observado no projeto B: um list_directory embutido num parágrafo de "passos"
    que a recuperação só-de-conteúdo-inteiro não via). Reutiliza a recuperação
    compartilhada (que valida nome e formato dos argumentos) em cada candidato e
    devolve a primeira chamada válida. Seguro executar aqui porque TODAS as
    ferramentas deste agente são de leitura; em llm_client, onde há ferramentas
    que gravam, a recuperação segue restrita ao conteúdo inteiro e a ferramentas
    de leitura."""
    chamada = recover_tool_call_from_content(content, known_tool_names)
    if chamada is not None:
        return chamada
    for bloco in re.findall(r"```(?:json)?\s*(.*?)```", content, re.DOTALL):
        chamada = recover_tool_call_from_content(bloco.strip(), known_tool_names)
        if chamada is not None:
            return chamada
    return None


def _parece_propor_patch(content: str) -> bool:
    """True if the answer proposes a code change (a diff or a code block) -- used
    to require the file to have been read first, so the diff can cite the real
    lines."""
    if re.search(r"^\s*(diff --git|--- |\+\+\+ |@@ )", content, re.M):
        return True
    return re.search(r"```(?:diff|python|py)\b", content) is not None


def run_coding_task(task: str, workspace_dir: str, *, model: str | None = None) -> str:
    """Executa uma tarefa de coding, somente leitura, usando o modelo dado
    (ou, se omitido, o configurado em NOAH_MODEL_CODING). Retorna a
    resposta final do modelo (texto) -- nunca aplica nenhuma mudança em
    disco.

    `model` existe para permitir comparar modelos diferentes no mesmo
    processo (ver scripts/benchmark_coding_agent.py) -- `config.CODING_MODEL`
    sozinho não serviria pra isso, já que é lido uma vez só na importação
    do módulo `config`, não a cada chamada."""
    if model is None:
        from config import CODING_MODEL

        model = CODING_MODEL

    if not model:
        return (
            "NOAH_MODEL_CODING não está configurado -- defina no .env antes "
            "de usar o agente de coding (ver assistant/coding_agent.py)."
        )

    workspace = Path(workspace_dir).resolve()
    if not workspace.is_dir():
        return f"Workspace não encontrado: {workspace_dir}"

    tools = make_tools(workspace)
    functions_by_name = {f.__name__: f for f in tools}
    tool_specs = functions_to_tool_specs(tools)

    provider: LocalLLMProvider = get_provider(model=model)
    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    known = set(functions_by_name)
    leu_arquivo = False
    nudges_leitura = 0
    for _ in range(MAX_TOOL_ITERATIONS):
        response = provider.chat(messages=messages, tool_specs=tool_specs)

        tool_calls = response.tool_calls
        if not tool_calls:
            # The model may write the call as JSON -- whole-content or embedded
            # in prose. Recover and EXECUTE it (all tools here are read-only);
            # never kill a valid investigation call. Validation-as-command in the
            # final answer is steered by the system prompt, not by a guard.
            recovered = _recuperar_chamada(response.content, known)
            if recovered is not None:
                tool_calls = [recovered]

        # Same reasoning as llm_client.py's send_turn(): the model needs to
        # see its own prior calls to make sense of the "tool"-role results
        # that follow, or multi-turn tool history silently breaks.
        assistant_message: dict = {"role": "assistant", "content": response.content}
        if tool_calls:
            assistant_message["tool_calls"] = [
                {"function": {"name": call.name, "arguments": call.arguments}} for call in tool_calls
            ]
        messages.append(assistant_message)

        if not tool_calls:
            # A patch proposed without ever reading the source tends to cite
            # fabricated lines (so `git apply` rejects it). Send the model to
            # read_file first -- the existing tool -- with a bounded number of
            # nudges, then let it answer.
            if nudges_leitura < 2 and not leu_arquivo and _parece_propor_patch(response.content):
                nudges_leitura += 1
                messages.append({
                    "role": "user",
                    "content": ("Antes de propor o diff, LEIA com read_file o arquivo que vai alterar e "
                                "baseie o diff no conteúdo REAL (linhas e contexto exatos). Depois "
                                "reescreva o patch como um diff unificado que aplique com `git apply`."),
                })
                continue
            return response.content

        for call in tool_calls:
            function = functions_by_name.get(call.name)
            if function is None:
                output = f"Ferramenta desconhecida: {call.name}"
            else:
                try:
                    output = function(**call.arguments)
                except WorkspaceViolation as exc:
                    output = str(exc)
                except Exception as exc:  # noqa: BLE001 -- a bad tool call is the model's mistake to see, not a reason to crash the task
                    output = f"Erro ao executar {call.name}: {exc}"
            if call.name == "read_file" and isinstance(output, str) and not output.startswith(
                ("Arquivo não encontrado", "Arquivo binário")
            ):
                leu_arquivo = True
            messages.append({"role": "tool", "content": str(output), "tool_name": call.name})

    return "Não consegui concluir a tarefa dentro do limite de iterações."
