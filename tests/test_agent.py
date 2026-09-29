from dejavu.agent import NO_HISTORY, IncidentAgent
from dejavu.schemas import AnalysisResult
from tests.conftest import VALID_ANALYSIS, make_llm, make_memory, recall_result, text_reply, tool_reply


async def run(agent, incident, use_memory=True):
    events = [e async for e in agent.run(incident, use_memory=use_memory)]
    final = AnalysisResult.model_validate(events[-1]["result"])
    return events, final


def build(settings, world, script, **memory_kwargs):
    memory, fake_memory = make_memory(settings, **memory_kwargs)
    llm, fake_llm = make_llm(settings, script)
    return IncidentAgent(settings=settings, world=world, memory=memory, llm=llm), fake_memory, fake_llm


async def test_memory_on_recalls_first_and_grounds_citations(settings, world, incident):
    agent, fake_memory, fake_llm = build(settings, world, [
        tool_reply("get_service_logs", {"service": "checkout-api"}),
        text_reply(VALID_ANALYSIS),
    ], recall_results=[recall_result("Restarting pods FAILED in INC-031", document_id="INC-031")])
    events, final = await run(agent, incident)

    assert events[1]["type"] == "tool_call" and events[1]["name"] == "recall_similar_incidents"
    assert fake_memory.calls[:2] == ["aget_bank_config", "arecall"]
    # INC-999 was never returned by memory, so it is stripped everywhere
    assert final.analysis.recommended_steps[0].evidence_incident_ids == ["INC-031"]
    assert [s.id for s in final.analysis.similar_incidents] == ["INC-031"]
    assert final.analysis.similar_incidents[0].date == "2026-07-17"
    assert final.meta.stripped_citations == ["INC-999"]
    assert final.meta.memory_mode == "on" and final.meta.history_found


async def test_empty_recall_says_no_similar_incidents(settings, world, incident):
    agent, _, _ = build(settings, world, [text_reply(VALID_ANALYSIS)], recall_results=[])
    _, final = await run(agent, incident)
    assert final.analysis.summary.startswith(NO_HISTORY)
    assert final.analysis.similar_incidents == []
    assert all(not s.evidence_incident_ids for s in final.analysis.recommended_steps + final.analysis.avoid_steps)


async def test_memory_off_offers_no_memory_tools_and_no_citations(settings, world, incident):
    agent, fake_memory, fake_llm = build(settings, world, [text_reply(VALID_ANALYSIS)],
                                         recall_results=[recall_result("x", document_id="INC-031")])
    _, final = await run(agent, incident, use_memory=False)
    offered = {t["function"]["name"] for t in fake_llm.calls[0]["tools"]}
    assert offered == {"get_service_logs", "get_recent_deploys"}
    assert fake_memory.calls == []
    assert final.analysis.similar_incidents == [] and final.meta.memory_mode == "off"


async def test_unreachable_memory_falls_back_to_no_memory_mode(settings, world, incident):
    agent, _, fake_llm = build(settings, world, [text_reply(VALID_ANALYSIS)], fail=ConnectionError("down"))
    events, final = await run(agent, incident)
    assert events[0]["type"] == "memory_unavailable"
    assert not final.meta.memory_available
    assert "recall_similar_incidents" not in {t["function"]["name"] for t in fake_llm.calls[0]["tools"]}


async def test_llm_outage_returns_degraded_memory_only_answer(settings, world, incident):
    agent, _, _ = build(settings, world, [ConnectionError("groq down")] * 6, recall_results=[
        recall_result("INC-031: capping the Hikari pool WORKED", document_id="INC-031"),
        recall_result("INC-031: restarting pods FAILED", document_id="INC-031"),
    ])
    events, final = await run(agent, incident)
    assert any(e["type"] == "degraded" for e in events)
    assert final.meta.degraded
    assert "WORKED" in final.analysis.recommended_steps[0].step
    assert "FAILED" in final.analysis.avoid_steps[0].step


async def test_tool_loop_is_bounded(settings, world, incident):
    looping = [tool_reply("get_recent_deploys", {}, call_id=f"c{i}") for i in range(settings.agent_max_steps)]
    agent, _, fake_llm = build(settings, world, looping + [text_reply(VALID_ANALYSIS)], recall_results=[])
    _, final = await run(agent, incident)
    assert final.meta.steps == settings.agent_max_steps
    assert fake_llm.calls[-1]["tool_choice"] == "none"  # forced to answer
