"""Agent tools. Each tool returns text for the LLM plus structured data for the UI.

Memory-backed tools (recall / reflect / deploy risk) are only offered when memory is ON, which is
exactly what the Memory ON/OFF comparison toggles. `record_step_outcome` is *not* offered to the
LLM: memory writes only come from outcomes an engineer has verified, so the model cannot poison
its own memory with guesses. The UI's "Mark worked / Mark failed" buttons call it instead.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from . import narrate, prompts
from .llm import LLMRouter, LLMUnavailable
from .log import get_logger, kv
from .memory import MemoryStore, MemoryUnavailable
from .schemas import DEPLOY_RISK_JSON_SCHEMA, INCIDENT_ID_RE, DeployRisk, MemoryHit
from .world import LiveIncident, World, iso, now_utc

log = get_logger("tools")

MAX_HITS_FOR_LLM = 10
MAX_HIT_CHARS = 260


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


MEMORY_TOOLS = [
    _fn("recall_similar_incidents",
        "Search long-term incident memory (semantic + keyword + entity graph + temporal) for past incidents, "
        "remediation outcomes, deploys and learned patterns similar to the given symptoms.",
        {"symptoms": {"type": "string", "description": "Symptoms, error messages or a question to search for"},
         "service": {"type": "string", "description": "Affected service, e.g. checkout-api"}},
        ["symptoms"]),
    _fn("reflect_root_cause",
        "Ask the memory system to reason over ALL past incidents and answer a question, e.g. "
        "'What root cause best explains X, and what fixed it before?'. Slower than recall; use once.",
        {"question": {"type": "string"}}, ["question"]),
    _fn("check_deploy_risk",
        "Check memory for whether changes like this one preceded outages before.",
        {"service": {"type": "string"}, "change_description": {"type": "string"}},
        ["service", "change_description"]),
]

WORLD_TOOLS = [
    _fn("get_service_logs", "Fetch recent log lines for a service.",
        {"service": {"type": "string"}, "minutes": {"type": "integer", "description": "Look-back window, default 30"}},
        ["service"]),
    _fn("get_recent_deploys", "List deploys and config changes in the look-back window (all services if service omitted).",
        {"service": {"type": "string"}, "hours": {"type": "number", "description": "Look-back window, default 24"}},
        []),
]


@dataclass
class ToolOutput:
    content: str  # what the LLM sees
    summary: str  # one line for the UI timeline
    memories: list[MemoryHit] = field(default_factory=list)
    data: Any = None


def format_hits(hits: list[MemoryHit], limit: int = MAX_HITS_FOR_LLM) -> str:
    if not hits:
        return "No similar past incidents found in memory."
    lines = []
    for n, h in enumerate(hits[:limit], start=1):
        ids = ",".join(h.incident_ids) or "-"
        text = h.text if len(h.text) <= MAX_HIT_CHARS else h.text[:MAX_HIT_CHARS] + "..."
        lines.append(f"[{n}] ({h.type or '?'} | {ids} | {h.date or '?'}) {text}")
    return "\n".join(lines)


def without_incident(hits: list[MemoryHit], incident_id: str) -> list[MemoryHit]:
    """Drop memories that are only about the incident being analysed (no self-citation on re-runs)."""
    return [h for h in hits if h.incident_ids != [incident_id]]


async def assess_deploy_risk(memory: MemoryStore, llm: LLMRouter, service: str, change: str,
                             budget: str = "mid") -> tuple[DeployRisk, list[MemoryHit]]:
    """Memory-backed deploy risk: Hindsight reflect (structured) + recall for visible evidence.

    Evidence IDs are grounded: only IDs present in the recalled/reflected memories survive.
    """
    question = prompts.deploy_risk_question(service, change)
    recall_task = asyncio.create_task(memory.recall(
        f"{service} {change} — deploys or config changes that preceded outages", budget="mid"))
    reflect_result = None
    try:
        reflect_result = await memory.reflect(question, budget=budget, response_schema=DEPLOY_RISK_JSON_SCHEMA)
    except MemoryUnavailable as exc:
        log.warning("deploy_risk.reflect_failed", extra=kv(error=str(exc)[:200]))
    hits = await recall_task  # raises MemoryUnavailable if memory is down entirely

    evidence = _dedupe(hits + (reflect_result.evidence if reflect_result else []))
    risk: DeployRisk | None = None
    if reflect_result and reflect_result.structured:
        try:
            risk = DeployRisk.model_validate(reflect_result.structured)
        except ValueError:
            risk = None
    if risk is None:
        # Reflect gave free text (or failed): have the LLM structure a verdict from the memories.
        messages = [{"role": "system", "content": prompts.DEPLOY_RISK_FROM_MEMORIES_SYSTEM},
                    {"role": "user", "content": f"{question}\n\nReflection: {reflect_result.text if reflect_result else 'n/a'}"
                                                f"\n\nMemories:\n{format_hits(evidence, 20)}"}]
        try:
            risk, _, _ = await llm.structured(messages, DeployRisk)
        except LLMUnavailable:
            risk = DeployRisk(risk="unknown", verdict=(reflect_result.text[:500] if reflect_result else
                                                       "Could not assess risk: language model unavailable."))
    known = {i for h in evidence for i in h.incident_ids}
    risk.evidence_incident_ids = [i for i in risk.evidence_incident_ids if i in known]
    return risk, evidence


async def assess_deploy_risk_without_memory(llm: LLMRouter, service: str, change: str) -> DeployRisk:
    messages = [{"role": "system", "content": prompts.DEPLOY_RISK_NO_MEMORY_SYSTEM},
                {"role": "user", "content": f"Planned change to {service}: {change}"}]
    try:
        risk, _, _ = await llm.structured(messages, DeployRisk)
    except LLMUnavailable:
        return DeployRisk(risk="unknown", verdict="Could not assess risk: language model unavailable.")
    risk.evidence_incident_ids = []
    return risk


def _dedupe(hits: list[MemoryHit]) -> list[MemoryHit]:
    seen: set[str] = set()
    out = []
    for h in hits:
        key = h.id or h.text
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out


class Toolbox:
    """Tools bound to one incident analysis run. Collects every memory it surfaces."""

    def __init__(self, *, world: World, memory: MemoryStore | None, llm: LLMRouter, incident: LiveIncident):
        self.world = world
        self.memory = memory  # None => memory OFF
        self.llm = llm
        self.incident = incident
        self.memories: list[MemoryHit] = []

    @property
    def specs(self) -> list[dict]:
        return (MEMORY_TOOLS if self.memory else []) + WORLD_TOOLS

    @property
    def names(self) -> set[str]:
        return {t["function"]["name"] for t in self.specs}

    def _collect(self, hits: list[MemoryHit]) -> list[MemoryHit]:
        hits = without_incident(hits, self.incident.id)
        self.memories = _dedupe(self.memories + hits)
        return hits

    @property
    def known_incident_ids(self) -> set[str]:
        return {i for h in self.memories for i in h.incident_ids}

    async def call(self, name: str, args: dict[str, Any]) -> ToolOutput:
        handler = getattr(self, f"_{name}", None)
        if name not in self.names or handler is None:
            return ToolOutput(content=f"Error: unknown tool {name!r}.", summary=f"unknown tool {name}")
        try:
            return await handler(**args)
        except TypeError as exc:  # wrong/missing arguments from the model
            return ToolOutput(content=f"Error: bad arguments for {name}: {exc}", summary="bad arguments")
        except ValueError as exc:
            return ToolOutput(content=f"Error: {exc}", summary=str(exc))
        except MemoryUnavailable as exc:
            return ToolOutput(content=f"Memory is unavailable right now ({exc}). Continue without it.",
                              summary="memory unavailable")

    # ------------------------------------------------------------------ memory tools

    async def _recall_similar_incidents(self, symptoms: str, service: str | None = None) -> ToolOutput:
        query = f"{service}: {symptoms}" if service else symptoms
        raw = await self.memory.recall(query)
        already_shown = {h.id for h in self.memories}
        hits = self._collect(raw)
        fresh = [h for h in hits if h.id not in already_shown]  # the LLM sees each memory once per run
        content = format_hits(fresh) if fresh or not hits else "(all matching memories were already listed above)"
        return ToolOutput(content=content, memories=hits,
                          summary=f"recalled {len(hits)} memories" if hits else "no similar past incidents found")

    async def _reflect_root_cause(self, question: str) -> ToolOutput:
        res = await self.memory.reflect(question, context=prompts.incident_brief(self.incident, self.world.services))
        hits = self._collect(res.evidence)
        cited = sorted(set(INCIDENT_ID_RE.findall(res.text)))
        return ToolOutput(content=res.text or "No answer.", memories=hits, data={"text": res.text},
                          summary=f"reflected over memory ({', '.join(cited) or 'no incident IDs cited'})")

    async def _check_deploy_risk(self, service: str, change_description: str) -> ToolOutput:
        risk, evidence = await assess_deploy_risk(self.memory, self.llm, service, change_description, budget="low")
        hits = self._collect(evidence)
        return ToolOutput(content=risk.model_dump_json(), memories=hits, data=risk.model_dump(),
                          summary=f"deploy risk {risk.risk.upper()}: {risk.verdict[:120]}")

    # ------------------------------------------------------------------ world tools

    async def _get_service_logs(self, service: str, minutes: int = 30) -> ToolOutput:
        lines = self.world.service_logs(self.incident, service, int(minutes))
        return ToolOutput(content="\n".join(lines) or "(no log lines in window)", data=lines,
                          summary=f"{len(lines)} log lines from {service}")

    async def _get_recent_deploys(self, service: str | None = None, hours: float = 24) -> ToolOutput:
        deploys = self.world.recent_deploys(self.incident, service or None, float(hours))
        return ToolOutput(content=json.dumps(deploys, indent=1) if deploys else "No deploys in the window.",
                          data=deploys, summary=f"{len(deploys)} deploys in last {hours:g}h")


async def record_step_outcome(memory: MemoryStore, incident: LiveIncident, step: str, outcome: str,
                              notes: str = "", from_agent: bool = True) -> list[str]:
    """Retain what the engineer tried and whether it worked (plus, for Déjà Vu's own suggestions,
    an experience fact about its advice). Returns the retained texts."""
    minute = incident.sim_minutes_elapsed()
    items = [narrate.step_item(incident_id=incident.id, service=incident.service, severity=incident.severity,
                               when=iso(now_utc()), action=step, outcome=outcome, minutes=minute, notes=notes)]
    if from_agent:
        items.append(narrate.agent_suggestion_item(
            incident_id=incident.id, service=incident.service, severity=incident.severity, when=iso(now_utc()),
            suggestion=step, accepted=True, outcome=outcome, notes=notes))
    if not incident.alert_retained:
        items.insert(0, narrate.alert_item(incident.as_record()))
    for item in items:
        item["update_mode"] = "append"
    await memory.retain_batch(items, document_id=incident.id)
    incident.alert_retained = True
    return [i["content"] for i in items]
