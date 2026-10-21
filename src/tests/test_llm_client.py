import copy

import pytest

from assistant import llm_client
from assistant.providers import ProviderResponse, ToolCallRequest
from resume import store
from resume.schema import Bilingual, Certification, PersonalInfo, Resume, SkillCategory


class ScriptedProvider:
    """Fake LocalLLMProvider: returns canned responses in sequence and
    records the exact `messages` list it was called with each time, so tests
    can assert history (including tool_calls) was preserved across turns."""

    def __init__(self, responses: list[ProviderResponse]):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat(self, messages, tool_specs):
        self.calls.append(copy.deepcopy(messages))
        if not self._responses:
            raise AssertionError("ScriptedProvider ran out of canned responses")
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def reset_provider_singleton():
    original = llm_client._provider
    yield
    llm_client._provider = original


def test_send_turn_no_tool_calls_returns_content_directly():
    provider = ScriptedProvider([ProviderResponse(content="Olá, Senhor Nicholas.")])
    llm_client._provider = provider

    messages = [{"role": "user", "content": "Explique a fotossíntese."}]
    reply = llm_client.send_turn(messages)

    assert reply == "Olá, Senhor Nicholas."
    assert len(provider.calls) == 1
    assert messages[-1] == {"role": "assistant", "content": "Olá, Senhor Nicholas."}


def test_send_turn_executes_real_tool_and_preserves_history():
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="",
                tool_calls=[ToolCallRequest(name="list_supported_sites", arguments={})],
            ),
            ProviderResponse(content="Os sites suportados são esses."),
        ]
    )
    llm_client._provider = provider

    messages = [{"role": "user", "content": "quais sites você já suporta?"}]
    reply = llm_client.send_turn(messages)

    assert reply == "Os sites suportados são esses."
    assert len(provider.calls) == 2

    # First assistant turn must carry tool_calls so the model can make sense
    # of the following tool-role result on the next call.
    first_assistant_msg = provider.calls[1][-2]
    assert first_assistant_msg["role"] == "assistant"
    assert first_assistant_msg["tool_calls"] == [
        {"function": {"name": "list_supported_sites", "arguments": {}}}
    ]

    tool_result_msg = provider.calls[1][-1]
    assert tool_result_msg["role"] == "tool"
    assert tool_result_msg["tool_name"] == "list_supported_sites"
    assert "LinkedIn" in tool_result_msg["content"]


def test_send_turn_unknown_tool_name_reports_error_without_raising():
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="", tool_calls=[ToolCallRequest(name="ferramenta_fantasma", arguments={})]
            ),
            ProviderResponse(content="tudo bem"),
        ]
    )
    llm_client._provider = provider

    messages = [{"role": "user", "content": "faça algo impossível"}]
    llm_client.send_turn(messages)

    tool_result_msg = messages[-2]
    assert "desconhecida" in tool_result_msg["content"].lower()


def test_send_turn_reports_tool_call_errors_instead_of_raising():
    # Real, observed failure: the model hallucinated an argument
    # (read_resume(path=...) -- read_resume takes none) -- this used to
    # propagate a TypeError all the way out of send_turn(), which
    # run_voice_loop misdiagnosed as a mic problem and silently dropped
    # the user's whole turn.
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="",
                tool_calls=[ToolCallRequest(name="read_resume", arguments={"path": "x"})],
            ),
            ProviderResponse(content="Desculpe, tive um problema -- pode repetir?"),
        ]
    )
    llm_client._provider = provider

    messages = [{"role": "user", "content": "me mostra o currículo"}]
    reply = llm_client.send_turn(messages)  # must not raise

    assert reply == "Desculpe, tive um problema -- pode repetir?"
    tool_result_msg = messages[-2]
    assert tool_result_msg["role"] == "tool"
    assert "erro" in tool_result_msg["content"].lower()


def test_send_turn_stops_after_max_iterations():
    always_tool_call = ProviderResponse(
        content="", tool_calls=[ToolCallRequest(name="list_supported_sites", arguments={})]
    )
    provider = ScriptedProvider([always_tool_call] * llm_client.MAX_TOOL_ITERATIONS)
    llm_client._provider = provider

    messages = [{"role": "user", "content": "insista para sempre"}]
    reply = llm_client.send_turn(messages)

    assert "perdi" in reply.lower()
    assert len(provider.calls) == llm_client.MAX_TOOL_ITERATIONS


