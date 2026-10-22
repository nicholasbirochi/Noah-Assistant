import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

import config
from assistant.providers import OllamaProvider, get_provider
from assistant.tool_schema import ToolSpec
from assistant.providers import chat_with_cancel


@dataclass
class FakeFunction:
    name: str
    arguments: dict


@dataclass
class FakeToolCall:
    function: FakeFunction


@dataclass
class FakeMessage:
    content: str
    tool_calls: list = field(default_factory=list)


class FakeClient:
    def __init__(self, response_message: FakeMessage):
        self._response_message = response_message
        self.last_call_kwargs: dict | None = None

    def chat(self, **kwargs):
        self.last_call_kwargs = kwargs
        return SimpleNamespace(message=self._response_message)


def test_get_provider_default_is_ollama(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    provider = get_provider()
    assert isinstance(provider, OllamaProvider)


def test_get_provider_unknown_raises(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "something-else")
    with pytest.raises(ValueError):
        get_provider()


def test_ollama_provider_chat_no_tool_calls():
    fake_client = FakeClient(FakeMessage(content="olá", tool_calls=[]))
    provider = OllamaProvider(model="qwen2.5:14b", host="http://x", client=fake_client)

    response = provider.chat(messages=[{"role": "user", "content": "oi"}], tool_specs=[])

    assert response.content == "olá"
    assert response.tool_calls == []
    assert fake_client.last_call_kwargs["tools"] == []


def test_ollama_provider_chat_with_tool_calls():
    fake_client = FakeClient(
        FakeMessage(
            content="",
            tool_calls=[FakeToolCall(function=FakeFunction(name="read_resume", arguments={}))],
        )
    )
    spec = ToolSpec(name="read_resume", description="d", parameters={"type": "object", "properties": {}, "required": []})
    provider = OllamaProvider(model="qwen2.5:14b", host="http://x", client=fake_client)

    response = provider.chat(messages=[{"role": "user", "content": "leia meu currículo"}], tool_specs=[spec])

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "read_resume"
    assert response.tool_calls[0].arguments == {}
    assert fake_client.last_call_kwargs["tools"][0]["function"]["name"] == "read_resume"


def test_ollama_provider_structured_chat_parses_json():
    fake_client = FakeClient(FakeMessage(content=json.dumps({"a": 1})))
    provider = OllamaProvider(model="qwen2.5:14b", host="http://x", client=fake_client)

    result = provider.structured_chat(messages=[{"role": "user", "content": "x"}], json_schema={"type": "object"})

    assert result == {"a": 1}
    assert fake_client.last_call_kwargs["options"] == {"temperature": 0}


def test_ollama_provider_passes_keep_alive_on_chat():
    # Ollama's own default keep-alive (5 minutes) was found to be the real
    # cost behind slow replies in practice -- any gap between Noah
    # activations longer than that forces a full cold model reload. This
    # must be sent on every request, not assumed to be a server setting.
    fake_client = FakeClient(FakeMessage(content="olá", tool_calls=[]))
    provider = OllamaProvider(model="qwen2.5:7b", host="http://x", client=fake_client, keep_alive="30m")

    provider.chat(messages=[{"role": "user", "content": "oi"}], tool_specs=[])

    assert fake_client.last_call_kwargs["keep_alive"] == "30m"


def test_ollama_provider_passes_keep_alive_on_structured_chat():
    fake_client = FakeClient(FakeMessage(content="{}"))
    provider = OllamaProvider(model="qwen2.5:7b", host="http://x", client=fake_client, keep_alive="30m")

    provider.structured_chat(messages=[{"role": "user", "content": "x"}], json_schema={"type": "object"})

    assert fake_client.last_call_kwargs["keep_alive"] == "30m"


class FakeStreamingResponse:
    def __init__(self, events, block_before_headers=False):
        self.events = events
        self.block_before_headers = block_before_headers
        self.closed = threading.Event()
        self.entered = threading.Event()
        self.cancelled_before_headers = threading.Event()

    async def __aenter__(self):
        self.entered.set()
        if self.block_before_headers:
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                self.cancelled_before_headers.set()
                self.closed.set()
                raise
        return self

    async def __aexit__(self, *_):
        self.closed.set()

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for event in self.events:
            yield event


class FakeStreamingHTTP:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def stream(self, method, path, **kwargs):
        self.kwargs = (method, path, kwargs)
        return self.response


def _provider_with_stream(events):
    response = FakeStreamingResponse(events)
    client = SimpleNamespace(_client=FakeStreamingHTTP(response))
    return OllamaProvider(model="qwen2.5:7b", host="http://x", client=client), response


def test_ollama_cancellable_stream_joins_content_and_keeps_tool_calls():
    provider, _ = _provider_with_stream([
        json.dumps({"message": {"content": "Olá "}, "done": False}),
        json.dumps({"message": {"content": "mundo", "tool_calls": [
            {"function": {"name": "read_resume", "arguments": {"campo": "nome"}}}
        ]}, "done": False}),
        json.dumps({"message": {}, "done": True}),
    ])
    spec = ToolSpec(name="read_resume", description="d", parameters={"type": "object", "properties": {}})

    response = chat_with_cancel(provider, [{"role": "user", "content": "oi"}], [spec], lambda: False)

    assert response.content == "Olá mundo"
    assert [(call.name, call.arguments) for call in response.tool_calls] == [
        ("read_resume", {"campo": "nome"})
    ]
    method, path, kwargs = provider._client._client.kwargs
    assert (method, path) == ("POST", "/api/chat")
    assert kwargs["json"]["stream"] is True
    assert kwargs["json"]["tools"][0]["function"]["name"] == "read_resume"


def test_ollama_cancellable_stream_cancels_after_first_chunk():
    first_chunk = threading.Event()
    response = FakeStreamingResponse([])

    async def lines():
        yield json.dumps({"message": {"content": "começou"}, "done": False})
        first_chunk.set()
        while not response.closed.is_set():
            await asyncio.sleep(0.005)

    response.aiter_lines = lines
    client = SimpleNamespace(_client=FakeStreamingHTTP(response))
    provider = OllamaProvider(model="qwen2.5:7b", host="http://x", client=client)
    cancelled = threading.Event()
    spec = ToolSpec(name="read_resume", description="d", parameters={"type": "object", "properties": {}})
    cancelador = threading.Thread(target=lambda: (first_chunk.wait(1), time.sleep(0.03), cancelled.set()))
    cancelador.start()

    inicio = time.monotonic()
    with pytest.raises(RuntimeError, match="pedido cancelado"):
        chat_with_cancel(provider, [{"role": "user", "content": "pare"}], [spec], cancelled.is_set)
    duracao = time.monotonic() - inicio
    cancelador.join(timeout=1)

    assert response.closed.is_set()
    assert duracao < 1
    assert not cancelador.is_alive()


def test_ollama_cancellable_stream_cancels_before_response_headers():
    response = FakeStreamingResponse([], block_before_headers=True)
    client = SimpleNamespace(_client=FakeStreamingHTTP(response))
    provider = OllamaProvider(model="qwen2.5:7b", host="http://x", client=client)
    cancelled = threading.Event()
    cancelador = threading.Thread(target=lambda: (response.entered.wait(1), time.sleep(0.03), cancelled.set()))
    cancelador.start()

    inicio = time.monotonic()
    with pytest.raises(RuntimeError, match="pedido cancelado"):
        chat_with_cancel(provider, [{"role": "user", "content": "pare"}], [], cancelled.is_set)
    duracao = time.monotonic() - inicio
    cancelador.join(timeout=1)

    assert response.cancelled_before_headers.is_set()
    assert response.closed.is_set()
    assert duracao < 1
    assert not cancelador.is_alive()


def test_get_provider_passes_keep_alive_from_config(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(config, "OLLAMA_KEEP_ALIVE", "1h")

    provider = get_provider()

    assert provider._keep_alive == "1h"
