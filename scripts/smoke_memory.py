"""Smoke-test Hindsight connectivity: retain -> recall -> reflect in a throwaway bank, then delete it.

    python scripts/smoke_memory.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

from dejavu.config import get_settings
from dejavu.memory import MemoryStore, MemoryUnavailable


async def main() -> int:
    settings = get_settings().model_copy(update={"hindsight_bank_id": "dejavu-smoke-test"})
    store = MemoryStore(settings)
    try:
        await store.ensure_bank(reset=True)
        await store.retain({
            "content": "INC-900 on checkout-api (SEV1, 2026-08-14): Restarting checkout-api pods did NOT fix the "
                       "HTTP 500s; errors returned within 3 minutes. Outcome: FAILED.",
            "context": "smoke test", "timestamp": datetime(2026, 8, 14, tzinfo=timezone.utc),
            "document_id": "INC-900", "metadata": {"incident_id": "INC-900", "kind": "step"},
        }, update_mode=None)
        hits = await store.recall("did restarting checkout-api fix the 500s?")
        print(f"recall: {len(hits)} hits")
        for h in hits[:5]:
            print(f"  [{h.type}] {h.incident_ids} {h.date} {h.text[:110]}")
        answer = await store.reflect("Should I restart checkout-api pods for HTTP 500s?")
        print(f"reflect: {answer.text[:300]}")
        print(f"reflect evidence: {[h.incident_ids for h in answer.evidence]}")
        await store._client.adelete_bank(settings.hindsight_bank_id)
    except MemoryUnavailable as exc:
        print(f"FAILED: {exc}")
        return 1
    finally:
        await store.aclose()
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
