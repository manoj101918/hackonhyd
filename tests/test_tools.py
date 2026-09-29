import pytest

from dejavu.schemas import MemoryHit
from dejavu.tools import Toolbox, format_hits, record_step_outcome, without_incident
from tests.conftest import make_llm, make_memory, recall_result


def toolbox(settings, world, incident, memory=True, **memory_kwargs):
    store, fake = make_memory(settings, **memory_kwargs)
    llm, _ = make_llm(settings, [])
    return Toolbox(world=world, memory=store if memory else None, llm=llm, incident=incident), fake


async def test_service_logs_come_from_the_active_scenario(settings, world, incident):
    tb, _ = toolbox(settings, world, incident)
    out = await tb.call("get_service_logs", {"service": "inventory-db", "minutes": 30})
    assert "remaining connection slots are reserved" in out.content
    narrow = await tb.call("get_service_logs", {"service": "checkout-api", "minutes": 2})
    assert "HorizontalPodAutoscaler" not in narrow.content  # 15 minutes old, outside the window


async def test_unknown_service_returns_error_to_the_model(settings, world, incident):
    tb, _ = toolbox(settings, world, incident)
    out = await tb.call("get_service_logs", {"service": "mainframe"})
    assert out.content.startswith("Error: unknown service")


async def test_bad_arguments_do_not_crash(settings, world, incident):
    tb, _ = toolbox(settings, world, incident)
    out = await tb.call("get_service_logs", {"svc": "checkout-api"})
    assert out.content.startswith("Error: bad arguments")


async def test_recent_deploys_filter_by_window_and_service(settings, world, incident):
    tb, _ = toolbox(settings, world, incident)
    all_24h = (await tb.call("get_recent_deploys", {"hours": 24})).data
    assert {d["service"] for d in all_24h} == {"api-gateway", "notification-worker"}  # 26h-old deploy excluded
    only = (await tb.call("get_recent_deploys", {"service": "api-gateway", "hours": 48})).data
    assert [d["service"] for d in only] == ["api-gateway"]


async def test_memory_tools_hidden_when_memory_off(settings, world, incident):
    tb, _ = toolbox(settings, world, incident, memory=False)
    assert tb.names == {"get_service_logs", "get_recent_deploys"}
    out = await tb.call("recall_similar_incidents", {"symptoms": "x"})
    assert out.content.startswith("Error: unknown tool")


async def test_recall_excludes_the_incident_being_analysed(settings, world, incident):
    tb, _ = toolbox(settings, world, incident, recall_results=[
        recall_result("own alert", document_id=incident.id),
        recall_result("INC-031 pool exhaustion", document_id="INC-031"),
    ])
    out = await tb.call("recall_similar_incidents", {"symptoms": "500s"})
    assert [m.incident_ids for m in out.memories] == [["INC-031"]]
    assert tb.known_incident_ids == {"INC-031"}


def test_format_hits_empty_is_explicit():
    assert format_hits([]) == "No similar past incidents found in memory."


def test_without_incident_keeps_cross_references():
    hits = [MemoryHit(id="1", text="a", incident_ids=["INC-047"]),
            MemoryHit(id="2", text="b", incident_ids=["INC-031", "INC-047"])]
    assert [h.id for h in without_incident(hits, "INC-047")] == ["2"]


async def test_record_step_outcome_retains_step_experience_and_alert_once(settings, world, incident):
    store, fake = make_memory(settings)
    texts = await record_step_outcome(store, incident, "Cap Hikari pool at 10", "WORKED")
    assert len(texts) == 3  # alert (first time only) + step + Déjà Vu's own experience
    assert "WORKED" in texts[1] and "I (Déjà Vu" in texts[2]
    assert all(i["document_id"] == incident.id and i["update_mode"] == "append" for i in fake.retained)
    texts = await record_step_outcome(store, incident, "Restart pods", "FAILED", from_agent=False)
    assert len(texts) == 1 and "did NOT fix" in texts[0]


@pytest.mark.parametrize("scenario", ["s1-checkout-500s", "s2-payment-pool"])
def test_live_incident_ids_are_sequential(world, scenario):
    first = world.start_scenario(scenario)
    second = world.start_scenario(scenario)
    assert first.id == "INC-047" and second.id == "INC-048"
    world.reset_live()
    assert world.start_scenario(scenario).id == "INC-049"  # demo reset never reuses an ID memory may hold
    world.reset_live(reset_ids=True)
    assert world.start_scenario(scenario).id == "INC-047"
