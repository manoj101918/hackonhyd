import asyncio

import pytest

from dejavu import bank
from dejavu.memory import MemoryUnavailable
from tests.conftest import make_memory, recall_result


async def test_recall_converts_hits_with_incident_ids_type_and_date(settings):
    store, _ = make_memory(settings, recall_results=[
        recall_result("Restarting pods did NOT fix INC-031", type_="experience", document_id="INC-031"),
        recall_result("Pool exhaustion recurs (INC-038, INC-044)", type_="observation"),
    ])
    hits = await store.recall("checkout 500s")
    assert [h.type for h in hits] == ["experience", "observation"]
    assert hits[0].incident_ids == ["INC-031"]
    assert hits[1].incident_ids == ["INC-038", "INC-044"]  # pulled from the text
    assert hits[0].date == "2026-07-17"
    assert store.status.available


async def test_failure_marks_memory_unavailable(settings):
    store, _ = make_memory(settings, fail=ConnectionError("connection refused"))
    with pytest.raises(MemoryUnavailable):
        await store.recall("anything")
    assert not store.status.available
    assert "connection refused" in store.status.reason


async def test_timeout_marks_memory_unavailable(settings):
    store, fake = make_memory(settings)

    async def slow(**kwargs):
        await asyncio.sleep(1)

    fake.arecall = slow
    store.settings = settings.model_copy(update={"recall_timeout_s": 0.01})
    with pytest.raises(MemoryUnavailable, match="timed out"):
        await store.recall("anything")
    assert not store.status.available


async def test_missing_api_key_for_cloud_is_reported(settings):
    from dejavu.memory import MemoryStore
    store = MemoryStore(settings.model_copy(update={"hindsight_api_key": ""}))
    assert not store.status.available
    assert "HINDSIGHT_API_KEY" in store.status.reason
    assert not await store.probe(max_age_s=0)


async def test_retain_appends_to_incident_document(settings):
    store, fake = make_memory(settings)
    await store.retain({"content": "x", "document_id": "INC-047", "metadata": {"kind": "step"}})
    assert fake.retained[0]["update_mode"] == "append"
    assert fake.retained[0]["document_id"] == "INC-047"


async def test_ensure_bank_is_idempotent(settings):
    store, fake = make_memory(settings)
    await store.ensure_bank()
    await store.ensure_bank()
    assert sorted(fake.directives) == sorted(d["name"] for d in bank.DIRECTIVES)
    assert fake.mental_models == [bank.PLAYBOOK_MODEL_ID]
