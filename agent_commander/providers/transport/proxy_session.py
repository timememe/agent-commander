"""Provider that streams responses from CLIProxyAPI-compatible HTTP endpoints.

Supports OpenAI-compatible tool calling: defines local tools (file ops, shell),
sends them in requests, executes tool calls locally, loops until done.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable

from loguru import logger

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_commander.session.extension_store import ExtensionStore


@dataclass
class ProxySession:
    """Lightweight session object used by ProxyAPIProvider."""

    agent_key: str
    cwd: str | None = None

    @property
    def agent(self) -> "_ProxyAgent":
        return _ProxyAgent(self.agent_key)


@dataclass(frozen=True)
class _ProxyAgent:
    key: str


@dataclass
class _ToolCallAccumulator:
    """Accumulates streamed tool_call deltas into a complete tool call."""

    id: str = ""
    name: str = ""
    arguments: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


@dataclass
class _RequestResult:
    """Result of a single HTTP request (after SSE stream is fully consumed)."""

    text_parts: list[str] = field(default_factory=list)
    tool_calls: list[_ToolCallAccumulator] = field(default_factory=list)
    finish_reason: str = "stop"


_MAX_TOOL_ROUNDS = 25
_EventQueue = "queue.Queue[tuple[str, str | Exception | None]]"


class ProxyAPIProvider:
    """Stream chat completions from a CLIProxyAPI/OpenAI-compatible endpoint."""

    mode = "proxy_api"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_claude: str,
        model_gemini: str,
        model_codex: str,
        request_timeout_s: float = 300.0,
        endpoint: str = "/v1/chat/completions",
        extension_store: "ExtensionStore | None" = None,
    ) -> None:
        self.base_url = (base_url or "http://127.0.0.1:8317").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.request_timeout_s = float(max(10.0, request_timeout_s))
        self.endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        self._models = {
            "claude": model_claude.strip(),
            "gemini": model_gemini.strip(),
            "codex": model_codex.strip(),
        }
        self._extension_store = extension_store

    # ── Public async interface ────────────────────────────────────────

    async def send_and_receive(
        self,
        message: str,
        session: ProxySession,
        on_raw: Callable[[str], Awaitable[None]] | None = None,
        on_tool_event: Callable[[str], Awaitable[None]] | None = None,
    ) -> AsyncIterator[str]:
        event_q: _EventQueue = queue.Queue()
        done = threading.Event()

        def worker() -> None:
            try:
                self._agent_loop(message=message, session=session, event_q=event_q)
            except Exception as exc:
                event_q.put(("error", exc))
            finally:
                done.set()
                event_q.put(("done", None))

        threading.Thread(target=worker, daemon=True, name="agent-commander-proxyapi-stream").start()

        while True:
            kind, payload = await asyncio.to_thread(event_q.get)

            if kind == "raw":
                if on_raw is not None and isinstance(payload, str):
                    await on_raw(payload)
                continue

            if kind == "chunk":
                if isinstance(payload, str) and payload:
                    if on_raw is not None:
                        await on_raw(payload)
                    yield payload
                continue

            if kind == "tool_chunk":
                if on_tool_event is not None and isinstance(payload, str) and payload:
                    await on_tool_event(payload)
                continue

            if kind == "error":
                if isinstance(payload, Exception):
                    raise payload
                raise RuntimeError(str(payload))

            if kind == "done":
                break

            if done.is_set():
                break

    async def send_and_collect(self, message: str, session: ProxySession) -> str:
        parts: list[str] = []
        async for chunk in self.send_and_receive(message=message, session=session):
            parts.append(chunk)
        return "".join(parts).strip()

    # ── Agent loop (runs in worker thread) ────────────────────────────

    def _agent_loop(
        self,
        message: str,
        session: ProxySession,
        event_q: _EventQueue,
    ) -> None:
        """Multi-round agent loop: send request, execute tool calls, repeat."""
        from agent_commander.providers.tools.definitions import TOOL_DEFINITIONS, execute_tool

        model = self._select_model(session)
        messages: list[dict] = [{"role": "user", "content": message}]

        for round_num in range(_MAX_TOOL_ROUNDS):
            result = self._single_request(
                model=model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                event_q=event_q,
            )

            if not result.tool_calls or result.finish_reason != "tool_calls":
                break

            # Build assistant message with tool_calls
            assistant_msg: dict = {"role": "assistant", "tool_calls": [tc.to_dict() for tc in result.tool_calls]}
            text = "".join(result.text_parts)
            if text:
                assistant_msg["content"] = text
            messages.append(assistant_msg)

            # Execute each tool call — emit as tool_chunk (separate bubble)
            for tc in result.tool_calls:
                short_args = tc.arguments[:120] + "..." if len(tc.arguments) > 120 else tc.arguments
                event_q.put(("tool_chunk", f"`{tc.name}({short_args})`\n"))

                tool_result = execute_tool(
                    name=tc.name,
                    arguments_json=tc.arguments,
                    cwd=session.cwd,
                    extension_store=self._extension_store,
                )

                preview = tool_result[:500]
                if len(tool_result) > 500:
                    preview += "..."
                event_q.put(("tool_chunk", f"```\n{preview}\n```\n\n"))

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })

            logger.debug(f"Tool round {round_num + 1}: {len(result.tool_calls)} tool(s) executed, continuing")

    # ── Single HTTP request ───────────────────────────────────────────

    def _single_request(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        event_q: _EventQueue,
    ) -> _RequestResult:
        """Send one HTTP request. Streams text chunks to event_q. Returns result with tool calls."""
        url = f"{self.base_url}{self.endpoint}"
        import pathlib; pathlib.Path.home().joinpath("_ac_debug.log").open("a").write(f"_single_request: model={model!r}\n")

        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": 0,
        }
        if tools:
            payload["tools"] = tools

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout_s) as resp:
                content_type = (resp.headers.get("Content-Type") or "").lower()
                if "text/event-stream" in content_type:
                    return self._consume_sse_stream_with_tools(resp, event_q)
                raw = resp.read().decode("utf-8", errors="ignore")
                return self._consume_json_fallback_with_tools(raw, event_q)
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Proxy API HTTP {exc.code}: {body_text or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Proxy API connection error: {exc.reason}") from exc

    # ── SSE stream consumption with tool call support ─────────────────

    def _consume_sse_stream_with_tools(
        self,
        resp: object,
        event_q: _EventQueue,
    ) -> _RequestResult:
        result = _RequestResult()
        tool_accumulators: list[_ToolCallAccumulator] = []
        data_lines: list[str] = []

        for raw_line in resp:  # type: ignore[assignment]
            line = raw_line.decode("utf-8", errors="ignore").rstrip("\r\n")

            if not line:
                if data_lines:
                    payload = "\n".join(data_lines)
                    data_lines.clear()
                    if payload == "[DONE]":
                        break
                    err = self._extract_error_from_json_line(payload)
                    if err:
                        raise RuntimeError(f"Proxy API stream error: {err}")
                    self._process_sse_payload(payload, event_q, result, tool_accumulators)
                continue

            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        result.tool_calls = [tc for tc in tool_accumulators if tc.name]
        return result

    def _process_sse_payload(
        self,
        payload: str,
        event_q: _EventQueue,
        result: _RequestResult,
        tool_accumulators: list[_ToolCallAccumulator],
    ) -> None:
        """Process one SSE data payload: extract text, tool_call deltas, finish_reason."""
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            # Try non-choices formats (Anthropic, Responses API)
            text = self._extract_text_from_json_line(payload)
            if text:
                event_q.put(("chunk", text))
                result.text_parts.append(text)
            return

        choice = choices[0] if isinstance(choices[0], dict) else {}

        # Extract finish_reason
        fr = choice.get("finish_reason")
        if isinstance(fr, str) and fr:
            result.finish_reason = fr

        # Extract from delta (streaming)
        delta = choice.get("delta")
        if isinstance(delta, dict):
            # Text content
            content = delta.get("content")
            text = self._normalize_content(content)
            if text:
                event_q.put(("chunk", text))
                result.text_parts.append(text)

            # Tool call deltas
            tc_deltas = delta.get("tool_calls")
            if isinstance(tc_deltas, list):
                for tc_delta in tc_deltas:
                    if not isinstance(tc_delta, dict):
                        continue
                    index = tc_delta.get("index", 0)
                    while len(tool_accumulators) <= index:
                        tool_accumulators.append(_ToolCallAccumulator())
                    acc = tool_accumulators[index]
                    if "id" in tc_delta:
                        acc.id = tc_delta["id"]
                    func = tc_delta.get("function", {})
                    if isinstance(func, dict):
                        if "name" in func:
                            acc.name = func["name"]
                        if "arguments" in func:
                            acc.arguments += func["arguments"]
            return

        # Extract from message (non-streaming)
        message = choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            text = self._normalize_content(content)
            if text:
                event_q.put(("chunk", text))
                result.text_parts.append(text)

            tc_list = message.get("tool_calls")
            if isinstance(tc_list, list):
                for tc in tc_list:
                    if not isinstance(tc, dict):
                        continue
                    func = tc.get("function", {})
                    if not isinstance(func, dict):
                        continue
                    tool_accumulators.append(_ToolCallAccumulator(
                        id=tc.get("id", ""),
                        name=func.get("name", ""),
                        arguments=func.get("arguments", ""),
                    ))

    def _consume_json_fallback_with_tools(
        self,
        raw: str,
        event_q: _EventQueue,
    ) -> _RequestResult:
        result = _RequestResult()
        tool_accumulators: list[_ToolCallAccumulator] = []
        if raw:
            err = self._extract_error_from_json_line(raw)
            if err:
                raise RuntimeError(f"Proxy API error: {err}")
            self._process_sse_payload(raw, event_q, result, tool_accumulators)
        result.tool_calls = [tc for tc in tool_accumulators if tc.name]
        return result

    # ── Text extraction helpers (unchanged) ───────────────────────────

    def _extract_text_from_json_line(self, payload: str) -> str:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return ""
        if not isinstance(data, dict):
            return ""

        # OpenAI Responses stream shape
        event_type = data.get("type")
        if isinstance(event_type, str):
            if event_type in {"response.output_text.delta", "output_text.delta"}:
                delta = data.get("delta")
                if isinstance(delta, str):
                    return delta
            if event_type in {"content_block_delta", "message_delta"}:
                delta_obj = data.get("delta")
                if isinstance(delta_obj, dict):
                    text = delta_obj.get("text")
                    if isinstance(text, str):
                        return text

        # OpenAI chat.completions stream shape
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0] if isinstance(choices[0], dict) else {}
            delta = choice.get("delta")
            if isinstance(delta, dict):
                content = delta.get("content")
                text = self._normalize_content(content)
                if text:
                    return text
            message = choice.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                text = self._normalize_content(content)
                if text:
                    return text
            text = choice.get("text")
            if isinstance(text, str):
                return text

        # Responses-style fallback
        output_text = data.get("output_text")
        if isinstance(output_text, str):
            return output_text
        if isinstance(output_text, list):
            return "".join(item for item in output_text if isinstance(item, str))

        # Anthropic-style message payload
        content = data.get("content")
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
            if text_parts:
                return "".join(text_parts)

        # Responses non-stream payload shape
        output = data.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                item_content = item.get("content")
                if not isinstance(item_content, list):
                    continue
                for block in item_content:
                    if not isinstance(block, dict):
                        continue
                    text = block.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            if parts:
                return "".join(parts)

        return ""

    def _extract_error_from_json_line(self, payload: str) -> str:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return ""
        if not isinstance(data, dict):
            return ""
        err = data.get("error")
        if isinstance(err, dict):
            message = err.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
            err_type = err.get("type")
            if isinstance(err_type, str) and err_type.strip():
                return err_type.strip()
            return json.dumps(err, ensure_ascii=False)
        if isinstance(err, str) and err.strip():
            return err.strip()
        return ""

    def _normalize_content(self, content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)
        return ""

    def _select_model(self, session: ProxySession) -> str:
        agent_key = (session.agent.key or "codex").strip().lower()
        model = self._models.get(agent_key) or self._models.get("codex") or ""
        import pathlib; pathlib.Path.home().joinpath("_ac_debug.log").open("a").write(f"_select_model: agent_key={agent_key!r}, model={model!r}, all_models={self._models}\n")
        if not model:
            raise RuntimeError(
                f"No proxy_api model configured for agent '{agent_key}'. "
                "Set config.proxyApi.model<Agent>."
            )
        return model
