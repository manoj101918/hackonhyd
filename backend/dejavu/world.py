"""The simulated production world: historical data, live demo scenarios, and live incident state.

Live incidents are created when a demo scenario is played (or a custom alert is raised). Their
logs and deploys are rendered relative to the incident's start time, and time-to-resolve is
measured on a demo clock that runs `DEMO_CLOCK_SPEED` times faster than wall-clock time so a
90-second demo maps to a realistic MTTR.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .config import DATA_DIR, RUNTIME_DIR

DEMO_CLOCK_SPEED = 10  # 1 real second = 10 simulated seconds
FIRST_LIVE_INCIDENT = 47  # historical data ends at INC-046


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StepRecord(BaseModel):
    step: str
    outcome: str
    notes: str = ""
    at: str
    sim_minute: int
    from_agent: bool = True
    retained: bool = False


class LiveIncident(BaseModel):
    id: str
    scenario_id: str | None = None
    title: str
    service: str
    severity: str
    alert: str
    symptoms: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    started_at: str
    status: str = "open"  # open | resolved
    steps: list[StepRecord] = Field(default_factory=list)
    resolved_at: str | None = None
    ttr_minutes: int | None = None
    root_cause: str | None = None
    memory_mode: str | None = None  # "on"/"off" — which analysis the engineer worked from
    alert_retained: bool = False

    @property
    def started(self) -> datetime:
        return datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))

    def sim_minutes_elapsed(self, at: datetime | None = None) -> int:
        real = ((at or now_utc()) - self.started).total_seconds()
        return max(1, round(real * DEMO_CLOCK_SPEED / 60))

    def as_record(self) -> dict[str, Any]:
        """Shape compatible with narrate.alert_item()."""
        return {"id": self.id, "service": self.service, "severity": self.severity, "title": self.title,
                "alert": self.alert, "symptoms": self.symptoms, "metrics": self.metrics,
                "started_at": self.started_at, "logs": []}


class World:
    def __init__(self, data_dir: Path = DATA_DIR, runtime_dir: Path = RUNTIME_DIR):
        self.data_dir = data_dir
        self.runtime_file = runtime_dir / "live_incidents.json"
        self._lock = threading.Lock()
        self.next_number = FIRST_LIVE_INCIDENT
        self.live: dict[str, LiveIncident] = self._load_live()

    # ------------------------------------------------------------------ static data

    @cached_property
    def history(self) -> list[dict]:
        return json.loads((self.data_dir / "incidents.json").read_text(encoding="utf-8"))

    @cached_property
    def deploys(self) -> list[dict]:
        return json.loads((self.data_dir / "deploys.json").read_text(encoding="utf-8"))

    @cached_property
    def _scenario_file(self) -> dict:
        return json.loads((self.data_dir / "scenarios.json").read_text(encoding="utf-8"))

    @property
    def services(self) -> dict[str, str]:
        return self._scenario_file["services"]

    @property
    def scenarios(self) -> list[dict]:
        return self._scenario_file["scenarios"]

    def scenario(self, scenario_id: str) -> dict | None:
        return next((s for s in self.scenarios if s["id"] == scenario_id), None)

    # ------------------------------------------------------------------ live incidents

    def _load_live(self) -> dict[str, LiveIncident]:
        if not self.runtime_file.exists():
            return {}
        raw = json.loads(self.runtime_file.read_text(encoding="utf-8"))
        self.next_number = raw.get("next_number", FIRST_LIVE_INCIDENT)
        return {r["id"]: LiveIncident.model_validate(r) for r in raw.get("incidents", [])}

    def save(self) -> None:
        with self._lock:
            self.runtime_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {"next_number": self.next_number, "incidents": [i.model_dump() for i in self.live.values()]}
            self.runtime_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _next_id(self) -> str:
        # Never reuse an ID: memory keeps live incidents even after a demo reset.
        number, self.next_number = self.next_number, self.next_number + 1
        return f"INC-{number:03d}"

    def start_scenario(self, scenario_id: str) -> LiveIncident:
        s = self.scenario(scenario_id)
        if s is None or s["kind"] != "incident":
            raise KeyError(scenario_id)
        return self._open(scenario_id=scenario_id, title=s["title"], service=s["service"], severity=s["severity"],
                          alert=s["alert"], symptoms=s["symptoms"], metrics=s["metrics"])

    def open_custom(self, *, service: str, severity: str, alert: str, symptoms: list[str]) -> LiveIncident:
        return self._open(scenario_id=None, title=alert[:90], service=service, severity=severity,
                          alert=alert, symptoms=symptoms, metrics={})

    def _open(self, **fields: Any) -> LiveIncident:
        incident = LiveIncident(id=self._next_id(), started_at=iso(now_utc()), **fields)
        self.live[incident.id] = incident
        self.save()
        return incident

    def get(self, incident_id: str) -> LiveIncident | None:
        return self.live.get(incident_id)

    def reset_live(self, *, reset_ids: bool = False) -> None:
        """Clear live incidents. IDs keep counting unless memory was wiped too (seed --reset)."""
        self.live.clear()
        if reset_ids:
            self.next_number = FIRST_LIVE_INCIDENT
        self.save()

    # ------------------------------------------------------------------ simulated observability

    def service_logs(self, incident: LiveIncident, service: str, minutes: int = 30) -> list[str]:
        if service not in self.services:
            raise ValueError(f"unknown service {service!r}; known services: {', '.join(self.services)}")
        scenario = self.scenario(incident.scenario_id) if incident.scenario_id else None
        lines = (scenario or {}).get("logs", {}).get(service)
        if lines:
            window = -minutes * 60
            return [f"{iso(incident.started + timedelta(seconds=l['offset_s']))} {l['line']}"
                    for l in lines if l["offset_s"] >= window]
        baseline = self._scenario_file["baseline_logs"].get(service, [])
        return [f"{iso(incident.started - timedelta(seconds=60 * (len(baseline) - i)))} {line}"
                for i, line in enumerate(baseline)]

    def recent_deploys(self, incident: LiveIncident, service: str | None = None, hours: float = 24) -> list[dict]:
        scenario = self.scenario(incident.scenario_id) if incident.scenario_id else None
        out = []
        for d in (scenario or {}).get("deploys", []):
            if d["hours_ago"] > hours or (service and d["service"] != service):
                continue
            at = incident.started - timedelta(hours=d["hours_ago"])
            out.append({"service": d["service"], "kind": d["kind"], "version": d["version"],
                        "description": d["description"], "deployed_at": iso(at),
                        "minutes_before_alert": round(d["hours_ago"] * 60)})
        return sorted(out, key=lambda d: d["deployed_at"], reverse=True)

    # ------------------------------------------------------------------ dashboard

    def learning_curve(self) -> list[dict]:
        points = [{"id": i["id"], "date": i["started_at"], "ttr_minutes": i["ttr_minutes"],
                   "service": i["service"], "severity": i["severity"], "title": i["title"],
                   "source": "history", "assisted": i["dejavu_assisted"]} for i in self.history]
        for inc in self.live.values():
            if inc.status == "resolved" and inc.ttr_minutes is not None:
                points.append({"id": inc.id, "date": inc.resolved_at, "ttr_minutes": inc.ttr_minutes,
                               "service": inc.service, "severity": inc.severity, "title": inc.title,
                               "source": "live", "assisted": inc.memory_mode != "off"})
        return points
