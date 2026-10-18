import copy
import subprocess
import sys

import pytest

import config
from assistant import coding_agent
from assistant.coding_agent import WorkspaceViolation, _recover_tool_call_from_content, make_tools, run_coding_task
from assistant.providers import ProviderResponse, ToolCallRequest


class ScriptedProvider:
    """Same fake as test_llm_client.py's own -- canned responses in
    sequence, records every `messages` list it was called with."""

    def __init__(self, responses: list[ProviderResponse]):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat(self, messages, tool_specs):
        self.calls.append(copy.deepcopy(messages))
        if not self._responses:
            raise AssertionError("ScriptedProvider ran out of canned responses")
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def set_coding_model(monkeypatch):
    monkeypatch.setattr(config, "CODING_MODEL", "qwen2.5-coder:14b")


def _patch_provider(monkeypatch, provider):
    monkeypatch.setattr(coding_agent, "get_provider", lambda model=None, host=None: provider)


def _tools_by_name(workspace) -> dict:
    return {f.__name__: f for f in make_tools(workspace)}


def test_run_coding_task_refuses_when_no_model_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CODING_MODEL", None)

    result = run_coding_task("audite o projeto", str(tmp_path))

    assert "NOAH_MODEL_CODING" in result


def test_run_coding_task_uses_explicit_model_over_config(monkeypatch, tmp_path):
    # scripts/benchmark_coding_agent.py relies on this to compare multiple
    # models in one process -- config.CODING_MODEL alone can't do that,
    # since config is only ever imported (and thus read) once.
    monkeypatch.setattr(config, "CODING_MODEL", "qwen2.5-coder:14b")
    captured = {}

    def fake_get_provider(model=None, host=None):
        captured["model"] = model
        return ScriptedProvider([ProviderResponse(content="ok")])

    monkeypatch.setattr(coding_agent, "get_provider", fake_get_provider)

    result = run_coding_task("audite o projeto", str(tmp_path), model="qwen2.5:7b")

    assert result == "ok"
    assert captured["model"] == "qwen2.5:7b"


def test_run_coding_task_reports_missing_workspace(monkeypatch):
    provider = ScriptedProvider([])
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("audite o projeto", "/nao/existe/de/verdade")

    assert "não encontrado" in result.lower()
    assert provider.calls == []  # never even asks the model


def test_run_coding_task_no_tool_calls_returns_content_directly(monkeypatch, tmp_path):
    provider = ScriptedProvider([ProviderResponse(content="Análise pronta.")])
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("resuma o projeto", str(tmp_path))

    assert result == "Análise pronta."
    assert len(provider.calls) == 1


def test_run_coding_task_executes_real_read_file_tool_and_preserves_history(monkeypatch, tmp_path):
    (tmp_path / "config.py").write_text("LOCAL_MODEL = 'qwen2.5:7b'\n", encoding="utf-8")
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="", tool_calls=[ToolCallRequest(name="read_file", arguments={"path": "config.py"})]
            ),
            ProviderResponse(content="O modelo local é qwen2.5:7b."),
        ]
    )
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("qual modelo o config.py usa?", str(tmp_path))

    assert result == "O modelo local é qwen2.5:7b."
    assert len(provider.calls) == 2

    first_assistant_msg = provider.calls[1][-2]
    assert first_assistant_msg["tool_calls"] == [{"function": {"name": "read_file", "arguments": {"path": "config.py"}}}]

    tool_result_msg = provider.calls[1][-1]
    assert tool_result_msg["role"] == "tool"
    assert "qwen2.5:7b" in tool_result_msg["content"]


def test_run_coding_task_blocks_path_traversal_without_raising(monkeypatch, tmp_path):
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="", tool_calls=[ToolCallRequest(name="read_file", arguments={"path": "../../etc/passwd"})]
            ),
            ProviderResponse(content="Não posso acessar esse caminho."),
        ]
    )
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("leia /etc/passwd", str(tmp_path))

    assert result == "Não posso acessar esse caminho."
    tool_result_msg = provider.calls[1][-1]
    assert "fora do workspace" in tool_result_msg["content"].lower()


