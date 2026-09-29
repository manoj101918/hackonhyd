import httpx
import openai
import pytest

from dejavu.llm import LLMUnavailable, extract_json
from dejavu.schemas import IncidentAnalysis
from tests.conftest import VALID_ANALYSIS, make_llm, text_reply, tool_reply

TOOLS = [{"type": "function", "function": {"name": "get_service_logs", "parameters": {"type": "object"}}}]
ALLOWED = {"get_service_logs"}


def groq_tool_use_failed() -> openai.BadRequestError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    body = {"error": {"code": "tool_use_failed", "message": "Failed to call a function",
                      "failed_generation": "<function=get_service_logs{bad"}}
    return openai.BadRequestError("tool_use_failed", response=httpx.Response(400, request=request), body=body)


def test_extract_json_tolerates_think_blocks_and_fences():
    assert extract_json('<think>hmm</think>\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here you go: {"a": 2} thanks') == {"a": 2}


async def test_malformed_tool_arguments_trigger_repair_retry(settings):
    llm, fake = make_llm(settings, [
        tool_reply("get_service_logs", "{not json"),
        tool_reply("get_service_logs", {"service": "checkout-api"}),
    ])
    result = await llm.step([{"role": "user", "content": "go"}], TOOLS, allowed_tools=ALLOWED)
    assert result.tool_calls[0].arguments == {"service": "checkout-api"}
    assert result.retries == 1
    assert "could not be used" in fake.calls[1]["messages"][-1]["content"]  # repair message was sent


async def test_unknown_tool_is_treated_as_malformed(settings):
    llm, _ = make_llm(settings, [tool_reply("rm_rf", {}), tool_reply("get_service_logs", {"service": "x"})])
    result = await llm.step([], TOOLS, allowed_tools=ALLOWED)
    assert result.tool_calls[0].name == "get_service_logs"


async def test_groq_tool_use_failed_falls_back_to_second_model(settings):
    llm, fake = make_llm(settings, [groq_tool_use_failed()] * 3 + [tool_reply("get_service_logs", {"service": "x"})])
    result = await llm.step([], TOOLS, allowed_tools=ALLOWED)
    assert result.model == settings.groq_fallback_model
    assert [c["model"] for c in fake.calls] == [settings.groq_model] * 3 + [settings.groq_fallback_model]


async def test_everything_failing_raises_llm_unavailable(settings):
    llm, _ = make_llm(settings, [groq_tool_use_failed()] * 6)
    with pytest.raises(LLMUnavailable):
        await llm.step([], TOOLS, allowed_tools=ALLOWED)


async def test_missing_key_is_unavailable_without_calling(settings):
    llm, fake = make_llm(settings.model_copy(update={"groq_api_key": ""}), [])
    with pytest.raises(LLMUnavailable, match="GROQ_API_KEY"):
        await llm.step([], TOOLS, allowed_tools=ALLOWED)
    assert fake.calls == []


async def test_structured_accepts_valid_first_reply_without_calling(settings):
    llm, fake = make_llm(settings, [])
    import json
    analysis, _, retries = await llm.structured([], IncidentAnalysis, first_reply=json.dumps(VALID_ANALYSIS))
    assert analysis.confidence == "high"
    assert retries == 0 and fake.calls == []


async def test_structured_repairs_invalid_json(settings):
    llm, fake = make_llm(settings, [text_reply("not json at all"), text_reply(VALID_ANALYSIS)])
    analysis, model, retries = await llm.structured([], IncidentAnalysis, first_reply='{"summary": "missing fields"}')
    assert analysis.recommended_steps[0].step.startswith("Cap Hikari")
    assert retries == 2  # invalid first reply + one invalid JSON-mode reply
    assert fake.calls[0]["response_format"] == {"type": "json_object"}