def test_specialization_summary_grounded_in_real_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESUME_PATH", tmp_path / "resume.json")
    monkeypatch.setattr(store, "BACKUPS_DIR", tmp_path / "backups")
    resume = Resume(
        personal_info=PersonalInfo(full_name="Fulano", phone="A"),
        summary=Bilingual(pt="Resumo."),
        skills=[SkillCategory(category="Programming", items=["Python", "SQL"])],
        certifications=[Certification(name="Data Science for Beginners")],
    )
    store.save(resume)

    summary = llm_client._specialization_summary()

    assert "Python" in summary
    assert "SQL" in summary
    assert "Data Science for Beginners" in summary


def test_specialization_summary_empty_when_resume_unreadable(monkeypatch):
    def raise_it():
        raise FileNotFoundError("no resume yet")

    monkeypatch.setattr(store, "load", raise_it)

    assert llm_client._specialization_summary() == ""


def test_build_system_prompt_includes_specialization_when_available(monkeypatch):
    monkeypatch.setattr(llm_client, "_specialization_summary", lambda: "Habilidades técnicas dele: Python.")

    prompt = llm_client._build_system_prompt()

    assert "Python" in prompt
    assert "Senhor Nicholas" in prompt  # existing instructions preserved
    assert "Fale o mínimo necessário" in prompt  # conciseness rules preserved


def test_build_system_prompt_still_valid_when_resume_unreadable(monkeypatch):
    monkeypatch.setattr(llm_client, "_specialization_summary", lambda: "")

    prompt = llm_client._build_system_prompt()

    assert "Senhor Nicholas" in prompt
    assert "Fale o mínimo necessário" in prompt


def test_send_turn_uses_a_fresh_system_prompt_each_call(monkeypatch):
    monkeypatch.setattr(llm_client, "_build_system_prompt", lambda: "PROMPT DE TESTE")
    provider = ScriptedProvider([ProviderResponse(content="ok")])
    llm_client._provider = provider

    llm_client.send_turn([{"role": "user", "content": "analise este exemplo"}])

    assert provider.calls[0][0] == {"role": "system", "content": "PROMPT DE TESTE"}


@pytest.mark.parametrize("texto,esperado", [
    ("Boa tarde, Noah! Tudo bem?", "Boa tarde! Tudo bem!"),
    ("Olá, Noah, tudo bem?", "Tudo bem! E por aí?"),
    ("Obrigado!", "Por nada!"),
    ("Opa, beleza?", "Opa! Beleza, e você?"),
    ("Opa, Noah, beleza?", "Opa! Beleza, e você?"),
    ("E aí, beleza?", "Opa! Beleza, e você?"),
])
def test_fastpath_responde_frase_exata_sem_carregar_provider(monkeypatch, texto, esperado):
    monkeypatch.setattr(llm_client, "_get_provider", lambda: pytest.fail("não deve chamar modelo"))
    messages = [{"role": "user", "content": texto}]

    resposta = llm_client.send_turn(messages)

    assert resposta == esperado
    assert messages[-1] == {"role": "assistant", "content": resposta}


def test_fastpath_nao_classifica_pergunta_factual_ou_de_identidade():
    assert llm_client._resposta_fastpath("Quem é você?") is None
    assert llm_client._resposta_fastpath("Como está o projeto Noah?") is None
    assert llm_client._resposta_fastpath("Quanto é 2 + 2?") is None


def test_cancelamento_apos_resposta_do_modelo_impede_execucao_de_ferramenta(monkeypatch):
    provider = ScriptedProvider([
        ProviderResponse(content="", tool_calls=[ToolCallRequest(name="cancel_test", arguments={})])
    ])
    llm_client._provider = provider
    executou = []
    monkeypatch.setitem(llm_client._functions_by_name, "cancel_test", lambda: executou.append(True))
    verificacoes = iter([False, False, False, False, True])

    with pytest.raises(RuntimeError, match="cancelado"):
        llm_client.send_turn(
            [{"role": "user", "content": "execute uma tarefa"}],
            should_cancel=lambda: next(verificacoes),
        )
    assert executou == []


# --- Claimed action without a tool (observed live on qwen2.5:7b, 2026-10-19:
# "Adicionei na sua lista de lembretes..." with no tool_call -- nothing done).


