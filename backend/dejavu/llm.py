"""Groq (OpenAI-compatible) client with the robustness the agent needs.

Failure ladder, per call:
  1. primary model (openai/gpt-oss-120b)
     - malformed tool call / invalid JSON  -> retry with an error-repair message (max 2 retries)
     - timeout / 5xx / rate limit           -> retry with backoff (same budget)
  2. fallback model (qwen/qwen3.8-27b — qwen3-32b is no longer served by Groq), same ladder
  3. raise `LLMUnavailable` -> the agent builds a degraded, memory-only answer
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from .config import Settings
from .log import get_logger, kv

log = get_logger("llm")
M = TypeVar("M", bound=BaseModel)

MAX_REPAIR_RETRIES = 2
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

# Per-model request extras (Groq specific knobs).
MODEL_EXTRAS: dict[str, dict[str, Any]] = {
    "openai/gpt-oss-120b": {"reasoning_effort": "medium"},
    "openai/gpt-oss-20b": {"reasoning_effort": "medium"},

}


class LLMUnavailable(RuntimeError):
    """Every model and retry failed."""


class LLMOutputError(ValueError):
    """The model answered, but not in a usable shape (malformed tool call / invalid JSON)."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class StepResult:
    """One assistant turn: either tool calls or final text content."""

    model: str
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    retries: int = 0

    def as_message(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in self.tool_calls
            ]
        return msg


def extract_json(text: str) -> Any:
    """Parse a JSON object from model text, tolerating <think> blocks and ``` fences."""
    text = THINK_RE.sub("", text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def _is_transient(exc: Exception) -> bool:
    return isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError,
                            openai.InternalServerError))


_RETRY_IN_RE = re.compile(r"try again in ([\d.]+)(ms|s)")


def _backoff_seconds(exc: Exception, attempt: int) -> float:
    """Rate limits: wait as long as Groq asks (capped); other transient errors: short linear backoff."""
    if isinstance(exc, openai.RateLimitError):
        header = exc.response.headers.get("retry-after") if exc.response is not None else None
        match = _RETRY_IN_RE.search(str(exc))
        if match:
            wait = float(match.group(1)) / (1000 if match.group(2) == "ms" else 1)
        else:
            wait = float(header) if header and header.replace(".", "").isdigit() else 2.0 * (attempt + 1)
        return min(wait + 0.3, 20.0)
    return 0.5 * (attempt + 1)


def _is_malformed_generation(exc: Exception) -> bool:
    """Groq returns 400 with code tool_use_failed / json_validate_failed for bad generations."""
    if not isinstance(exc, openai.BadRequestError):
        return False
    body = exc.body if isinstance(exc.body, dict) else {}
    code = (body.get("error") or body).get("code", "") if isinstance(body, dict) else ""
    return code in {"tool_use_failed", "json_validate_failed", "output_parse_failed"} or "failed_generation" in str(exc)


def _repair_message(problem: str) -> dict[str, str]:
    return {"role": "user", "content": (
        f"Your previous reply could not be used: {problem[:600]}\n"
        "Try again. Either call one of the provided tools with valid JSON arguments, "
        "or reply with ONLY the final JSON object described in the instructions."
    )}


