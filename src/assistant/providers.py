"""LocalLLMProvider abstraction: OllamaProvider (default) and MLXProvider
(opt-in, NOAH_LLM_PROVIDER=mlx). Callers (llm_client.py, coding_agent.py,
scripts/import_resume.py, indexing/proposer.py) depend on this Protocol, not
on `ollama` or `mlx_lm` directly, so switching backends never touches them."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable, Protocol

import httpx
from ollama import Client, ResponseError

from assistant.tool_schema import ToolSpec, tool_spec_to_openai_dict


@dataclass
class ToolCallRequest:
    name: str
    arguments: dict[str, Any]


@dataclass
class ProviderResponse:
    content: str
    tool_calls: list[ToolCallRequest] = field(default_factory=list)


def recover_tool_call_from_content(content: str, known_tool_names: set[str]) -> ToolCallRequest | None:
    """Real, live-observed gap (2026-09-20, qwen2.5-coder via Ollama): the model
    correctly understood a tool-use task and picked the right tool, but this
    tag's chat template never populated Ollama's own structured
    `message.tool_calls` field -- it wrote the call out as plain JSON text in
    the ordinary content instead (confirmed live, reproducibly). Silently
    treating that JSON blob as the model's final answer is a real, confirmed
    failure mode, not a hypothetical one.

    Deliberately conservative: only recovers a call when the parsed object is
    unambiguously {"name", "arguments"}-shaped AND the name is in the set of
    names the CALLER declared eligible -- never guesses at a call for an unknown
    or hallucinated tool name. The eligible set is the caller's safety lever:
    the read-only coding agent (coding_agent.py) passes its whole tool surface,
    but the voice/text conversation (llm_client.py) passes ONLY its read-only
    tools, so a loose JSON blob the model merely wrote as prose can never fire a
    data-mutating action (update_resume_field, continue_job_application, ...).

    Lives here, not in coding_agent.py, so both tool loops share one
    implementation (it returns a ToolCallRequest, defined just above)."""
    stripped = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1).strip()
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    name, arguments = parsed.get("name"), parsed.get("arguments")
    if name not in known_tool_names or not isinstance(arguments, dict):
        return None
    return ToolCallRequest(name=name, arguments=arguments)


class LocalLLMProvider(Protocol):
    def chat(self, messages: list[dict], tool_specs: list[ToolSpec]) -> ProviderResponse: ...

    def structured_chat(self, messages: list[dict], json_schema: dict) -> dict: ...


def chat_with_cancel(provider: LocalLLMProvider, messages: list[dict], tool_specs: list[ToolSpec],
                     should_cancel: Callable[[], bool]) -> ProviderResponse:
    """Check cancellation around one provider call and use a cancellable stream
    when the provider supports it."""
    if should_cancel():
        raise RuntimeError("pedido cancelado")
    cancellable = getattr(provider, "chat_with_cancel", None)
    response = (cancellable(messages, tool_specs, should_cancel) if callable(cancellable)
                else provider.chat(messages, tool_specs))
    if should_cancel():
        raise RuntimeError("pedido cancelado")
    return response


class OllamaProvider:
    def __init__(self, model: str, host: str, client: Client | None = None, keep_alive: str | None = None) -> None:
        self._model = model
        self._client = client or Client(host=host)
        # Passed on every request rather than relying on server-side config
        # -- works regardless of how `ollama serve`/the brew service was
        # started. Ollama's own default (5 minutes) was found to be the
        # dominant cost behind slow replies in practice: a cold model load
        # measured ~30s vs ~1s warm for the same prompt, and any real gap
        # between Noah activations (a coffee break, a meeting) is enough
        # to fall out of that 5-minute window on every single session.
        self._keep_alive = keep_alive

    def chat(self, messages: list[dict], tool_specs: list[ToolSpec]) -> ProviderResponse:
        tools = [tool_spec_to_openai_dict(spec) for spec in tool_specs]
        response = self._client.chat(
            model=self._model, messages=messages, tools=tools, keep_alive=self._keep_alive
        )
        message = response.message
        calls = [
            ToolCallRequest(name=call.function.name, arguments=dict(call.function.arguments))
            for call in (message.tool_calls or [])
        ]
        return ProviderResponse(content=message.content or "", tool_calls=calls)

    def chat_with_cancel(self, messages: list[dict], tool_specs: list[ToolSpec],
                         should_cancel: Callable[[], bool]) -> ProviderResponse:
        """Stream one chat and cancel its HTTP request, including while Ollama
        is still preparing response headers. The ordinary `chat()` path stays
        unchanged for every other caller.
        """
        if should_cancel():
            raise RuntimeError("pedido cancelado")

        sync_http = getattr(self._client, "_client", None)
        if sync_http is None:
            return self._chat_with_cancel_test_double(messages, tool_specs, should_cancel)

        # Ollama's normal Client owns a sync httpx.Client. Clone only its
        # connection-facing settings into a dedicated async client so task
        # cancellation can abort a connect/read without closing the shared
        # sync pool used by other provider calls.
        if hasattr(sync_http, "base_url") and hasattr(sync_http, "headers"):
            async_http: Any = httpx.AsyncClient(
                base_url=sync_http.base_url,
                headers=sync_http.headers,
                timeout=sync_http.timeout,
                follow_redirects=sync_http.follow_redirects,
                auth=sync_http.auth,
                cookies=sync_http.cookies,
            )
            owns_http = True
        else:
            # Small injected test transports can expose an async stream
            # directly, without requiring an Ollama or network process.
            async_http = sync_http
            owns_http = False
        if not callable(getattr(async_http, "stream", None)):
            return self._chat_with_cancel_test_double(messages, tool_specs, should_cancel)

        body = {
            "model": self._model,
            "messages": messages,
            "tools": [tool_spec_to_openai_dict(spec) for spec in tool_specs],
            "stream": True,
        }
        if self._keep_alive is not None:
            body["keep_alive"] = self._keep_alive

        async def consumir() -> ProviderResponse:
            content: list[str] = []
            calls: list[ToolCallRequest] = []
            ended = False
            async with async_http.stream("POST", "/api/chat", json=body) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise ResponseError(exc.response.text, exc.response.status_code) from None

                async for line in response.aiter_lines():
                    if should_cancel():
                        raise asyncio.CancelledError()
                    if not line:
                        continue
                    event = json.loads(line)
                    if error := event.get("error"):
                        raise ResponseError(str(error))
                    message = event.get("message") or {}
                    if text := message.get("content"):
                        content.append(text)
                    for call in message.get("tool_calls") or []:
                        function = call.get("function") or {}
                        name = function.get("name")
                        if name:
                            calls.append(ToolCallRequest(
                                name=name,
                                arguments=dict(function.get("arguments") or {}),
                            ))
                    if event.get("done"):
                        ended = True
                        break
            if not ended:
                raise RuntimeError("Ollama encerrou o stream antes de concluir a resposta")
            return ProviderResponse(content="".join(content), tool_calls=calls)

        async def aguardar_ou_cancelar() -> ProviderResponse:
            request = asyncio.create_task(consumir())
            try:
                while not request.done():
                    done, _ = await asyncio.wait((request,), timeout=0.05)
                    if not done and should_cancel():
                        request.cancel()
                        break
                try:
                    response = await request
                except asyncio.CancelledError:
                    if should_cancel():
                        raise RuntimeError("pedido cancelado") from None
                    raise
                if should_cancel():
                    raise RuntimeError("pedido cancelado")
                return response
            finally:
                if not request.done():
                    request.cancel()
                await asyncio.gather(request, return_exceptions=True)
                if owns_http:
                    await async_http.aclose()

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(aguardar_ou_cancelar())
        raise RuntimeError("chat_with_cancel deve ser chamado fora de um event loop")

    def _chat_with_cancel_test_double(self, messages: list[dict], tool_specs: list[ToolSpec],
                                      should_cancel: Callable[[], bool]) -> ProviderResponse:
        """Compatibility path for legacy fake clients used by provider tests."""
        if should_cancel():
            raise RuntimeError("pedido cancelado")
        response = self.chat(messages, tool_specs)
        if should_cancel():
            raise RuntimeError("pedido cancelado")
        return response

    def structured_chat(self, messages: list[dict], json_schema: dict) -> dict:
        response = self._client.chat(
            model=self._model,
            messages=messages,
            format=json_schema,
            options={"temperature": 0},
            keep_alive=self._keep_alive,
        )
        return json.loads(response.message.content)


_TOOL_CALL_BLOCK = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


def parse_tool_call_blocks(text: str, known_tool_names: set[str]) -> tuple[str, list[ToolCallRequest]]:
    """Qwen-family chat templates (the models Noah uses) write tool calls as
    `<tool_call>{"name": ..., "arguments": {...}}</tool_call>` in the raw
    generated text -- Ollama parses that server-side into `message.tool_calls`;
    with MLX nobody does, so this does. Same conservative rule as
    recover_tool_call_from_content: only names the caller declared eligible,
    only {"name", "arguments"}-shaped objects. Returns the text outside the
    blocks (stripped) and the recognised calls."""
    calls = []
    for block in _TOOL_CALL_BLOCK.findall(text):
        call = recover_tool_call_from_content(block, known_tool_names)
        if call is not None:
            calls.append(call)
    return _TOOL_CALL_BLOCK.sub("", text).strip(), calls


def _mlx_backend() -> Any:
    """Imported lazily: mlx-lm is an optional, Apple-Silicon-only dependency
    (not in requirements.txt), so the default Ollama path never needs it."""
    try:
        import mlx_lm
        from mlx_lm.sample_utils import make_sampler
    except ImportError as exc:
        raise RuntimeError(
            "NOAH_LLM_PROVIDER=mlx precisa do pacote opcional mlx-lm "
            "(`pip install mlx-lm`, só Apple Silicon). Sem ele, use NOAH_LLM_PROVIDER=ollama."
        ) from exc

    greedy = make_sampler(temp=0.0)

    def generate(model: Any, tokenizer: Any, prompt: str, max_tokens: int) -> str:
        return mlx_lm.generate(model, tokenizer, prompt=prompt, max_tokens=max_tokens, sampler=greedy)

    return SimpleNamespace(load=mlx_lm.load, generate=generate)


# One loaded model per repo for the whole process: llm_client caches its
# provider, but coding_agent/import_resume/proposer each call get_provider(),
# and reloading weights (seconds, GBs of unified memory) per call would undo
# the latency MLX is here for.
_MLX_LOADED: dict[str, tuple[Any, Any]] = {}


class MLXProvider:
    """Runs the model in-process with Apple's MLX (`mlx-lm`) instead of over
    HTTP to Ollama -- the F4 bet is lower latency on Apple Silicon, to be
    confirmed with scripts/benchmark_llm.py-style measurements before it ever
    becomes the default. Opt-in only (NOAH_LLM_PROVIDER=mlx); weights come
    from a Hugging Face repo or local path (NOAH_MLX_MODEL), and `mlx_lm.load`
    downloads a repo on first use -- that download is the user's choice, the
    default provider never triggers it.

    Differences from OllamaProvider, kept explicit:
    - tool calls are parsed from the model's `<tool_call>` blocks here
      (parse_tool_call_blocks), not by a server;
    - structured_chat cannot constrain decoding to the schema the way
      Ollama's `format=` does: the schema goes into the prompt and the reply
      is parsed as JSON, raising ValueError if it is not valid JSON;
    - decoding is greedy (temperature 0) in both methods."""

    def __init__(self, model: str, max_tokens: int = 1024, backend: Any | None = None) -> None:
        self._model_name = model
        self._max_tokens = max_tokens
        self._backend = backend

    def _loaded(self) -> tuple[Any, Any, Any]:
        backend = self._backend or _mlx_backend()
        if self._model_name not in _MLX_LOADED:
            _MLX_LOADED[self._model_name] = backend.load(self._model_name)
        model, tokenizer = _MLX_LOADED[self._model_name]
        return backend, model, tokenizer

    def _generate(self, messages: list[dict], tools: list[dict] | None) -> str:
        backend, model, tokenizer = self._loaded()
        prompt = tokenizer.apply_chat_template(
            messages, tools=tools or None, add_generation_prompt=True, tokenize=False
        )
        return backend.generate(model, tokenizer, prompt, self._max_tokens)

    def chat(self, messages: list[dict], tool_specs: list[ToolSpec]) -> ProviderResponse:
        tools = [tool_spec_to_openai_dict(spec) for spec in tool_specs]
        text = self._generate(messages, tools)
        content, calls = parse_tool_call_blocks(text, {spec.name for spec in tool_specs})
        return ProviderResponse(content=content, tool_calls=calls)

    def structured_chat(self, messages: list[dict], json_schema: dict) -> dict:
        instruction = {
            "role": "system",
            "content": "Responda só com um objeto JSON válido, sem texto antes ou depois, "
            "seguindo este JSON Schema:\n" + json.dumps(json_schema, ensure_ascii=False),
        }
        text = self._generate([*messages, instruction], None).strip()
        fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fenced:
            text = fenced.group(1)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"MLXProvider: a resposta não é JSON válido: {text[:200]!r}") from exc


def get_provider(model: str | None = None, host: str | None = None) -> LocalLLMProvider:
    from config import (
        LLM_PROVIDER,
        LOCAL_MODEL,
        MLX_MAX_TOKENS,
        MLX_MODEL,
        OLLAMA_HOST,
        OLLAMA_KEEP_ALIVE,
    )

    if LLM_PROVIDER == "ollama":
        return OllamaProvider(
            model=model or LOCAL_MODEL, host=host or OLLAMA_HOST, keep_alive=OLLAMA_KEEP_ALIVE
        )
    if LLM_PROVIDER == "mlx":
        # An explicit `model` from a caller is an Ollama tag ("qwen2.5-coder:14b")
        # unless it looks like an HF repo/local path; a tag means nothing to MLX.
        if model and "/" not in model:
            raise ValueError(
                f"Com NOAH_LLM_PROVIDER=mlx o modelo precisa ser um repositório MLX ou caminho "
                f"(ex.: mlx-community/Qwen2.5-7B-Instruct-4bit), não a tag do Ollama {model!r}."
            )
        return MLXProvider(model=model or MLX_MODEL, max_tokens=MLX_MAX_TOKENS)
    raise ValueError(f"Provedor de LLM desconhecido: {LLM_PROVIDER!r}")
