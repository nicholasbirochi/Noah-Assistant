"""LocalLLMProvider abstraction: OllamaProvider (default) and MLXProvider
(opt-in, NOAH_LLM_PROVIDER=mlx). Callers (llm_client.py, coding_agent.py,
scripts/import_resume.py, indexing/proposer.py) depend on this Protocol, not
on `ollama` or `mlx_lm` directly, so switching backends never touches them."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Protocol

from ollama import Client

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
