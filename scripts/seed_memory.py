"""Create the Hindsight bank and retain Acme's incident history with backdated timestamps.

    python scripts/seed_memory.py            # idempotent: documents are replaced, not duplicated
    python scripts/seed_memory.py --reset    # delete the bank first, then seed from scratch

Each historical incident becomes one Hindsight document (document_id = INC-###) holding its alert,
Déjà Vu's own suggestions, every remediation step with its outcome, and the postmortem. Each deploy
becomes its own document (DEP-####). Live demo scenarios are deliberately NOT seeded.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

from dejavu import narrate
from dejavu.config import DATA_DIR, get_settings
from dejavu.log import setup_logging
from dejavu.memory import MemoryStore, MemoryUnavailable
from dejavu.world import World


async def seed(reset: bool, concurrency: int) -> int:
    settings = get_settings()
    store = MemoryStore(settings)
    incidents = json.loads((DATA_DIR / "incidents.json").read_text(encoding="utf-8"))
    deploys = json.loads((DATA_DIR / "deploys.json").read_text(encoding="utf-8"))
    deploys_by_id = {d["id"]: d for d in deploys}

    print(f"Hindsight: {settings.hindsight_base_url}  bank: {settings.hindsight_bank_id}")
    try:
        await store.ensure_bank(reset=reset)
    except MemoryUnavailable as exc:
        print(f"ERROR: could not set up the bank: {exc}")
        return 1
    print("bank ready (mission, disposition, directives, playbook mental model)")
    if reset:
        World().reset_live(reset_ids=True)  # memory was wiped, so live incident IDs can start over
        print("cleared live demo incidents (IDs restart at INC-047)")

    started = time.perf_counter()
    gate = asyncio.Semaphore(concurrency)
    failures: list[str] = []

    async def retain(label: str, items: list[dict], document_id: str | None) -> None:
        async with gate:
            t0 = time.perf_counter()
            try:
                await store.retain_batch(items, document_id=document_id)
                print(f"  retained {label:<10} {len(items):>2} items  ({time.perf_counter() - t0:.1f}s)")
            except MemoryUnavailable as exc:
                failures.append(label)
                print(f"  FAILED   {label:<10} {exc}")

    jobs = [retain(i["id"], narrate.incident_items(i, deploys_by_id), i["id"]) for i in incidents]
    deploy_items = [narrate.deploy_item(d) for d in deploys]
    jobs += [retain(f"deploys#{n // 10 + 1}", deploy_items[n:n + 10], None) for n in range(0, len(deploy_items), 10)]
    await asyncio.gather(*jobs)

    print(f"retained {len(incidents)} incidents and {len(deploys)} deploys in {time.perf_counter() - started:.0f}s"
          + (f" — {len(failures)} failed: {', '.join(failures)}" if failures else ""))
    await store.refresh_playbook()
    try:
        print("memory counts:", await store.stats(), "(observations keep consolidating in the background)")
    except MemoryUnavailable:
        pass
    await store.aclose()
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="delete and recreate the bank before seeding")
    parser.add_argument("--concurrency", type=int, default=4, help="parallel retain calls (default 4)")
    args = parser.parse_args()
    setup_logging("WARNING")
    return asyncio.run(seed(args.reset, args.concurrency))


if __name__ == "__main__":
    sys.exit(main())
