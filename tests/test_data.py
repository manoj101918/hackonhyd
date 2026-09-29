"""The synthetic data is deterministic, committed, and contains the patterns memory should learn."""

import importlib.util
import json
from pathlib import Path

from dejavu import narrate

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("generate_data", ROOT / "scripts" / "generate_data.py")
generate_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate_data)


def test_generation_is_deterministic_and_committed():
    incidents, deploys, scenarios = generate_data.build()
    assert generate_data.build() == (incidents, deploys, scenarios)
    assert json.loads((ROOT / "data" / "incidents.json").read_text(encoding="utf-8")) == incidents
    assert json.loads((ROOT / "data" / "deploys.json").read_text(encoding="utf-8")) == deploys


def test_history_shape():
    incidents, deploys, scenarios = generate_data.build()
    assert len(incidents) == 20 and len(deploys) == 30 and len(scenarios["scenarios"]) == 3
    failed = [s for i in incidents for s in i["steps"] if s["outcome"] == "FAILED"]
    assert len(failed) >= 8
    pool = [i for i in incidents if i["pattern"] == "db-pool-exhaustion"]
    assert len({i["service"] for i in pool}) == 3
    assert all(any(s["action"].startswith("Restart") and s["outcome"] == "FAILED" for s in i["steps"]) for i in pool)


def test_memory_makes_mttr_drop():
    incidents, _, _ = generate_data.build()
    before = [i["ttr_minutes"] for i in incidents if not i["dejavu_assisted"]]
    after = [i["ttr_minutes"] for i in incidents if i["dejavu_assisted"]]
    assert sum(after) / len(after) < 0.7 * sum(before) / len(before)


def test_narrated_items_carry_incident_id_and_metadata():
    incidents, deploys, _ = generate_data.build()
    items = narrate.incident_items(incidents[4], {d["id"]: d for d in deploys})
    assert all(item["content"].count("INC-031") >= 1 for item in items)
    assert all(set(item["metadata"]) >= {"kind", "service", "incident_id"} for item in items)
    assert all(isinstance(v, str) for item in items for v in item["metadata"].values())  # Hindsight requires str
    assert any("did NOT fix" in item["content"] for item in items)
