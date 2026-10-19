"""MLXProvider (F4) com backend simulado: mlx-lm não precisa estar instalado e
nenhum peso é carregado ou baixado."""

import json
import sys

import pytest

import config
from assistant import providers
from assistant.providers import MLXProvider, get_provider, parse_tool_call_blocks
from assistant.tool_schema import ToolSpec


class FakeTokenizer:
    def __init__(self):
        self.calls = []

    def apply_chat_template(self, messages, *, tools, add_generation_prompt, tokenize):
        assert add_generation_prompt is True and tokenize is False
        self.calls.append({"messages": messages, "tools": tools})
        return "PROMPT"


class FakeBackend:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.tokenizer = FakeTokenizer()
        self.loads: list[str] = []
        self.generations: list[tuple] = []

    def load(self, repo):
        self.loads.append(repo)
        return "MODEL", self.tokenizer

    def generate(self, model, tokenizer, prompt, max_tokens):
        self.generations.append((model, prompt, max_tokens))
        return self.replies.pop(0)


@pytest.fixture(autouse=True)
def _limpa_cache():
    providers._MLX_LOADED.clear()
    yield
    providers._MLX_LOADED.clear()


def _spec(name):
    return ToolSpec(name=name, description="d", parameters={"type": "object", "properties": {}})


def test_chat_sem_ferramenta_devolve_o_texto():
    backend = FakeBackend("Olá, Senhor Nicholas.")
    resp = MLXProvider("repo/x", max_tokens=64, backend=backend).chat(
        [{"role": "user", "content": "oi"}], []
    )
    assert resp.content == "Olá, Senhor Nicholas." and resp.tool_calls == []
    assert backend.generations == [("MODEL", "PROMPT", 64)]
    assert backend.tokenizer.calls[0]["tools"] is None  # sem ferramentas, nada no template


def test_chat_extrai_tool_call_do_bloco_qwen_e_passa_tools_ao_template():
    texto = 'Vou consultar.\n<tool_call>\n{"name": "consult_cerebro", "arguments": {"assunto": "noah"}}\n</tool_call>'
    backend = FakeBackend(texto)
    resp = MLXProvider("repo/x", backend=backend).chat(
        [{"role": "user", "content": "o que diz o cofre?"}], [_spec("consult_cerebro")]
    )
    assert resp.content == "Vou consultar."
    assert [(c.name, c.arguments) for c in resp.tool_calls] == [("consult_cerebro", {"assunto": "noah"})]
    tools = backend.tokenizer.calls[0]["tools"]
    assert tools and tools[0]["function"]["name"] == "consult_cerebro"


def test_tool_call_de_ferramenta_nao_declarada_e_ignorada():
    texto = '<tool_call>{"name": "update_resume_field", "arguments": {"campo": "x"}}</tool_call>'
    content, calls = parse_tool_call_blocks(texto, {"consult_cerebro"})
    assert calls == [] and content == ""


def test_varios_blocos_e_json_quebrado():
    texto = ('<tool_call>{"name": "a", "arguments": {}}</tool_call>'
             '<tool_call>{nao é json}</tool_call>'
             '<tool_call>{"name": "b", "arguments": {"k": 1}}</tool_call>')
    _, calls = parse_tool_call_blocks(texto, {"a", "b"})
    assert [c.name for c in calls] == ["a", "b"]


def test_structured_chat_poe_o_schema_no_prompt_e_le_json_cercado():
    schema = {"type": "object", "properties": {"nome": {"type": "string"}}}
    backend = FakeBackend('```json\n{"nome": "Noah"}\n```')
    out = MLXProvider("repo/x", backend=backend).structured_chat([{"role": "user", "content": "x"}], schema)
    assert out == {"nome": "Noah"}
    ultima = backend.tokenizer.calls[0]["messages"][-1]
    assert ultima["role"] == "system" and json.dumps(schema, ensure_ascii=False) in ultima["content"]


def test_structured_chat_sem_json_levanta_value_error():
    backend = FakeBackend("não sei")
    with pytest.raises(ValueError, match="não é JSON válido"):
        MLXProvider("repo/x", backend=backend).structured_chat([], {"type": "object"})


def test_modelo_carregado_uma_vez_por_processo():
    backend = FakeBackend("a", "b")
    MLXProvider("repo/x", backend=backend).chat([], [])
    MLXProvider("repo/x", backend=backend).chat([], [])
    assert backend.loads == ["repo/x"]


def test_sem_mlx_lm_instalado_o_erro_explica_como_resolver(monkeypatch):
    monkeypatch.setitem(sys.modules, "mlx_lm", None)  # força ImportError mesmo se instalado
    with pytest.raises(RuntimeError, match="mlx-lm"):
        MLXProvider("repo/x").chat([], [])


def test_get_provider_mlx(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "mlx")
    monkeypatch.setattr(config, "MLX_MODEL", "mlx-community/Qwen2.5-7B-Instruct-4bit")
    monkeypatch.setattr(config, "MLX_MAX_TOKENS", 512)
    provider = get_provider()
    assert isinstance(provider, MLXProvider)
    assert provider._model_name == "mlx-community/Qwen2.5-7B-Instruct-4bit"
    assert provider._max_tokens == 512
    assert get_provider(model="/modelos/meu-qwen")._model_name == "/modelos/meu-qwen"


def test_get_provider_mlx_recusa_tag_do_ollama(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "mlx")
    with pytest.raises(ValueError, match="tag do Ollama"):
        get_provider(model="qwen2.5-coder:14b")
