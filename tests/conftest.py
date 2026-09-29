"""Shared fakes: a scripted OpenAI-compatible client and an in-memory Hindsight client."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from dejavu.config import Settings
from dejavu.llm import LLMRouter
from dejavu.memory import MemoryStore
from dejavu.world import World


# --------------------------------------------------------------------------- fake Groq

def tool_reply(name: str, arguments: dict | str, call_id: str = "call_1") -> SimpleNamespace:
    args = arguments if isinstance(arguments, str) else json.dumps(arguments)
    fn = SimpleNamespace(name=name, arguments=args)
    return _completion(SimpleNamespace(content="", tool_calls=[SimpleNamespace(id=call_id, function=fn)]))


def text_reply(content: str | dict) -> SimpleNamespace:
    text = content if isinstance(content, str) else json.dumps(content)
    return _completion(SimpleNamespace(content=text, tool_calls=None))


def _completion(message: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(total_tokens=10))


class FakeOpenAI:
    """Returns scripted replies in order; an Exception in the script is raised instead."""

    def __init__(self, script: list[Any]):
        self.script = list(script)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("FakeOpenAI script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# --------------------------------------------------------------------------- fake Hindsight

def recall_result(text: str, *, type_: str = "world", document_id: str | None = None, rid: str | None = None,
                  date: str = "2026-07-17T12:00:00Z") -> SimpleNamespace:
    return SimpleNamespace(id=rid or f"m-{abs(hash(text)) % 10**8}", text=text, type=type_, context="ctx",
                           occurred_start=date, mentioned_at=date, document_id=document_id,
                           metadata={"incident_id": document_id} if document_id else {}, scores=None)


class FakeHindsight:
    def __init__(self, recall_results: list | None = None, fail: Exception | None = None):
        self.recall_results = recall_results or []
        self.fail = fail
        self.retained: list[dict] = []
        self.directives: list[str] = []
        self.mental_models: list[str] = []
        self.calls: list[str] = []

    def _check(self, name: str):
        self.calls.append(name)
        if self.fail:
            raise self.fail

    async def aget_bank_config(self, bank_id):
        self._check("aget_bank_config")
        return {}

    async def arecall(self, **kwargs):
        self._check("arecall")
        return SimpleNamespace(results=self.recall_results)

    async def areflect(self, **kwargs):
        self._check("areflect")
        evidence = SimpleNamespace(memories=self.recall_results[:2])
        return SimpleNamespace(text="Reflected: matches INC-031.", based_on=evidence, structured_output=None)

    async def aretain(self, **kwargs):
        self._check("aretain")
        self.retained.append(kwargs)

    async def aretain_batch(self, **kwargs):
        self._check("aretain_batch")
        self.retained.extend(kwargs["items"])

    async def acreate_bank(self, bank_id, **kwargs):
        self._check("acreate_bank")

    async def aupdate_bank_config(self, bank_id, **kwargs):
        self._check("aupdate_bank_config")

    async def alist_directives(self, bank_id):
        return SimpleNamespace(items=[SimpleNamespace(name=n) for n in self.directives])

    async def acreate_directive(self, bank_id, name, **kwargs):
        self.directives.append(name)

    async def alist_mental_models(self, bank_id, **kwargs):
        return SimpleNamespace(items=[SimpleNamespace(id=i) for i in self.mental_models])

    async def acreate_mental_model(self, bank_id, id, **kwargs):
        self.mental_models.append(id)


# --------------------------------------------------------------------------- fixtures

@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, hindsight_api_key="test", groq_api_key="test", agent_max_steps=4)


@pytest.fixture
def world(tmp_path) -> World:
    return World(runtime_dir=tmp_path)


@pytest.fixture
def incident(world):
    return world.start_scenario("s1-checkout-500s")


def make_memory(settings: Settings, **kwargs) -> tuple[MemoryStore, FakeHindsight]:
    fake = FakeHindsight(**kwargs)
    return MemoryStore(settings, client=fake), fake


def make_llm(settings: Settings, script: list) -> tuple[LLMRouter, FakeOpenAI]:
    fake = FakeOpenAI(script)
    return LLMRouter(settings, client=fake), fake


VALID_ANALYSIS = {
    "summary": "Matches INC-031: inventory-db pool exhaustion.",
    "likely_root_cause": "Connection pool exhaustion on inventory-db after HPA scale-out.",
    "confidence": "high",
    "recommended_steps": [{"step": "Cap Hikari maximumPoolSize at 10", "rationale": "worked in INC-031",
                           "evidence_incident_ids": ["INC-031", "INC-999"]}],
    "avoid_steps": [{"step": "Restart checkout-api pods", "reason": "failed before", "evidence_incident_ids": ["INC-031"]}],
    "similar_incidents": [{"id": "INC-031", "similarity_reason": "same FATAL"}, {"id": "INC-999", "similarity_reason": "made up"}],
}
