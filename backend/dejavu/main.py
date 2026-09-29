"""FastAPI app: incident analysis (streamed over SSE), live learning, deploy checks, dashboards.

Run:  uvicorn dejavu.main:app --reload --app-dir backend
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import narrate
from .agent import IncidentAgent
from .config import Settings, get_settings
from .llm import LLMRouter
from .log import get_logger, kv, setup_logging
from .memory import MemoryStore, MemoryUnavailable
from .schemas import AnalysisResult, CustomIncidentRequest, DeployCheckRequest, ResolveRequest, StepOutcomeRequest
from .tools import assess_deploy_risk, assess_deploy_risk_without_memory, record_step_outcome
from .world import LiveIncident, StepRecord, World, iso, now_utc

log = get_logger("api")


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.world = World()
        self.memory = MemoryStore(settings)
        self.llm = LLMRouter(settings)
        self.agent = IncidentAgent(settings=settings, world=self.world, memory=self.memory, llm=self.llm)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    app.state.s = AppState(settings)
    await app.state.s.memory.probe(max_age_s=0)
    log.info("app.start", extra=kv(memory=app.state.s.memory.status.available, llm=app.state.s.llm.configured,
                                   bank=settings.hindsight_bank_id))
    yield
    await app.state.s.memory.aclose()


app = FastAPI(title="Déjà Vu", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origin_list, allow_methods=["*"],
                   allow_headers=["*"])


def state(request: Request) -> AppState:
    return request.app.state.s


def live_incident(incident_id: str, s: AppState = Depends(state)) -> LiveIncident:
    incident = s.world.get(incident_id)
    if incident is None:
        raise HTTPException(404, f"no live incident {incident_id}")
    return incident


# --------------------------------------------------------------------------- status

@app.get("/api/health")
async def health(s: AppState = Depends(state)):
    await s.memory.probe()
    return {"ok": True, "memory": s.memory.status, "llm": {"configured": s.llm.configured, "models": s.llm.models}}


# --------------------------------------------------------------------------- scenarios & incidents

@app.get("/api/scenarios")
def scenarios(s: AppState = Depends(state)):
    return [{k: sc.get(k) for k in ("id", "kind", "title", "service", "severity", "alert", "planned_change")}
            for sc in s.world.scenarios]


@app.post("/api/scenarios/{scenario_id}/start", response_model=LiveIncident)
def start_scenario(scenario_id: str, s: AppState = Depends(state)):
    try:
        return s.world.start_scenario(scenario_id)
    except KeyError:
        raise HTTPException(404, f"no incident scenario {scenario_id}")


@app.post("/api/incidents", response_model=LiveIncident)
def create_incident(req: CustomIncidentRequest, s: AppState = Depends(state)):
    if req.service not in s.world.services:
        raise HTTPException(422, f"unknown service; choose one of {list(s.world.services)}")
    return s.world.open_custom(service=req.service, severity=req.severity, alert=req.alert, symptoms=req.symptoms)


@app.get("/api/incidents", response_model=list[LiveIncident])
def list_incidents(s: AppState = Depends(state)):
    return sorted(s.world.live.values(), key=lambda i: i.started_at, reverse=True)


@app.get("/api/incidents/{incident_id}", response_model=LiveIncident)
def get_incident(incident: LiveIncident = Depends(live_incident)):
    return incident


def _sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"


@app.post("/api/incidents/{incident_id}/analyze")
async def analyze_stream(memory: bool = True, incident: LiveIncident = Depends(live_incident),
                         s: AppState = Depends(state)):
    """Stream the agent's progress as Server-Sent Events; the last event is `final`."""

    async def events() -> AsyncIterator[str]:
        try:
            async for event in s.agent.run(incident, use_memory=memory):
                yield _sse(event)
        except Exception as exc:  # never leave the client hanging mid-stream
            log.exception("agent.crash", extra=kv(incident=incident.id))
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/incidents/{incident_id}/analyze/sync", response_model=AnalysisResult)
async def analyze_sync(memory: bool = True, incident: LiveIncident = Depends(live_incident),
                       s: AppState = Depends(state)):
    final = None
    async for event in s.agent.run(incident, use_memory=memory):
        if event["type"] == "final":
            final = event["result"]
    return final


class StepOutcomeResponse(BaseModel):
    incident: LiveIncident
    retained: bool
    retained_texts: list[str] = []
    error: str | None = None