def test_run_coding_task_unknown_tool_reports_error_without_raising(monkeypatch, tmp_path):
    provider = ScriptedProvider(
        [
            ProviderResponse(content="", tool_calls=[ToolCallRequest(name="write_file", arguments={"path": "x"})]),
            ProviderResponse(content="Essa ferramenta ainda não existe."),
        ]
    )
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("edite um arquivo", str(tmp_path))

    assert result == "Essa ferramenta ainda não existe."
    tool_result_msg = provider.calls[1][-1]
    assert "desconhecida" in tool_result_msg["content"].lower()


def test_run_coding_task_gives_up_after_max_iterations(monkeypatch, tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    responses = [
        ProviderResponse(content="", tool_calls=[ToolCallRequest(name="read_file", arguments={"path": "a.txt"})])
        for _ in range(coding_agent.MAX_TOOL_ITERATIONS)
    ]
    provider = ScriptedProvider(responses)
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("nunca conclua", str(tmp_path))

    assert "limite de iterações" in result
    assert len(provider.calls) == coding_agent.MAX_TOOL_ITERATIONS


def test_make_tools_read_file_returns_content(tmp_path):
    (tmp_path / "nota.txt").write_text("conteúdo real", encoding="utf-8")
    read_file = _tools_by_name(tmp_path)["read_file"]

    assert read_file("nota.txt") == "conteúdo real"


def test_make_tools_read_file_reports_missing_file(tmp_path):
    read_file = _tools_by_name(tmp_path)["read_file"]

    assert "não encontrado" in read_file("nao_existe.txt").lower()


def test_make_tools_read_file_blocks_path_traversal(tmp_path):
    read_file = _tools_by_name(tmp_path)["read_file"]

    with pytest.raises(WorkspaceViolation):
        read_file("../../etc/passwd")


def test_make_tools_list_directory_lists_real_entries(tmp_path):
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    list_directory = _tools_by_name(tmp_path)["list_directory"]

    entries = list_directory(".").splitlines()

    assert "b.py" in entries
    assert "sub/" in entries


def test_make_tools_list_directory_blocks_path_traversal(tmp_path):
    list_directory = _tools_by_name(tmp_path)["list_directory"]

    with pytest.raises(WorkspaceViolation):
        list_directory("..")


def test_make_tools_run_tests_invokes_pytest_scoped_to_workspace(tmp_path, monkeypatch):
    run_tests = _tools_by_name(tmp_path)["run_tests"]
    captured = {}

    class FakeCompleted:
        stdout = "1 passed"
        stderr = ""

    def fake_run(args, cwd, capture_output, text, timeout):
        captured["args"] = args
        captured["cwd"] = cwd
        return FakeCompleted()

    monkeypatch.setattr(coding_agent.subprocess, "run", fake_run)

    result = run_tests()

    assert captured["args"][:3] == [sys.executable, "-m", "pytest"]
    assert captured["cwd"] == tmp_path
    assert "1 passed" in result


def test_make_tools_run_tests_blocks_path_traversal_in_target(tmp_path):
    run_tests = _tools_by_name(tmp_path)["run_tests"]

    with pytest.raises(WorkspaceViolation):
        run_tests(target="../../../etc")


def test_make_tools_run_tests_hints_when_target_missing(tmp_path, monkeypatch):
    # Alvo presumido que não existe: não roda pytest num caminho inexistente --
    # devolve uma dica para descobrir a estrutura (sem desistir).
    monkeypatch.setattr(coding_agent.subprocess, "run",
                        lambda *a, **k: pytest.fail("não deve rodar pytest num caminho inexistente"))
    run_tests = _tools_by_name(tmp_path)["run_tests"]

    result = run_tests(target="tests")

    assert "não encontrado" in result.lower()
    assert "sem 'target'" in result.lower() or "list_directory" in result


def test_make_tools_search_text_finds_a_real_match(tmp_path):
    (tmp_path / "a.py").write_text("LOCAL_MODEL = 'qwen2.5:7b'\n", encoding="utf-8")
    search_text = _tools_by_name(tmp_path)["search_text"]

    result = search_text("LOCAL_MODEL")

    assert "a.py" in result
    assert "qwen2.5:7b" in result


def test_make_tools_search_text_reports_no_matches(tmp_path):
    (tmp_path / "a.py").write_text("nada relevante aqui\n", encoding="utf-8")
    search_text = _tools_by_name(tmp_path)["search_text"]

    assert "nenhuma ocorrência" in search_text("PADRAO_INEXISTENTE").lower()


def test_make_tools_search_text_excludes_noise_directories(tmp_path):
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.py").write_text("SEGREDO = 1\n", encoding="utf-8")
    (tmp_path / "real.py").write_text("SEGREDO = 2\n", encoding="utf-8")
    search_text = _tools_by_name(tmp_path)["search_text"]

    result = search_text("SEGREDO")

    assert "real.py" in result
    assert "__pycache__" not in result


def test_make_tools_search_text_reports_missing_directory(tmp_path):
    search_text = _tools_by_name(tmp_path)["search_text"]

    assert "não encontrado" in search_text("x", path="nao_existe").lower()


def test_make_tools_git_log_reports_real_commits(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Teste"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "primeiro commit"], cwd=tmp_path, check=True)
    git_log = _tools_by_name(tmp_path)["git_log"]

    assert "primeiro commit" in git_log()


def test_make_tools_git_log_reports_when_not_a_repo(tmp_path):
    git_log = _tools_by_name(tmp_path)["git_log"]

    assert "não é um repositório git" in git_log().lower()


def test_make_tools_git_diff_reports_real_uncommitted_change(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Teste"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "commit inicial"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("mudou\n", encoding="utf-8")
    git_diff = _tools_by_name(tmp_path)["git_diff"]

    result = git_diff()

    assert "mudou" in result
    assert "original" in result


def test_make_tools_git_diff_blocks_path_traversal(tmp_path):
    git_diff = _tools_by_name(tmp_path)["git_diff"]

    with pytest.raises(WorkspaceViolation):
        git_diff(path="../../etc")


def test_make_tools_propose_edit_valid_proposal_generates_applicable_diff(tmp_path):
    # Proposta válida: trecho único, lido do arquivo real. O programa gera o diff
    # mecanicamente e ele aplica de verdade com `git apply` (validação de ponta a
    # ponta: a numeração/contexto do hunk têm de bater byte a byte com o arquivo).
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Teste"], cwd=tmp_path, check=True)
    (tmp_path / "m.py").write_text("def soma(a, b):\n    return a - b\n", encoding="utf-8")
    subprocess.run(["git", "add", "m.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "inicial"], cwd=tmp_path, check=True)
    propose_edit = _tools_by_name(tmp_path)["propose_edit"]

    diff = propose_edit("m.py", "    return a - b\n", "    return a + b\n")

    assert diff.startswith("--- a/m.py")
    assert "+++ b/m.py" in diff
    assert "-    return a - b" in diff
    assert "+    return a + b" in diff
    # O programa nunca escreveu nada: o arquivo em disco segue o original.
    assert (tmp_path / "m.py").read_text(encoding="utf-8") == "def soma(a, b):\n    return a - b\n"
    # E o diff gerado realmente aplica.
    apply = subprocess.run(
        ["git", "apply", "--check"], cwd=tmp_path, input=diff, capture_output=True, text=True
    )
    assert apply.returncode == 0, apply.stderr


def test_make_tools_propose_edit_rejects_snippet_not_in_file(tmp_path):
    # Trecho inexistente (provavelmente citado de memória, não lido do arquivo):
    # rejeita e manda reler, nunca gera um diff inventado.
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
    propose_edit = _tools_by_name(tmp_path)["propose_edit"]

    result = propose_edit("m.py", "x = 99\n", "x = 2\n")

    assert "não encontrado" in result.lower()
    assert "---" not in result  # não é um diff


def test_make_tools_propose_edit_rejects_ambiguous_snippet(tmp_path):
    # Trecho ambíguo: aparece mais de uma vez. Sem contexto único, um diff
    # mecânico mudaria o lugar errado -- então rejeita e pede mais contexto.
    (tmp_path / "m.py").write_text("v = 0\nv = 0\n", encoding="utf-8")
    propose_edit = _tools_by_name(tmp_path)["propose_edit"]

    result = propose_edit("m.py", "v = 0\n", "v = 1\n")

    assert "ambíguo" in result.lower()
    assert "2 vezes" in result


def test_make_tools_propose_edit_rejects_missing_file(tmp_path):
    propose_edit = _tools_by_name(tmp_path)["propose_edit"]

    result = propose_edit("nao_existe.py", "a\n", "b\n")

    assert "não encontrado" in result.lower()


def test_make_tools_propose_edit_blocks_path_traversal(tmp_path):
    # Caminho inválido (fora do workspace): mesma deny-by-default das outras
    # ferramentas -- levanta WorkspaceViolation, nunca lê/propõe fora da raiz.
    propose_edit = _tools_by_name(tmp_path)["propose_edit"]

    with pytest.raises(WorkspaceViolation):
        propose_edit("../../etc/passwd", "root", "hacked")


def test_make_tools_propose_edit_rejects_noop_replacement(tmp_path):
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
    propose_edit = _tools_by_name(tmp_path)["propose_edit"]

    result = propose_edit("m.py", "x = 1\n", "x = 1\n")

    assert "igual ao original" in result.lower()


def test_gerar_diff_unificado_matches_git_apply_for_multiline_change(tmp_path):
    # O helper em si: dado conteúdo antigo e novo, produz um diff que aplica.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Teste"], cwd=tmp_path, check=True)
    antigo = "linha 1\nlinha 2\nlinha 3\n"
    (tmp_path / "f.txt").write_text(antigo, encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True)
    novo = "linha 1\nlinha DOIS\nlinha 3\n"

    diff = coding_agent._gerar_diff_unificado("f.txt", antigo, novo)

    apply = subprocess.run(
        ["git", "apply", "--check"], cwd=tmp_path, input=diff, capture_output=True, text=True
    )
    assert apply.returncode == 0, apply.stderr


def test_run_coding_task_executes_propose_edit_tool_and_returns_the_generated_diff(monkeypatch, tmp_path):
    # Fluxo completo no loop: o modelo lê o arquivo e chama propose_edit; o diff
    # gerado pelo PROGRAMA volta como resultado de ferramenta e o modelo o
    # apresenta. (Aqui o provider é roteirizado -- isto testa a fiação, não o
    # modelo real; a avaliação com o modelo real é feita à parte.)
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="", tool_calls=[ToolCallRequest(name="read_file", arguments={"path": "m.py"})]
            ),
            ProviderResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        name="propose_edit",
                        arguments={"path": "m.py", "original": "x = 1\n", "replacement": "x = 2\n"},
                    )
                ],
            ),
            ProviderResponse(content="Segue o diff proposto."),
        ]
    )
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("troque x para 2", str(tmp_path))

    assert result == "Segue o diff proposto."
    tool_result_msg = provider.calls[-1][-1]
    assert tool_result_msg["role"] == "tool" and tool_result_msg["tool_name"] == "propose_edit"
    assert "--- a/m.py" in tool_result_msg["content"]
    assert "+x = 2" in tool_result_msg["content"]


