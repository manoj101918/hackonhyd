"""The Déjà Vu incident agent: a bounded tool-calling loop that streams its progress as events.

Flow for one analysis:
  1. (memory ON) recall similar incidents up front — memory is always consulted, not left to chance
  2. tool loop (max `agent_max_steps`): logs, deploys, more recall, reflect, deploy-risk checks
  3. final JSON validated against `IncidentAnalysis` (repair -> fallback model -> degraded answer)
  4. grounding: evidence incident IDs the memory never returned are stripped, so the UI only ever
     shows citations that are backed by a real memory
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from . import prompts
from .config import Settings
from .llm import LLMRouter, LLMUnavailable
from .log import get_logger, kv
from .memory import MemoryStore
from .schemas import (AnalysisMeta, AnalysisResult, AvoidStep, IncidentAnalysis, MemoryHit, RecommendedStep,
                      SimilarIncident)
from .tools import Toolbox
from .world import LiveIncident, World

log = get_logger("agent")

NO_HISTORY = "No similar past incidents found."
_WORKED_RE = re.compile(r"\b(WORKED|fixed|resolved)\b", re.IGNORECASE)
_FAILED_RE = re.compile(r"\b(FAILED|did not fix|did NOT fix|made it worse)\b", re.IGNORECASE)

Event = dict[str, Any]


def ground(analysis: IncidentAnalysis, memories: list[MemoryHit], *, history_found: bool) -> list[str]:
    """Remove citations not backed by a recalled memory. Returns the stripped IDs."""
    known = {i for h in memories for i in h.incident_ids} if history_found else set()
    stripped: list[str] = []

    def keep(ids: list[str]) -> list[str]:
        stripped.extend(i for i in ids if i not in known)
        return [i for i in ids if i in known]

    for step in [*analysis.recommended_steps, *analysis.avoid_steps]:
        step.evidence_incident_ids = keep(step.evidence_incident_ids)
    analysis.similar_incidents = [s for s in analysis.similar_incidents if keep([s.id])]

    dates = {}
    for h in memories:
        for i in h.incident_ids:
            dates.setdefault(i, h.date)
    for s in analysis.similar_incidents:
        s.date = s.date or dates.get(s.id)
    return sorted(set(stripped))


def degraded_analysis(incident: LiveIncident, memories: list[MemoryHit]) -> IncidentAnalysis:
    """Answer built from memory alone, used when every LLM call failed."""
    similar: dict[str, MemoryHit] = {}  # incident -> first (most relevant) memory, in recall order
    for h in memories:
        for i in h.incident_ids:
            similar.setdefault(i, h)
    top = set(list(similar)[:3])
    relevant = [h for h in memories if top & set(h.incident_ids)]
    worked = [h for h in relevant if _WORKED_RE.search(h.text) and not _FAILED_RE.search(h.text)][:3]
    failed = [h for h in relevant if _FAILED_RE.search(h.text)][:3]
    if not memories:
        return IncidentAnalysis(
            summary=f"{NO_HISTORY} The language model is unavailable, so this is a generic checklist.",
            likely_root_cause="Unknown — language model unavailable.",
            confidence="low",
            recommended_steps=[RecommendedStep(step=f"Check recent deploys and config changes to {incident.service}"),
                               RecommendedStep(step=f"Inspect {incident.service} error logs and dependency health")],
        )
    return IncidentAnalysis(
        summary="The language model is unavailable; showing what memory says worked and failed in similar incidents.",
        likely_root_cause="See the matching past incidents below.",
        confidence="low",
        recommended_steps=[RecommendedStep(step=h.text[:300], rationale="worked before", evidence_incident_ids=h.incident_ids)
                           for h in worked] or [RecommendedStep(step="Review the similar incidents below")],
        avoid_steps=[AvoidStep(step=h.text[:300], reason="failed before", evidence_incident_ids=h.incident_ids)
                     for h in failed],
        similar_incidents=[SimilarIncident(id=i, date=h.date, similarity_reason=h.text[:160])
                           for i, h in list(similar.items())[:5]],
    )


class IncidentAgent:
    def __init__(self, *, settings: Settings, world: World, memory: MemoryStore, llm: LLMRouter):
        self.settings = settings
        self.world = world
        self.memory = memory
        self.llm = llm

    async def run(self, incident: LiveIncident, *, use_memory: bool) -> AsyncIterator[Event]:
        started = time.perf_counter()

        def ev(type_: str, **fields: Any) -> Event:
            return {"type": type_, "t_ms": int((time.perf_counter() - started) * 1000), **fields}

        memory_available = bool(use_memory and await self.memory.probe(max_age_s=10))
        if use_memory and not memory_available:
            yield ev("memory_unavailable", reason=self.memory.status.reason)
        tools = Toolbox(world=self.world, memory=self.memory if memory_available else None,
                        llm=self.llm, incident=incident)
        system = prompts.SYSTEM_WITH_MEMORY if tools.memory else prompts.SYSTEM_WITHOUT_MEMORY
        brief = prompts.incident_brief(incident, self.world.services)
        messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": brief}]
        transcript: list[str] = []
        log.info("agent.start", extra=kv(incident=incident.id, memory="on" if tools.memory else "off"))
        yield ev("status", message=f"Investigating {incident.id} with memory {'ON' if tools.memory else 'OFF'}")

        async def run_tools(calls: list[tuple[str, str, dict]]) -> AsyncIterator[Event]:
            """Run a batch of tool calls concurrently; stream call/result events in call order."""
            for cid, name, args in calls:
                yield ev("tool_call", id=cid, name=name, args=args)
            outs = await asyncio.gather(*(tools.call(name, args) for _, name, args in calls))
            for (cid, name, args), out in zip(calls, outs):
                transcript.append(f"### {name}({args})\n{out.content[:3000]}")
                messages.append({"role": "tool", "tool_call_id": cid, "content": out.content[:6000]})
                yield ev("tool_result", id=cid, name=name, summary=out.summary,
                         memories=[m.model_dump() for m in out.memories], data=out.data)

        # Deterministic triage: memory is always consulted first (never left to the model's discretion),
        # and the obvious logs/deploys are fetched in the same batch. This keeps an analysis to 1-2
        # LLM calls, which matters on rate-limited LLM tiers; the model can still dig deeper.
        # Three recall angles: the whole picture, the exact error signature (finds the same root cause
        # on *other* services), and what worked/failed before.
        errors = prompts.key_error_lines(self.world.service_logs(incident, incident.service, 30))
        triage: list[tuple[str, dict]] = []
        if tools.memory:
            triage.append(("recall_similar_incidents", {"symptoms": prompts.recall_query(incident, errors),
                                                        "service": incident.service}))
            if errors:
                triage.append(("recall_similar_incidents", {"symptoms": " ".join(errors)}))
            triage.append(("recall_similar_incidents", {"symptoms": prompts.remediation_query(incident, errors)}))
        triage += [("get_service_logs", {"service": incident.service, "minutes": 30}),
                   ("get_recent_deploys", {"hours": 24})]
        calls = [(f"call_triage_{n}", name, args) for n, (name, args) in enumerate(triage)]
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            for cid, name, args in calls]})
        async for e in run_tools(calls):
            yield e

        steps, retries, model_index = 0, 0, 0
        model_used: str | None = None
        degraded_reason: str | None = None
        try:
            final_text = ""
            while True:
                result = await self.llm.step(messages, tools.specs, allowed_tools=tools.names,
                                             force_answer=steps >= self.settings.agent_max_steps,
                                             start_model=model_index)
                model_used, model_index = result.model, self.llm.models.index(result.model)
                if result.retries:
                    retries += result.retries
                    yield ev("retry", model=result.model, retries=result.retries)
                if not result.tool_calls:
                    final_text = result.content
                    break
                steps += 1
                messages.append(result.as_message())
                async for e in run_tools([(tc.id, tc.name, tc.arguments) for tc in result.tool_calls]):
                    yield e

            yield ev("status", message="Writing analysis")
            finalize = [{"role": "system", "content": system},
                        {"role": "user", "content": brief + "\n\nEvidence gathered by tools:\n\n" + "\n\n".join(transcript)}]
            analysis, model_used, r = await self.llm.structured(finalize, IncidentAnalysis, first_reply=final_text,
                                                                start_model=model_index)
            retries += r
        except LLMUnavailable as exc:
            degraded_reason = str(exc)
            log.error("agent.degraded", extra=kv(incident=incident.id, reason=degraded_reason[:200]))
            yield ev("degraded", reason=degraded_reason)
            analysis = degraded_analysis(incident, tools.memories)

        history_found = bool(tools.memories)
        stripped = ground(analysis, tools.memories, history_found=history_found)
        if tools.memory and not history_found and not analysis.summary.startswith(NO_HISTORY):
            analysis.summary = f"{NO_HISTORY} {analysis.summary}"

        meta = AnalysisMeta(memory_mode="on" if use_memory else "off", memory_available=memory_available,
                            history_found=history_found, model=model_used, steps=steps, retries=retries,
                            degraded=degraded_reason is not None, degraded_reason=degraded_reason,
                            elapsed_ms=int((time.perf_counter() - started) * 1000), stripped_citations=stripped)
        log.info("agent.done", extra=kv(incident=incident.id, memory=meta.memory_mode, steps=steps, retries=retries,
                                        memories=len(tools.memories), ms=meta.elapsed_ms, stripped=len(stripped)))
        result_model = AnalysisResult(incident_id=incident.id, analysis=analysis, memories=tools.memories, meta=meta)
        yield ev("final", result=result_model.model_dump())
