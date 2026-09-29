"""Definition of the `acme-incidents` memory bank: mission, extraction focus, directives and the
self-refreshing "remediation playbook" mental model."""

REFLECT_MISSION = (
    "I am the on-call memory for Acme's engineering team. I track production incidents, their "
    "symptoms, root causes, which remediation steps worked and which failed, and which deploys or "
    "config changes preceded outages. I prioritize fixes proven to work and warn against steps that "
    "previously failed."
)

RETAIN_MISSION = (
    "Extract production-incident facts: incident IDs (INC-###), deploy IDs (DEP-####), the affected "
    "service, severity, date, alert text and error messages, each remediation step with its outcome "
    "(WORKED / FAILED / PARTIAL) and duration, root causes, and which deploy or config change "
    "preceded an incident. Always keep the incident ID attached to every fact. Record the on-call "
    "agent's own recommendations and whether they worked as the agent's experience."
)

OBSERVATIONS_MISSION = (
    "Consolidate recurring operational patterns across incidents: for each kind of root cause, "
    "which remediation steps repeatedly worked and which repeatedly failed (cite the incident IDs), "
    "which kinds of deploys or config changes on which services preceded outages, and where the "
    "on-call agent's own recommendations were right or wrong."
)

DISPOSITION = {"disposition_skepticism": 4, "disposition_literalism": 3, "disposition_empathy": 2}

DIRECTIVES = [
    {
        "name": "cite-evidence",
        "content": "Always cite the incident IDs (INC-###) and deploy IDs (DEP-####) that support each claim.",
        "priority": 10,
    },
    {
        "name": "warn-failed-steps",
        "content": "Never recommend a remediation step that previously FAILED for the same root cause without "
                   "explicitly saying it failed before and in which incidents.",
        "priority": 9,
    },
    {
        "name": "admit-no-history",
        "content": "If there is no relevant incident history, say clearly that no similar past incidents were "
                   "found. Never invent incidents, IDs or outcomes.",
        "priority": 8,
    },
]

PLAYBOOK_MODEL_ID = "remediation-playbook"
MENTAL_MODELS = [
    {
        "id": PLAYBOOK_MODEL_ID,
        "name": "Remediation playbook",
        "source_query": "For each recurring root cause seen in Acme's incidents, which remediation steps worked, "
                        "which failed, and which deploys or config changes are risky? Cite incident IDs.",
        "max_tokens": 1200,
        "trigger": {"refresh_after_consolidation": True},
    },
]