def _fake_add_reminder(monkeypatch):
    feitos = []

    def add_reminder(text: str) -> str:
        feitos.append(text)
        return "Lembrete salvo."

    monkeypatch.setitem(llm_client._functions_by_name, "add_reminder", add_reminder)
    return feitos


def test_claim_without_tool_gets_feedback_and_retry_with_real_tool(monkeypatch):
    feitos = _fake_add_reminder(monkeypatch)
    provider = ScriptedProvider(
        [
            ProviderResponse(content="Adicionei na sua lista de lembretes: comprar pão."),
            ProviderResponse(
                content="",
                tool_calls=[ToolCallRequest(name="add_reminder", arguments={"text": "comprar pão"})],
            ),
            ProviderResponse(content="Adicionei o lembrete: comprar pão."),
        ]
    )
    llm_client._provider = provider

    messages = [{"role": "user", "content": "anote um lembrete: comprar pão"}]
    reply = llm_client.send_turn(messages)

    assert reply == "Adicionei o lembrete: comprar pão."
    assert feitos == ["comprar pão"]
    aviso = provider.calls[1][-1]
    assert aviso["role"] == "system"
    assert "nada foi feito" in aviso["content"]
    # The note is a system turn, never a fake user turn.
    assert [m["content"] for m in messages if m["role"] == "user"] == ["anote um lembrete: comprar pão"]


def test_repeated_claim_without_tool_returns_honest_message(monkeypatch):
    feitos = _fake_add_reminder(monkeypatch)
    provider = ScriptedProvider(
        [
            ProviderResponse(content="Adicionei na sua lista de lembretes."),
            ProviderResponse(content="Pronto, já anotei."),
        ]
    )
    llm_client._provider = provider

    reply = llm_client.send_turn([{"role": "user", "content": "anote um lembrete: comprar pão"}])

    assert "nada foi feito" in reply
    assert "anotei" not in reply.lower()
    assert feitos == []  # never executed on the model's behalf
    assert len(provider.calls) == 2


def test_negated_claim_is_not_flagged():
    provider = ScriptedProvider([ProviderResponse(content="Ainda não adicionei; quer que eu adicione?")])
    llm_client._provider = provider

    reply = llm_client.send_turn([{"role": "user", "content": "lembra de comprar pão"}])

    assert reply == "Ainda não adicionei; quer que eu adicione?"
    assert len(provider.calls) == 1


def test_action_claim_after_read_only_tool_is_still_flagged():
    provider = ScriptedProvider(
        [
            ProviderResponse(content="", tool_calls=[ToolCallRequest(name="list_supported_sites", arguments={})]),
            ProviderResponse(content="Atualizei seu currículo na Gupy."),
            ProviderResponse(content="Não atualizei nada; só listei os sites suportados."),
        ]
    )
    llm_client._provider = provider

    reply = llm_client.send_turn([{"role": "user", "content": "atualize meu currículo na gupy"}])

    assert reply == "Não atualizei nada; só listei os sites suportados."
    assert len(provider.calls) == 3


def test_lookup_claim_after_automatic_cerebro_consult_is_fine(monkeypatch):
    def consulta_falsa(messages, cancelado=None):
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "consult_cerebro", "arguments": {"assunto": "x"}}}],
            }
        )
        messages.append({"role": "tool", "content": "[CONSULTA AO CÉREBRO OK] nada", "tool_name": "consult_cerebro"})

    monkeypatch.setattr(llm_client, "_forcar_consulta_cerebro", consulta_falsa)
    provider = ScriptedProvider([ProviderResponse(content="Consultei o Cérebro e não achei essa decisão.")])
    llm_client._provider = provider

    reply = llm_client.send_turn([{"role": "user", "content": "o que o cérebro diz do roadmap?"}])

    assert reply == "Consultei o Cérebro e não achei essa decisão."
    assert len(provider.calls) == 1


def test_fake_cerebro_label_without_consult_is_flagged():
    assert llm_client._alegacao_sem_ferramenta("[CONSULTA AO CÉREBRO OK] Sim, existe.", set()) is not None
    assert llm_client._alegacao_sem_ferramenta("[CONSULTA AO CÉREBRO OK] Sim.", {"consult_cerebro"}) is None


def test_plain_answers_are_not_claims():
    for texto in ("2 + 2 = 4.", "Posso adicionar esse lembrete, se quiser.", "Bom dia, Senhor Nicholas."):
        assert llm_client._alegacao_sem_ferramenta(texto, set()) is None
