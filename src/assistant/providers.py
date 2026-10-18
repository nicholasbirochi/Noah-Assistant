"""LocalLLMProvider abstraction: today only OllamaProvider exists, but
callers (llm_client.py, scripts/import_resume.py, indexing/proposer.py)
depend on this Protocol, not on `ollama` directly -- so a future MLXProvider
can be dropped in via get_provider() without touching any caller."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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


def get_provider(model: str | None = None, host: str | None = None) -> LocalLLMProvider:
    from config import LLM_PROVIDER, LOCAL_MODEL, OLLAMA_HOST, OLLAMA_KEEP_ALIVE

    if LLM_PROVIDER == "ollama":
        return OllamaProvider(
            model=model or LOCAL_MODEL, host=host or OLLAMA_HOST, keep_alive=OLLAMA_KEEP_ALIVE
        )
    raise ValueError(f"Provedor de LLM desconhecido: {LLM_PROVIDER!r}")
