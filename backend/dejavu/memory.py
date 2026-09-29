"""Thin async wrapper around the Hindsight client.

Responsibilities:
  * convert Hindsight results into `MemoryHit`s the UI can render (type badge, incident IDs, date)
  * enforce per-operation timeouts
  * degrade gracefully: any failure flips `status.available` to False and raises
    `MemoryUnavailable`, which the agent turns into "no memory" mode plus a UI banner
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable
from datetime import datetime
from typing import Any, TypeVar

from hindsight_client import Hindsight

from . import bank
from .config import Settings
from .log import get_logger, kv
from .narrate import RetainItem
from .schemas import INCIDENT_ID_RE, MemoryHit, MemoryStatus, ReflectResult

log = get_logger("memory")
T = TypeVar("T")

ALL_FACT_TYPES = ["world", "experience", "observation"]

LEARNED_QUESTIONS = [
    ("Fixes that keep failing", "Which remediation steps repeatedly failed, and for which root cause?"),
    ("Fixes that work", "Which remediation steps reliably worked, and for which root cause?"),
    ("Risky changes", "Which deploys or config changes preceded outages, on which services?"),
    ("Where Déjà Vu was wrong", "When were Déjà Vu's own recommendations wrong or not followed, and what was learned?"),
]


class MemoryUnavailable(RuntimeError):
    """Hindsight could not be reached (or rejected the request)."""


def _incident_ids(*sources: Any) -> list[str]:
    ids: list[str] = []
    for src in sources:
        for match in INCIDENT_ID_RE.findall(str(src or "")):
            if match not in ids:
                ids.append(match)
    return ids


def _date(*candidates: str | None) -> str | None:
    for c in candidates:
        if c:
            return str(c)[:10]
    return None


_SUFFIX_RE = re.compile(r"\s*\|\s*(When|Involving):.*$", re.DOTALL)


def clean_text(text: str) -> str:
    """Hindsight appends ' | When: ... | Involving: ...' to fact text; dates/entities are shown separately."""
    return _SUFFIX_RE.sub("", text or "").strip()


def hit_from_result(r: Any, source: str = "recall") -> MemoryHit:
    """Build a MemoryHit from a RecallResult / ReflectFact / MemoryUnitListItem (duck-typed)."""
    meta = getattr(r, "metadata", None) or {}
    scores = getattr(r, "scores", None)
    return MemoryHit(
        id=str(getattr(r, "id", None) or ""),
        text=clean_text(getattr(r, "text", "")),
        type=getattr(r, "type", None) or getattr(r, "fact_type", None),
        incident_ids=_incident_ids(meta.get("incident_id"), getattr(r, "document_id", None), getattr(r, "text", "")),
        date=_date(getattr(r, "occurred_start", None), getattr(r, "var_date", None), getattr(r, "mentioned_at", None)),
        context=getattr(r, "context", None),
        score=float(scores.final) if scores is not None and getattr(scores, "final", None) is not None else None,
        proof_count=getattr(r, "proof_count", None),
        source=source,
    )


class MemoryStore:
    def __init__(self, settings: Settings, client: Hindsight | None = None):
        self.settings = settings
        self.bank_id = settings.hindsight_bank_id
        self._client = client
        self._status = MemoryStatus(available=client is not None, bank_id=self.bank_id,
                                    base_url=settings.hindsight_base_url)
        self._last_probe = 0.0
        if client is None:
            self._connect()

    # ------------------------------------------------------------------ plumbing

    def _connect(self) -> None:
        s = self.settings
        if "vectorize.io" in s.hindsight_base_url and not s.hindsight_api_key:
            self._mark_down("HINDSIGHT_API_KEY is not set")
            return
        self._client = Hindsight(base_url=s.hindsight_base_url, api_key=s.hindsight_api_key or None,
                                 timeout=s.hindsight_timeout_s)
        self._status.available = True

    @property
    def status(self) -> MemoryStatus:
        return self._status.model_copy()

    def _mark_down(self, reason: str) -> None:
        if self._status.available or self._status.reason != reason:
            log.warning("memory.unavailable", extra=kv(reason=reason))
        self._status.available = False
        self._status.reason = reason

    async def _call(self, op: str, coro: Awaitable[T], timeout: float) -> T:
        if self._client is None:
            raise MemoryUnavailable(self._status.reason or "Hindsight client not configured")
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._mark_down(f"{op} timed out after {timeout:.0f}s")
            raise MemoryUnavailable(self._status.reason) from exc
        except Exception as exc:  # network errors, 4xx/5xx from the API
            self._mark_down(f"{op} failed: {type(exc).__name__}: {str(exc)[:200]}")
            raise MemoryUnavailable(self._status.reason) from exc
        self._status.available, self._status.reason = True, None
        log.info(f"memory.{op}", extra=kv(bank=self.bank_id, ms=int((time.perf_counter() - started) * 1000)))
        return result

    async def probe(self, max_age_s: float = 30.0) -> bool:
        """Cheap health check (cached for `max_age_s`). Returns current availability."""
        if self._client is None:
            return False
        if time.monotonic() - self._last_probe < max_age_s:
            return self._status.available
        self._last_probe = time.monotonic()
        try:
            await self._call("probe", self._client.aget_bank_config(self.bank_id), timeout=8)
        except MemoryUnavailable:
            return False
        return True

    # ------------------------------------------------------------------ bank setup

    async def ensure_bank(self, reset: bool = False) -> None:
        """Create/update the bank, its disposition, directives and mental models (idempotent)."""
        c = self._client
        if c is None:
            raise MemoryUnavailable(self._status.reason or "Hindsight client not configured")
        t = self.settings.hindsight_timeout_s
        if reset:
            try:
                await self._call("delete_bank", c.adelete_bank(self.bank_id), timeout=t)
            except MemoryUnavailable:
                log.info("memory.delete_bank.skipped", extra=kv(reason="bank did not exist"))
        await self._call("create_bank", c.acreate_bank(
            self.bank_id,
            name="Acme Commerce on-call memory",
            reflect_mission=bank.REFLECT_MISSION,
            retain_mission=bank.RETAIN_MISSION,
            enable_observations=True,
            observations_mission=bank.OBSERVATIONS_MISSION,
            background="Acme Commerce runs checkout-api, payment-service, inventory-db (Postgres), auth-service, "
                       "notification-worker, redis-cache and api-gateway on Kubernetes.",
        ), timeout=t)
        await self._call("update_bank_config", c.aupdate_bank_config(self.bank_id, **bank.DISPOSITION), timeout=t)

        existing = await self._call("list_directives", c.alist_directives(self.bank_id), timeout=t)
        existing_names = {d.name for d in getattr(existing, "items", None) or []}
        for d in bank.DIRECTIVES:
            if d["name"] not in existing_names:
                await self._call("create_directive", c.acreate_directive(self.bank_id, **d), timeout=t)

        models = await self._call("list_mental_models", c.alist_mental_models(self.bank_id, detail="metadata"), timeout=t)
        existing_models = {m.id for m in getattr(models, "items", None) or []}
        for m in bank.MENTAL_MODELS:
            if m["id"] not in existing_models:
                await self._call("create_mental_model", c.acreate_mental_model(self.bank_id, **m), timeout=t)

    # ------------------------------------------------------------------ core operations

    async def recall(self, query: str, *, types: list[str] | None = None, tags: list[str] | None = None,
                     budget: str = "mid", max_tokens: int = 2048) -> list[MemoryHit]:
        res = await self._call("recall", self._client.arecall(
            bank_id=self.bank_id, query=query, types=types or ALL_FACT_TYPES, budget=budget,
            max_tokens=max_tokens, tags=tags, tags_match="any",
        ), timeout=self.settings.recall_timeout_s)
        hits = [hit_from_result(r) for r in res.results]
        log.info("memory.recall.hits", extra=kv(query=query[:80], hits=len(hits)))
        return hits

    async def reflect(self, query: str, *, context: str | None = None, budget: str = "low",
                      response_schema: dict | None = None, tags: list[str] | None = None) -> ReflectResult:
        res = await self._call("reflect", self._client.areflect(
            bank_id=self.bank_id, query=query, budget=budget, context=context,
            response_schema=response_schema, tags=tags, include_facts=True,
        ), timeout=self.settings.reflect_timeout_s)
        based_on = getattr(res, "based_on", None)
        evidence = [hit_from_result(f, source="reflect") for f in (getattr(based_on, "memories", None) or [])]
        return ReflectResult(text=res.text or "", structured=res.structured_output, evidence=evidence)

    async def retain(self, item: RetainItem, *, update_mode: str | None = "append") -> None:
        """Retain one narrated item synchronously so it is recallable as soon as this returns."""
        await self._call("retain", self._client.aretain(
            bank_id=self.bank_id,
            content=item["content"],
            context=item.get("context"),
            timestamp=item.get("timestamp"),
            document_id=item.get("document_id"),
            metadata=item.get("metadata"),
            tags=item.get("tags"),
            update_mode=update_mode if item.get("document_id") else None,
        ), timeout=self.settings.retain_timeout_s)

    async def retain_batch(self, items: list[RetainItem], *, document_id: str | None = None,
                           retain_async: bool = False) -> None:
        await self._call("retain_batch", self._client.aretain_batch(
            bank_id=self.bank_id, items=items, document_id=document_id, retain_async=retain_async,
        ), timeout=max(self.settings.retain_timeout_s, 30 + 10 * len(items)))

    async def observations(self, limit: int = 50) -> list[MemoryHit]:
        res = await self._call("list_observations", self._client.alist_memories(
            bank_id=self.bank_id, type="observation", limit=limit,
        ), timeout=self.settings.hindsight_timeout_s)
        return [hit_from_result(m, source="list") for m in res.items]

    async def learned(self) -> list[dict]:
        """Cross-incident observations, grouped by what kind of lesson they are."""
        results = await asyncio.gather(*(
            self.recall(q, types=["observation"], budget="low", max_tokens=1500) for _, q in LEARNED_QUESTIONS
        ))
        seen: set[str] = set()
        groups = []
        for (title, _), hits in zip(LEARNED_QUESTIONS, results):
            fresh = [h for h in hits if h.text not in seen]
            fresh.sort(key=lambda h: len(h.incident_ids), reverse=True)  # patterns seen across incidents first
            fresh = fresh[:6]
            seen.update(h.text for h in fresh)
            groups.append({"title": title, "observations": [h.model_dump() for h in fresh]})
        return groups

    async def playbook(self) -> dict | None:
        """The auto-refreshing 'remediation playbook' mental model, if it has been built yet."""
        try:
            m = await self._call("get_mental_model", self._client.aget_mental_model(
                self.bank_id, bank.PLAYBOOK_MODEL_ID, detail="content",
            ), timeout=self.settings.hindsight_timeout_s)
        except MemoryUnavailable:
            return None
        content = getattr(m, "content", None)
        updated = getattr(m, "last_refreshed_at", None) or getattr(m, "updated_at", None)
        return {"name": getattr(m, "name", "Remediation playbook"), "content": content or "",
                "updated_at": updated.isoformat() if isinstance(updated, datetime) else updated}

    async def refresh_playbook(self) -> None:
        try:
            await self._call("refresh_mental_model", self._client.arefresh_mental_model(
                self.bank_id, bank.PLAYBOOK_MODEL_ID), timeout=self.settings.hindsight_timeout_s)
        except MemoryUnavailable:
            pass

    async def stats(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for t in ALL_FACT_TYPES:
            res = await self._call(f"count_{t}", self._client.alist_memories(bank_id=self.bank_id, type=t, limit=1),
                                   timeout=self.settings.hindsight_timeout_s)
            counts[t] = res.total
        return counts

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # closing is best-effort
                pass