def test_run_coding_task_recovers_a_real_tool_call_written_as_plain_json_content(monkeypatch, tmp_path):
    # Real, live-observed gap (qwen2.5-coder:14b via Ollama, 2026-09-20):
    # the model picks the right tool but this tag's chat template never
    # populates the structured tool_calls field -- it writes the call out
    # as JSON text in content instead.
    (tmp_path / "config.py").write_text("LOCAL_MODEL = 'qwen2.5:7b'\n", encoding="utf-8")
    provider = ScriptedProvider(
        [
            ProviderResponse(content='{\n  "name": "read_file",\n  "arguments": {"path": "config.py"}\n}'),
            ProviderResponse(content="O modelo local é qwen2.5:7b."),
        ]
    )
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("qual modelo o config.py usa?", str(tmp_path))

    assert result == "O modelo local é qwen2.5:7b."
    tool_result_msg = provider.calls[1][-1]
    assert tool_result_msg["role"] == "tool"
    assert "qwen2.5:7b" in tool_result_msg["content"]


def test_run_coding_task_recovers_a_tool_call_wrapped_in_a_markdown_code_fence(monkeypatch, tmp_path):
    (tmp_path / "a.txt").write_text("conteúdo", encoding="utf-8")
    provider = ScriptedProvider(
        [
            ProviderResponse(content='```json\n{"name": "read_file", "arguments": {"path": "a.txt"}}\n```'),
            ProviderResponse(content="Pronto."),
        ]
    )
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("leia a.txt", str(tmp_path))

    assert result == "Pronto."
    assert provider.calls[1][-1]["content"] == "conteúdo"


