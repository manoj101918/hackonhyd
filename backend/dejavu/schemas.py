"""Pydantic models shared by the agent, the API and the memory layer."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator

INCIDENT_ID_RE = re.compile(r"\bINC-\d{3,}\b")

FactType = Literal["world", "experience", "observation"]
Outcome = Literal["WORKED", "FAILED", "PARTIAL"]
Confidence = Literal["low", "medium", "high"]


def _clean_ids(values: list[str] | None) -> list[str]:
    """Normalise model-produced citations: extract INC-### tokens, uppercase, de-duplicate."""
    seen: list[str] = []
    for v in values or []:
        for match in INCIDENT_ID_RE.findall(str(v).upper()):
            if match not in seen:
                seen.append(match)
    return seen


IncidentIds = Annotated[list[str], BeforeValidator(_clean_ids)]


# --------------------------------------------------------------------------- memory

class MemoryHit(BaseModel):
    """One memory as shown in the UI's memory panel."""

    id: str
    text: str
    type: str | None = None  # world | experience | observation
    incident_ids: list[str] = Field(default_factory=list)
    date: str | None = None
    context: str | None = None
    score: float | None = None
    proof_count: int | None = None  # observations: how many facts back this learned pattern
    source: Literal["recall", "reflect", "list"] = "recall"


class ReflectResult(BaseModel):
    text: str
    structured: dict | None = None
    evidence: list[MemoryHit] = Field(default_factory=list)


class MemoryStatus(BaseModel):
    available: bool
    bank_id: str
    base_url: str
    reason: str | None = None


# --------------------------------------------------------------------------- agent output

class RecommendedStep(BaseModel):
    step: str
    rationale: str = ""
    evidence_incident_ids: IncidentIds = Field(default_factory=list)


class AvoidStep(BaseModel):
    step: str
    reason: str = ""
    evidence_incident_ids: IncidentIds = Field(default_factory=list)


class SimilarIncident(BaseModel):
    id: str
    date: str | None = None
    similarity_reason: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v: str) -> str:
        ids = _clean_ids([v])
        if not ids:
            raise ValueError(f"not an incident id: {v!r}")
        return ids[0]


class IncidentAnalysis(BaseModel):
    """The agent's structured answer for a new incident (validated before it reaches the UI)."""

    summary: str
    likely_root_cause: str
    confidence: Confidence
    recommended_steps: list[RecommendedStep] = Field(min_length=1)
    avoid_steps: list[AvoidStep] = Field(default_factory=list)
    similar_incidents: list[SimilarIncident] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, v: str) -> str:
        v = str(v).strip().lower()
        return {"med": "medium", "moderate": "medium"}.get(v, v)


class AnalysisMeta(BaseModel):
    memory_mode: Literal["on", "off"]
    memory_available: bool
    history_found: bool
    model: str | None = None
    steps: int = 0
    retries: int = 0
    degraded: bool = False
    degraded_reason: str | None = None
    elapsed_ms: int = 0
    stripped_citations: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    incident_id: str
    analysis: IncidentAnalysis
    memories: list[MemoryHit]
    meta: AnalysisMeta


# --------------------------------------------------------------------------- deploy risk

class DeployRisk(BaseModel):
    risk: Literal["low", "medium", "high", "unknown"]
    verdict: str
    reasons: list[str] = Field(default_factory=list)
    evidence_incident_ids: IncidentIds = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

    @field_validator("risk", mode="before")
    @classmethod
    def _risk(cls, v: str) -> str:
        v = str(v).strip().lower()
        return v if v in {"low", "medium", "high"} else "unknown"


DEPLOY_RISK_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "verdict": {"type": "string", "description": "One-sentence verdict citing incident IDs"},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "evidence_incident_ids": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["risk", "verdict", "reasons", "evidence_incident_ids", "recommendations"],
}


# --------------------------------------------------------------------------- API requests

class AnalyzeRequest(BaseModel):
    memory: bool = True


class CustomIncidentRequest(BaseModel):
    service: str
    severity: Literal["SEV1", "SEV2", "SEV3"] = "SEV2"
    alert: str = Field(min_length=5)
    symptoms: list[str] = Field(default_factory=list)


class StepOutcomeRequest(BaseModel):
    step: str = Field(min_length=3)
    outcome: Outcome
    notes: str = ""
    minutes: int | None = None
    from_agent: bool = True  # the step came from Déjà Vu's recommendation list


class ResolveRequest(BaseModel):
    root_cause: str = Field(min_length=5)
    summary: str = ""


class DeployCheckRequest(BaseModel):
    service: str
    change_description: str = Field(min_length=10)
