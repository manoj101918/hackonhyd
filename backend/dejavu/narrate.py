"""Turn structured incident records into the natural-language sentences we retain in Hindsight.

Hindsight extracts facts from free text, so every memory is written as a self-contained sentence
that repeats the incident ID, service, severity and date. That way each extracted fact carries
its own evidence ("INC-031 on checkout-api ...") and the agent can cite it back.

Each function returns a `RetainItem` dict accepted by `Hindsight.retain_batch`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

RetainItem = dict[str, Any]

OUTCOME_PHRASES = {
    "WORKED": "WORKED — it fixed the problem",
    "FAILED": "did NOT fix the problem. Outcome: FAILED",
    "PARTIAL": "only partially helped. Outcome: PARTIAL",
}


def parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _header(incident_id: str, service: str, severity: str, when: str | datetime) -> str:
    return f"{incident_id} on {service} ({severity}, {parse_ts(when):%Y-%m-%d})"


def _item(content: str, *, context: str, when: str | datetime, kind: str, incident_id: str | None,
          service: str, extra_meta: dict[str, str] | None = None) -> RetainItem:
    metadata = {"kind": kind, "service": service, **(extra_meta or {})}
    if incident_id:
        metadata["incident_id"] = incident_id
    return {
        "content": content,
        "context": context,
        "timestamp": parse_ts(when),
        "metadata": metadata,
        "tags": [f"service:{service}", f"kind:{kind}"],
        **({"document_id": incident_id} if incident_id else {}),
    }


def alert_item(incident: dict) -> RetainItem:
    iid, svc, sev = incident["id"], incident["service"], incident["severity"]
    parts = [f"{_header(iid, svc, sev, incident['started_at'])}: alert fired — {incident['alert']}."]
    if incident.get("title"):
        parts.append(f"Incident title: {incident['title']}.")
    if incident.get("symptoms"):
        parts.append("Symptoms: " + "; ".join(incident["symptoms"]) + ".")
    if incident.get("metrics"):
        parts.append("Metrics: " + ", ".join(f"{k}={v}" for k, v in incident["metrics"].items()) + ".")
    if incident.get("logs"):
        parts.append("Key log lines: " + " | ".join(incident["logs"][:3]))
    return _item(" ".join(parts), context="production incident alert and symptoms", when=incident["started_at"],
                 kind="alert", incident_id=iid, service=svc, extra_meta={"severity": sev})


def step_item(*, incident_id: str, service: str, severity: str, when: str | datetime, action: str,
              outcome: str, minutes: int | None = None, notes: str = "", by: str | None = None) -> RetainItem:
    outcome = outcome.upper()
    who = f" by {by}" if by else ""
    took = f" after {minutes} min" if minutes else ""
    text = (f"{_header(incident_id, service, severity, when)}: remediation step '{action}'{who}"
            f" {OUTCOME_PHRASES.get(outcome, 'Outcome: ' + outcome)}{took}.")
    if notes:
        text += f" Notes: {notes}."
    return _item(text, context="remediation step and its outcome", when=when, kind="step",
                 incident_id=incident_id, service=service, extra_meta={"outcome": outcome, "severity": severity})


def resolution_item(incident: dict, deploy: dict | None = None) -> RetainItem:
    iid, svc, sev = incident["id"], incident["service"], incident["severity"]
    text = (f"{_header(iid, svc, sev, incident['started_at'])} was resolved in {incident['ttr_minutes']} minutes"
            f" (incident commander: {incident['commander']}). Root cause: {incident['root_cause']}")
    if deploy:
        text += (f" The incident was triggered by deploy {deploy['id']} on {deploy['service']}"
                 f" ({deploy['kind']} change '{deploy['description']}', deployed {parse_ts(deploy['deployed_at']):%Y-%m-%d %H:%M} UTC"
                 f" by {deploy['author']}).")
    text += f" Postmortem: {incident['postmortem']}"
    return _item(text, context="incident root cause and postmortem", when=incident["resolved_at"],
                 kind="postmortem", incident_id=iid, service=svc,
                 extra_meta={"severity": sev, "ttr_minutes": str(incident["ttr_minutes"])})


def agent_suggestion_item(*, incident_id: str, service: str, severity: str, when: str | datetime,
                          suggestion: str, accepted: bool, outcome: str, notes: str = "") -> RetainItem:
    """Déjà Vu's own advice and how it turned out — retained in first person so Hindsight files it
    as an *experience* fact, which is how the agent learns from its own mistakes."""
    verdict = "accepted" if accepted else "did not follow"
    text = (f"During {_header(incident_id, service, severity, when)}, I (Déjà Vu, the on-call memory agent)"
            f" recommended: \"{suggestion}\". The engineer {verdict} my recommendation and the outcome was {outcome.upper()}.")
    if notes:
        text += f" {notes}."
    return _item(text, context="my own recommendation during an incident and whether it worked", when=when,
                 kind="agent_suggestion", incident_id=incident_id, service=service,
                 extra_meta={"outcome": outcome.upper(), "accepted": str(accepted).lower()})


def deploy_item(deploy: dict) -> RetainItem:
    text = (f"Deploy {deploy['id']}: {deploy['kind']} change to {deploy['service']} ({deploy['version']}) deployed"
            f" {parse_ts(deploy['deployed_at']):%Y-%m-%d %H:%M} UTC by {deploy['author']}: {deploy['description']}.")
    item = _item(text, context="deploy or config change event", when=deploy["deployed_at"], kind="deploy",
                 incident_id=None, service=deploy["service"], extra_meta={"deploy_id": deploy["id"], "change_kind": deploy["kind"]})
    item["document_id"] = deploy["id"]
    return item


def incident_items(incident: dict, deploys_by_id: dict[str, dict]) -> list[RetainItem]:
    """Everything we know about one historical incident, in chronological order."""
    iid, svc, sev = incident["id"], incident["service"], incident["severity"]
    items = [alert_item(incident)]
    for s in incident.get("agent_suggestions", []):
        items.append(agent_suggestion_item(incident_id=iid, service=svc, severity=sev, when=incident["started_at"],
                                           suggestion=s["suggestion"], accepted=s["accepted"],
                                           outcome=s["outcome"], notes=s.get("notes", "")))
    for s in incident["steps"]:
        items.append(step_item(incident_id=iid, service=svc, severity=sev, when=s["at"], action=s["action"],
                               outcome=s["outcome"], minutes=s["minutes"], notes=s["notes"], by=s["by"]))
    items.append(resolution_item(incident, deploys_by_id.get(incident.get("trigger_deploy_id") or "")))
    return items