def test_recover_tool_call_from_content_ignores_ordinary_prose():
    assert _recover_tool_call_from_content("Aqui está a análise do arquivo.", {"read_file"}) is None


def test_recover_tool_call_from_content_ignores_json_for_an_unknown_tool():
    # Must never guess at a call for a tool that doesn't actually exist in
    # this run -- e.g. a hallucinated or unrelated JSON blob.
    content = '{"name": "delete_everything", "arguments": {}}'
    assert _recover_tool_call_from_content(content, {"read_file"}) is None


def test_recover_tool_call_from_content_ignores_json_missing_arguments_shape():
    content = '{"name": "read_file", "arguments": "config.py"}'
    assert _recover_tool_call_from_content(content, {"read_file"}) is None


def test_recuperar_chamada_de_json_inteiro():
    content = '{"name": "read_file", "arguments": {"path": "x.py"}}'
    chamada = coding_agent._recuperar_chamada(content, {"read_file"})
    assert chamada is not None and chamada.name == "read_file"


def test_recuperar_chamada_de_bloco_embutido_em_prosa():
    # Caso do projeto B: o modelo narra e embute a tool-call num bloco ```json.
    content = ("Para encontrar o defeito vou seguir estes passos:\n```json\n"
               '{"name": "list_directory", "arguments": {}}\n```')
    chamada = coding_agent._recuperar_chamada(content, {"list_directory", "run_tests"})
    assert chamada is not None and chamada.name == "list_directory"