class LLMRouter:
    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None):
        self.settings = settings
        self.models = [settings.groq_model, settings.groq_fallback_model]
        self.client = client or AsyncOpenAI(
            api_key=settings.groq_api_key or "missing", base_url=settings.groq_base_url,
            timeout=settings.llm_timeout_s, max_retries=0,  # retries are handled here, visibly
        )

    @property
    def configured(self) -> bool:
        return bool(self.settings.groq_api_key)

    async def _create(self, model: str, messages: list[dict], **kwargs: Any):
        started = time.perf_counter()
        resp = await self.client.chat.completions.create(
            model=model, messages=messages, temperature=0.2, extra_body=MODEL_EXTRAS.get(model) or None, **kwargs,
        )
        usage = getattr(resp, "usage", None)
        log.info("llm.call", extra=kv(model=model, ms=int((time.perf_counter() - started) * 1000),
                                      tokens=getattr(usage, "total_tokens", "?")))
        return resp

    async def _ladder(self, run_once, *, what: str, start_model: int = 0):
        """Run `run_once(model, repair_messages)` across the retry/fallback ladder."""
        if not self.configured:
            raise LLMUnavailable("GROQ_API_KEY is not set")
        last_error = "unknown error"
        retries = 0
        for model in self.models[start_model:]:
            has_fallback = model != self.models[-1]
            repair: list[dict] = []
            for attempt in range(1 + MAX_REPAIR_RETRIES):
                try:
                    return await run_once(model, repair), model, retries
                except (LLMOutputError, openai.BadRequestError) as exc:
                    if isinstance(exc, openai.BadRequestError) and not _is_malformed_generation(exc):
                        last_error = f"{model}: {exc}"
                        break  # a genuine bad request will not fix itself; go to fallback
                    last_error = str(exc)
                    repair = [_repair_message(last_error)]
                except Exception as exc:  # transport errors, auth errors, timeouts
                    last_error = f"{model}: {type(exc).__name__}: {exc}"
                    if not _is_transient(exc):
                        break
                    wait = _backoff_seconds(exc, attempt)
                    if isinstance(exc, openai.RateLimitError) and wait > 4 and has_fallback:
                        break  # rate limits are per model: switching beats waiting
                    await asyncio.sleep(wait)
                retries += 1
                log.warning("llm.retry", extra=kv(what=what, model=model, attempt=attempt + 1, error=last_error[:200]))
            log.warning("llm.fallback", extra=kv(what=what, from_model=model, error=last_error[:200]))
        raise LLMUnavailable(last_error)

    async def step(self, messages: list[dict], tools: list[dict], *, allowed_tools: set[str],
                   force_answer: bool = False, start_model: int = 0) -> StepResult:
        """One agent step: the model either calls tools or gives its final answer."""

        async def run_once(model: str, repair: list[dict]) -> StepResult:
            kwargs: dict[str, Any] = {}
            if tools:
                kwargs = {"tools": tools, "tool_choice": "none" if force_answer else "auto"}
            resp = await self._create(model, messages + repair, **kwargs)
            msg = resp.choices[0].message
            calls: list[ToolCall] = []
            for tc in msg.tool_calls or []:
                if tc.function.name not in allowed_tools:
                    raise LLMOutputError(f"unknown tool {tc.function.name!r}; available: {sorted(allowed_tools)}")
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    raise LLMOutputError(f"tool {tc.function.name} arguments are not valid JSON: {exc}") from exc
                if not isinstance(args, dict):
                    raise LLMOutputError(f"tool {tc.function.name} arguments must be a JSON object")
                calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
            content = THINK_RE.sub("", msg.content or "").strip()
            if not calls and not content:
                raise LLMOutputError("empty reply (no tool call and no content)")
            return StepResult(model=model, content=content, tool_calls=calls)

        result, model, retries = await self._ladder(run_once, what="step", start_model=start_model)
        result.retries = retries
        return result

    async def structured(self, messages: list[dict], schema: type[M], *, first_reply: str | None = None,
                         start_model: int = 0) -> tuple[M, str, int]:
        """Get a reply validated against `schema`, repairing invalid JSON up to MAX_REPAIR_RETRIES times.

        If `first_reply` is given (e.g. the agent's final message), it is validated first and only
        re-requested from the model when it does not parse.
        """
        if first_reply:
            try:
                return schema.model_validate(extract_json(first_reply)), self.models[start_model], 0
            except (json.JSONDecodeError, ValidationError, TypeError) as exc:
                log.warning("llm.final_invalid", extra=kv(error=str(exc)[:200]))
                messages = messages + [{"role": "assistant", "content": first_reply[:4000]},
                                       _repair_message(f"invalid final JSON: {exc}")]

        async def run_once(model: str, repair: list[dict]) -> M:
            resp = await self._create(model, messages + repair, response_format={"type": "json_object"})
            text = resp.choices[0].message.content or ""
            try:
                return schema.model_validate(extract_json(text))
            except (json.JSONDecodeError, ValidationError, TypeError) as exc:
                raise LLMOutputError(f"invalid JSON for {schema.__name__}: {exc}") from exc

        value, model, retries = await self._ladder(run_once, what=f"structured:{schema.__name__}",
                                                   start_model=start_model)
        return value, model, retries + (1 if first_reply else 0)