@app.post("/api/incidents/{incident_id}/steps", response_model=StepOutcomeResponse)
async def record_step(req: StepOutcomeRequest, incident: LiveIncident = Depends(live_incident),
                      s: AppState = Depends(state)):
    """'Mark worked / Mark failed' — the moment the agent learns live."""
    record = StepRecord(step=req.step, outcome=req.outcome, notes=req.notes, at=iso(now_utc()),
                        sim_minute=incident.sim_minutes_elapsed(), from_agent=req.from_agent)
    error, texts = None, []
    try:
        texts = await record_step_outcome(s.memory, incident, req.step, req.outcome, req.notes, req.from_agent)
        record.retained = True
    except MemoryUnavailable as exc:
        error = str(exc)
    incident.steps.append(record)
    s.world.save()
    return StepOutcomeResponse(incident=incident, retained=record.retained, retained_texts=texts, error=error)


class ResolveBody(ResolveRequest):
    memory_mode: Literal["on", "off"] = "on"


@app.post("/api/incidents/{incident_id}/resolve", response_model=StepOutcomeResponse)
async def resolve(req: ResolveBody, incident: LiveIncident = Depends(live_incident), s: AppState = Depends(state)):
    if incident.status != "resolved":
        incident.status, incident.resolved_at = "resolved", iso(now_utc())
        incident.ttr_minutes = incident.sim_minutes_elapsed()
        incident.root_cause, incident.memory_mode = req.root_cause, req.memory_mode
    worked = [st.step for st in incident.steps if st.outcome == "WORKED"]
    failed = [st.step for st in incident.steps if st.outcome == "FAILED"]
    postmortem = req.summary or (
        f"Resolved live with Déjà Vu (memory {req.memory_mode.upper()}). "
        + (f"Worked: {'; '.join(worked)}. " if worked else "")
        + (f"Failed: {'; '.join(failed)}." if failed else "")
    )
    record = {**incident.as_record(), "ttr_minutes": incident.ttr_minutes, "commander": "on-call engineer",
              "root_cause": req.root_cause, "postmortem": postmortem, "resolved_at": incident.resolved_at}
    item = narrate.resolution_item(record)
    item["update_mode"] = "append"
    items = [item] if incident.alert_retained else [narrate.alert_item(incident.as_record()) | {"update_mode": "append"}, item]
    error = None
    try:
        await s.memory.retain_batch(items, document_id=incident.id)
        incident.alert_retained = True
        asyncio.create_task(s.memory.refresh_playbook())
    except MemoryUnavailable as exc:
        error = str(exc)
    s.world.save()
    return StepOutcomeResponse(incident=incident, retained=error is None,
                               retained_texts=[i["content"] for i in items] if error is None else [], error=error)


# --------------------------------------------------------------------------- deploy check

class DeployCheckBody(DeployCheckRequest):
    memory: bool = True


@app.post("/api/deploy-check")
async def deploy_check(req: DeployCheckBody, s: AppState = Depends(state)):
    if req.memory and await s.memory.probe(max_age_s=10):
        try:
            risk, evidence = await assess_deploy_risk(s.memory, s.llm, req.service, req.change_description)
            return {"risk": risk, "memories": evidence, "memory_mode": "on", "memory_available": True}
        except MemoryUnavailable:
            pass
    risk = await assess_deploy_risk_without_memory(s.llm, req.service, req.change_description)
    return {"risk": risk, "memories": [], "memory_mode": "on" if req.memory else "off",
            "memory_available": s.memory.status.available}


# --------------------------------------------------------------------------- memory & dashboard

@app.get("/api/memory/observations")
async def observations(s: AppState = Depends(state)):
    """'What Déjà Vu has learned': consolidated cross-incident observations + the playbook mental model."""
    try:
        groups, playbook = await asyncio.gather(s.memory.learned(), s.memory.playbook())
    except MemoryUnavailable as exc:
        return {"available": False, "reason": str(exc), "groups": [], "playbook": None}
    return {"available": True, "groups": groups, "playbook": playbook}


@app.get("/api/memory/stats")
async def memory_stats(s: AppState = Depends(state)):
    try:
        return {"available": True, "counts": await s.memory.stats()}
    except MemoryUnavailable as exc:
        return {"available": False, "reason": str(exc), "counts": {}}


@app.get("/api/memory/search")
async def memory_search(q: str, s: AppState = Depends(state)):
    try:
        return {"available": True, "memories": await s.memory.recall(q, budget="low")}
    except MemoryUnavailable as exc:
        return {"available": False, "reason": str(exc), "memories": []}


@app.get("/api/dashboard/learning-curve")
def learning_curve(s: AppState = Depends(state)):
    return s.world.learning_curve()


@app.get("/api/history/incidents")
def history(s: AppState = Depends(state)):
    return s.world.history


@app.post("/api/demo/reset")
def demo_reset(s: AppState = Depends(state)):
    """Clear live demo incidents (memory is untouched; use `make seed-reset` for that)."""
    s.world.reset_live()
    return {"ok": True}