def test_recuperar_chamada_ignora_prosa_pura_e_ferramenta_desconhecida():
    assert coding_agent._recuperar_chamada("Só uma análise em texto.", {"read_file"}) is None
    desconhecida = '```json\n{"name": "deletar_tudo", "arguments": {}}\n```'
    assert coding_agent._recuperar_chamada(desconhecida, {"read_file"}) is None


def test_parece_propor_patch():
    assert coding_agent._parece_propor_patch("```diff\n--- a/x\n+++ b/x\n@@\n-a\n+b\n```") is True
    assert coding_agent._parece_propor_patch("Aqui vai:\n```python\ndef f(): ...\n```") is True
    assert coding_agent._parece_propor_patch("Só uma explicação do defeito, em texto.") is False


def test_run_coding_task_conduz_a_leitura_antes_de_patch_sem_read_file(monkeypatch, tmp_path):
    # Propõe um diff sem ter lido o arquivo -> é conduzido a read_file (limitado).
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
    patch_sem_ler = "Proponho:\n```diff\n--- a/m.py\n+++ b/m.py\n@@\n-x = 1\n+x = 2\n```"
    ler = ProviderResponse(content="", tool_calls=[ToolCallRequest(name="read_file", arguments={"path": "m.py"})])
    final = ProviderResponse(content="Patch final, baseado na leitura real.")
    provider = ScriptedProvider([ProviderResponse(content=patch_sem_ler), ler, final])
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("conserte o bug", str(tmp_path))

    assert result == "Patch final, baseado na leitura real."
    ultima = provider.calls[-1]
    assert any(m.get("role") == "user" and "LEIA" in m.get("content", "") for m in ultima)  # houve condução
    assert any(m.get("tool_name") == "read_file" for m in ultima)                            # leu de verdade


def test_run_coding_task_executa_chamada_de_leitura_embutida_em_prosa(monkeypatch, tmp_path):
    # Regressão do projeto B: uma tool-call de leitura embutida em prosa deve ser
    # EXECUTADA (investigação), não descartada.
    (tmp_path / "a.txt").write_text("conteúdo", encoding="utf-8")
    narr = 'Vou investigar:\n```json\n{"name": "read_file", "arguments": {"path": "a.txt"}}\n```'
    provider = ScriptedProvider([ProviderResponse(content=narr), ProviderResponse(content="Análise pronta.")])
    _patch_provider(monkeypatch, provider)

    result = run_coding_task("investigue", str(tmp_path))

    assert result == "Análise pronta."
    tool_result = provider.calls[1][-1]
    assert tool_result["role"] == "tool" and tool_result["tool_name"] == "read_file"
    assert "conteúdo" in tool_result["content"]  # a leitura realmente executou
