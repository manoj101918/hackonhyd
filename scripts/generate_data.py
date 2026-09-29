"""Generate Acme Commerce's synthetic incident history, deploy log and live demo scenarios.

Deterministic: the same seed always produces byte-identical JSON in `data/`.

    python scripts/generate_data.py            # writes data/*.json
    python scripts/generate_data.py --check    # fails if data/ is out of date

Recurring patterns are baked in on purpose so long-term memory has something to learn:
  * inventory-db connection-pool exhaustion hits three different services (INC-031, INC-038,
    INC-044). Restarting pods FAILED every time; capping pools / killing idle sessions WORKED.
  * Two payment-service PSP-client config changes preceded SEV1 outages (INC-033, INC-041).
  * Cache-TTL changes caused Redis eviction storms twice (INC-029, INC-042); flushing or
    restarting Redis made both worse.
  * Restarts are not always wrong: they WORKED for a stale JWKS cache (INC-028).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 42
ANCHOR = datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc)  # "today" for the synthetic history
DEJAVU_ADOPTED = ANCHOR - timedelta(days=54)  # Déjà Vu joined the on-call rotation here
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

ENGINEERS = [
    "Priya Raman", "Arjun Mehta", "Sneha Kulkarni", "Rahul Iyer", "Fatima Sheikh",
    "Karthik Reddy", "Ananya Das", "Vikram Singh", "Maria Gonzalez", "Tom Becker",
    "Aisha Okafor", "Kenji Watanabe", "Lucas Silva", "Emily Chen", "Olivia Novak",
]

SERVICES = {
    "checkout-api": "Java 21 / Spring Boot 3, HikariCP pool to inventory-db, 8-24 pods (HPA)",
    "payment-service": "Go 1.23, pgxpool to inventory-db, calls the PayFlow card-payments PSP",
    "inventory-db": "PostgreSQL 15 cluster (primary + 2 replicas), max_connections=400, hosts inventory, orders, accounts and payments databases",
    "auth-service": "Node.js 20 / Express, RS256 JWTs, sessions in redis-cache, accounts DB on inventory-db",
    "notification-worker": "Python 3.12 / Celery, SQLAlchemy, sends email + push via SMTP relay",
    "redis-cache": "Redis 7.2 with Sentinel, maxmemory 6gb, shared by checkout-api and auth-service",
    "api-gateway": "ingress-nginx in front of all public APIs at api.acme.shop",
}

# ---------------------------------------------------------------------------------------------
# Historical incident blueprints. `logs` lines are rendered with timestamps near the incident
# start; `{pod}`, `{req}`, `{ip}`, `{order}` are filled by the seeded RNG.
# steps: (action, outcome, minutes, note)
# agent: Déjà Vu's own suggestions (only after adoption): (suggestion, accepted, outcome, note)
# ---------------------------------------------------------------------------------------------
BLUEPRINTS: list[dict] = [
    {
        "days_ago": 89, "service": "api-gateway", "severity": "SEV2", "pattern": "gateway-keepalive",
        "title": "Intermittent 504s on /api/* after ingress-nginx upgrade",
        "alert": "api-gateway 5xx ratio 7.4% (threshold 2%) for 5m — mostly 504 Gateway Timeout on /api/checkout/*",
        "symptoms": ["504 Gateway Timeout on ~7% of /api/checkout requests", "checkout-api itself reports healthy p99 of 310ms", "errors cluster on connections idle for >20s"],
        "metrics": {"gateway_5xx_ratio": "7.4%", "checkout_api_p99_ms": 310, "upstream_connect_errors_per_min": 480},
        "logs": [
            '[error] 31#31: *{n} upstream timed out (110: Connection timed out) while reading response header from upstream, client: {ip}, server: api.acme.shop, request: "POST /api/checkout/confirm HTTP/2.0", upstream: "http://10.42.7.21:8080/checkout/confirm"',
            '[error] 29#29: *{n} upstream prematurely closed connection while reading response header from upstream, client: {ip}, server: api.acme.shop, request: "GET /api/checkout/cart HTTP/2.0"',
            '[warn] 31#31: *{n} upstream server temporarily disabled while reading response header from upstream',
        ],
        "trigger": {"kind": "infra", "minutes_before": 50, "version": "ingress-nginx 1.10.1",
                    "description": "Upgrade ingress-nginx controller 1.9.4 -> 1.10.1 on the prod cluster"},
        "steps": [
            ("Increase proxy-read-timeout on the ingress from 60s to 120s", "PARTIAL", 14, "504s dropped to ~3% but p99 latency rose to 40s"),
            ("Restart ingress-nginx controller pods", "FAILED", 9, "504s returned within 2 minutes of the restart"),
            ("Roll back ingress-nginx to 1.9.4", "WORKED", 18, "5xx back under 0.2% within 5 minutes of rollback"),
        ],
        "root_cause": "ingress-nginx 1.10 raised the default upstream keepalive timeout to 60s, longer than checkout-api's Tomcat keepAliveTimeout of 20s, so NGINX reused connections the backend had already closed.",
        "postmortem": "Upstream keepalive timeouts at the gateway must stay below every backend's server-side idle timeout. Action items: pin upstream-keepalive-timeout=15s, add an upgrade checklist for ingress defaults, canary ingress upgrades on one node pool first.",
    },
    {
        "days_ago": 85, "service": "auth-service", "severity": "SEV1", "pattern": "jwks-stale-cache",
        "title": "Login and API auth failures — JWT signature verification failed after key rotation",
        "alert": "auth-service 401 rate 46% (baseline 1.5%) — 'JWT signature verification failed' across all API consumers",
        "symptoms": ["Nearly half of authenticated API calls return 401", "Only tokens issued after 03:10 UTC fail", "Newly deployed pods verify tokens fine"],
        "metrics": {"auth_401_ratio": "46%", "login_success_rate": "52%"},
        "logs": [
            'ERROR [auth] JsonWebTokenError: JWT signature verification failed: invalid signature (kid="acme-2026-07") req={req}',
            'WARN  [jwks] kid "acme-2026-07" not found in cached JWKS (cache age 3480s, ttl 3600s) — falling back to cached keyset',
            'ERROR [middleware/verify] 401 Unauthorized path=/api/orders sub=user_{n} kid=acme-2026-07',
        ],
        "trigger": {"kind": "config", "minutes_before": 22, "version": "secret rotation 2026-07",
                    "description": "Scheduled rotation of the JWT signing key (new kid acme-2026-07) — signer switched to the new key immediately"},
        "steps": [
            ("Verify the new signing key secret is mounted correctly in auth-service", "PARTIAL", 11, "Secret was correct; confirmed only verifiers with old JWKS cache were failing"),
            ("Rolling restart of auth-service pods to flush the in-memory JWKS cache", "WORKED", 8, "401 rate back to baseline as soon as the rollout finished"),
        ],
        "root_cause": "Verifiers cache the JWKS for 1 hour. The rotation published the new key and started signing with it at the same moment, so verifiers with a warm cache rejected every new token until the cache expired.",
        "postmortem": "Key rotation must publish the new key at least one JWKS cache TTL before signing with it. In this case a restart was the correct fix because the fault was stale in-process state. Action items: overlap window in the rotation job, refetch JWKS on unknown kid.",
    },
    {
        "days_ago": 81, "service": "redis-cache", "severity": "SEV2", "pattern": "redis-eviction-ttl",
        "title": "Redis eviction storm after product-catalog cache TTL change — checkout p99 4.8s",
        "alert": "redis-cache evicted_keys 38k/s, used_memory at maxmemory (6gb); checkout-api p99 latency 4.8s",
        "symptoms": ["Redis at maxmemory with a massive eviction rate", "Catalog cache miss rate 71%", "inventory-db CPU 92% from cache-miss read load", "Some users logged out (session keys evicted)"],
        "metrics": {"evicted_keys_per_s": 38000, "used_memory": "5.99G/6.00G", "cache_miss_rate": "71%", "inventory_db_cpu": "92%"},
        "logs": [
            'WARN  c.a.checkout.cache.CatalogCache - cache miss rate 71% over 5m window (baseline 6%)',
            'ERROR c.a.checkout.cache.CatalogCache - io.lettuce.core.RedisCommandExecutionException: OOM command not allowed when used memory > \'maxmemory\'.',
            '# redis-cache INFO stats: evicted_keys:18294411 keyspace_misses:9120442 used_memory_human:5.99G maxmemory_policy:allkeys-lru',
        ],
        "trigger": {"kind": "config", "minutes_before": 185, "version": "checkout-api config r412",
                    "description": "checkout-api config: raise product-catalog cache TTL from 1h to 24h (catalog.cache.ttl=86400)"},
        "steps": [
            ("FLUSHDB the catalog keyspace on redis-cache to free memory", "FAILED", 12, "Thundering herd: inventory-db CPU hit 100% and checkout p99 went to 9s"),
            ("Revert catalog cache TTL to 1h", "PARTIAL", 20, "Memory pressure eased slowly as long-TTL keys aged out"),
            ("Raise maxmemory 6gb -> 10gb and switch maxmemory-policy to volatile-lru", "WORKED", 15, "Evictions stopped; sessions no longer evicted"),
        ],
        "root_cause": "A 24x longer catalog TTL grew the keyspace past maxmemory; with allkeys-lru Redis evicted hot catalog and session keys continuously, pushing reads onto inventory-db.",
        "postmortem": "Cache TTL changes are capacity changes. Never flush a hot cache during an incident (thundering herd). Action items: capacity estimate required for TTL changes, volatile-lru policy, memory alerts at 80%.",
    },
    {
        "days_ago": 77, "service": "notification-worker", "severity": "SEV3", "pattern": "worker-oom",
        "title": "notification-worker pods OOMKilled in a loop — order emails delayed 40 min",
        "alert": "notification-worker restarts > 10 in 15m (OOMKilled); email queue depth 84k",
        "symptoms": ["Pods restarting with exit code 137", "Order confirmation emails delayed ~40 minutes", "Started with the marketing campaign send"],
        "metrics": {"pod_restarts_15m": 23, "queue_depth": 84000, "memory_limit": "512Mi"},
        "logs": [
            'Last State: Terminated  Reason: OOMKilled  Exit Code: 137  (pod {pod})',
            'ERROR celery.worker.request: Task handler raised error: WorkerLostError(\'Worker exited prematurely: signal 9 (SIGKILL) Job: 412.\')',
            'INFO  notifications.campaign: rendering campaign "monsoon-sale" for batch of 50000 recipients',
        ],
        "steps": [
            ("Raise notification-worker memory limit 512Mi -> 1Gi", "PARTIAL", 16, "OOMs less frequent but still happening under the campaign batch"),
            ("Lower Celery --prefetch-multiplier from 16 to 1 and split campaign batches to 2k recipients", "WORKED", 22, "Memory flat at ~380Mi, queue drained in 25 min"),
        ],
        "root_cause": "Campaign tasks loaded a 50k-recipient template context each, and prefetch-multiplier 16 held many such tasks in memory per worker.",
        "postmortem": "Bulk sends must be chunked. Action items: batch size cap in the campaign API, prefetch 1 for heavy queues, separate queue for marketing sends.",
    },
    {
        "days_ago": 73, "service": "checkout-api", "severity": "SEV1", "pattern": "db-pool-exhaustion",
        "title": "checkout-api HTTP 500s — HikariCP pool exhausted, inventory-db out of connection slots",
        "alert": "checkout-api HTTP 5xx ratio 38% (threshold 2%) for 5m; p99 latency 30s",
        "symptoms": ["38% of checkout requests return HTTP 500", "Requests hang ~30s then fail", "inventory-db refuses new connections", "HPA had scaled checkout-api from 8 to 16 pods for the weekend sale"],
        "metrics": {"http_5xx_ratio": "38%", "p99_latency_ms": 30012, "pg_connections": "397/400", "idle_in_transaction": 182, "checkout_pods": 16},
        "logs": [
            'ERROR o.h.engine.jdbc.spi.SqlExceptionHelper - HikariPool-1 - Connection is not available, request timed out after 30000ms.',
            'ERROR c.a.checkout.api.OrderController - POST /checkout/confirm failed req={req}: org.springframework.jdbc.CannotGetJdbcConnectionException: Failed to obtain JDBC Connection',
            'FATAL:  remaining connection slots are reserved for non-replication superuser connections  (inventory-db, client {ip})',
            'WARN  com.zaxxer.hikari.pool.HikariPool - HikariPool-1 - Thread starvation or clock leap detected (housekeeper delta=58s)',
        ],
        "steps": [
            ("Restart checkout-api pods", "FAILED", 12, "HTTP 500s returned within 4 minutes as new pods refilled their pools"),
            ("Scale checkout-api from 16 to 24 replicas", "FAILED", 9, "Made it worse: every new pod opened 20 more connections against inventory-db"),
            ("Terminate idle-in-transaction sessions on inventory-db with pg_terminate_backend", "PARTIAL", 10, "Errors dropped for ~6 minutes, then came back"),
            ("Cap Hikari maximumPoolSize at 10 per pod and set idle_in_transaction_session_timeout=60s on inventory-db", "WORKED", 35, "Connections fell to 210/400 and 5xx cleared"),
        ],
        "root_cause": "Connection-pool exhaustion on inventory-db: HPA scale-out multiplied per-pod pools (16 pods x 20) past max_connections=400, while a reporting query path left sessions idle in transaction.",
        "postmortem": "Total pool size across all replicas must stay below inventory-db max_connections. Restarting or scaling out makes pool exhaustion worse. Action items: PgBouncer in transaction mode, pool caps tied to HPA max, idle_in_transaction_session_timeout on all databases.",
    },
    {
        "days_ago": 69, "service": "api-gateway", "severity": "SEV1", "pattern": "tls-expiry",
        "title": "TLS certificate for api.acme.shop expired — all clients failing TLS handshake",
        "alert": "Synthetic check: api.acme.shop TLS handshake failed (certificate has expired)",
        "symptoms": ["Browsers and mobile apps show certificate errors", "cert-manager renewal had been failing silently for 9 days"],
        "metrics": {"successful_handshakes": "0%"},
        "logs": [
            'cert-manager: Failed to finalize order: acme: authorization error for api.acme.shop: 403 urn:ietf:params:acme:error:unauthorized: Invalid response from http://api.acme.shop/.well-known/acme-challenge/...',
            'SSL_do_handshake() failed (SSL: error:0A000086:SSL routines::certificate verify failed) while SSL handshaking to upstream',
        ],
        "steps": [
            ("Trigger manual cert-manager renewal with the HTTP-01 solver", "FAILED", 10, "WAF rule still blocked /.well-known/acme-challenge"),
            ("Switch the issuer to DNS-01 and reissue the certificate", "WORKED", 21, "New certificate served; handshakes recovered"),
        ],
        "root_cause": "A new WAF rule blocked the /.well-known/acme-challenge path, so HTTP-01 renewals had been failing for 9 days until the certificate expired.",
        "postmortem": "Alert on certificate expiry < 14 days and on cert-manager order failures. Use DNS-01 for public endpoints behind the WAF.",
    },
    {
        "days_ago": 65, "service": "payment-service", "severity": "SEV1", "pattern": "payment-config-psp",
        "title": "Card payments failing — PayFlow authorization timeouts after client timeout config change",
        "alert": "payment-service authorize success rate 61% (baseline 97%); PayFlow 429 rate rising",
        "symptoms": ["39% of card authorizations fail", "Errors are client-side timeouts at exactly 2s", "Retry traffic triggered PayFlow rate limiting (HTTP 429)"],
        "metrics": {"authorize_success_rate": "61%", "payflow_p95_ms": 2400, "payflow_429_per_min": 1300},
        "logs": [
            'level=error msg="payflow authorize failed" order_id={order} err="context deadline exceeded (Client.Timeout exceeded while awaiting headers)" latency_ms=2001',
            'level=warn msg="retrying payflow request" attempt=2 max_attempts=3 order_id={order}',
            'level=error msg="payflow authorize failed" order_id={order} status=429 err="rate limit exceeded"',
        ],
        "trigger": {"kind": "config", "minutes_before": 40, "version": "payment-service config r88",
                    "description": "payment-service config: lower PayFlow HTTP client timeout from 8000ms to 2000ms to fail fast"},
        "steps": [
            ("Restart payment-service pods", "FAILED", 8, "No change; timeouts are config-driven"),
            ("Scale payment-service from 6 to 12 replicas", "FAILED", 10, "More concurrent retries; PayFlow 429s doubled"),
            ("Revert PayFlow client timeout to 8000ms", "WORKED", 12, "Authorize success back to 97% within 4 minutes"),
        ],
        "root_cause": "The new 2s client timeout was below PayFlow's peak p95 of 2.4s (3-D Secure flows). Timeouts plus 3 retries created a retry storm that got payment-service rate-limited by PayFlow.",
        "postmortem": "payment-service PSP client settings (timeouts, retries, connection pools) are high-risk changes: they must go through canary during off-peak hours with PayFlow latency percentiles checked first. Estimated lost GMV: Rs 38 lakh.",
    },
    {
        "days_ago": 61, "service": "inventory-db", "severity": "SEV2", "pattern": "wal-replication-slot",
        "title": "inventory-db disk at 97% — WAL growth from inactive replication slot",
        "alert": "inventory-db primary disk usage 97% (threshold 85%), growing 4GB/hour",
        "symptoms": ["pg_wal directory at 310GB", "Inactive logical replication slot analytics_cdc", "Analytics CDC connector down for 3 days"],
        "metrics": {"disk_used": "97%", "pg_wal_size_gb": 310},
        "logs": [
            'LOG:  checkpoints are occurring too frequently (24 seconds apart)',
            'WARNING:  replication slot "analytics_cdc" is inactive; restart_lsn 1F3/9A0000 is 312 GB behind',
        ],
        "steps": [
            ("Expand the primary volume from 500GB to 750GB", "PARTIAL", 18, "Bought time but WAL kept growing"),
            ("Drop the inactive replication slot analytics_cdc after confirming with the data team", "WORKED", 14, "WAL recycled; disk back to 58%"),
        ],
        "root_cause": "The analytics Debezium connector had been down for 3 days, so its logical replication slot pinned WAL on the primary.",
        "postmortem": "Alert on replication slot lag. Set max_slot_wal_keep_size=100GB so an abandoned slot can never fill the disk.",
    },
    {
        "days_ago": 57, "service": "auth-service", "severity": "SEV2", "pattern": "redis-nlb-idle",
        "title": "auth-service intermittent 502s — ECONNRESET to redis-cache after NLB migration",
        "alert": "auth-service 5xx ratio 4.1% — 'read ECONNRESET' from redis client",
        "symptoms": ["Failures on the first Redis command after a quiet period", "Worse overnight when traffic is low"],
        "metrics": {"auth_5xx_ratio": "4.1%"},
        "logs": [
            'ERROR [session-store] Error: read ECONNRESET at TCP.onStreamRead (node:internal/stream_base_commons:217:20) req={req}',
            'WARN  [ioredis] Reconnecting to redis-cache.acme.internal:6379 (attempt 1)',
        ],
        "trigger": {"kind": "infra", "minutes_before": 2900, "version": "infra PR #1182",
                    "description": "Move redis-cache behind an internal AWS NLB (350s idle timeout)"},
        "steps": [
            ("Restart auth-service pods", "PARTIAL", 9, "Fixed until connections sat idle again (~6 minutes later)"),
            ("Enable TCP keepAlive (30s) in the ioredis client config", "WORKED", 25, "No ECONNRESET for 24h"),
        ],
        "root_cause": "The NLB silently dropped idle TCP connections after 350s; ioredis had no keepalive, so the first command on a dead connection got ECONNRESET.",
        "postmortem": "Every client behind an NLB needs TCP keepalive below the idle timeout. Restarts only masked the problem.",
    },
    {
        "days_ago": 53, "service": "notification-worker", "severity": "SEV3", "pattern": "smtp-rate-limit",
        "title": "Email backlog of 120k — SMTP relay returning 421 rate-limit responses",
        "alert": "notification-worker queue depth 120k (threshold 10k); SMTP 421 responses rising",
        "symptoms": ["Email sends failing with SMTP 421", "Backlog growing during the flash sale"],
        "metrics": {"queue_depth": 120000, "smtp_421_per_min": 900},
        "logs": [
            'ERROR notifications.smtp: SMTPResponseException: (421, b\'4.7.0 Try again later, rate limit exceeded\')',
            'WARN  celery.app.trace: Task notifications.send_email[{req}] retry: Retry in 5s',
        ],
        "steps": [
            ("Scale notification-worker from 4 to 12 pods", "FAILED", 11, "More parallel sends; 421 responses tripled"),
            ("Apply Celery rate_limit=40/s on send_email with exponential backoff", "WORKED", 24, "Backlog drained in 50 minutes"),
        ],
        "agent": [("Check the SMTP relay's per-account rate limit and throttle sends instead of scaling out (no similar past incidents in memory)", True, "WORKED", "Engineer applied a Celery rate limit after scale-out failed")],
        "root_cause": "Sale traffic exceeded the SMTP relay account's 50 messages/s limit; retries without backoff amplified the load.",
        "postmortem": "Scaling out does not help when the bottleneck is an external rate limit. Action items: rate limit at the queue, request a higher relay quota before sales.",
    },
    {
        "days_ago": 49, "service": "redis-cache", "severity": "SEV2", "pattern": "redis-failover",
        "title": "redis-cache failover — clients stuck writing to demoted replica (READONLY errors)",
        "alert": "checkout-api and auth-service Redis errors 'READONLY You can't write against a read only replica'",
        "symptoms": ["Writes to Redis failing after Sentinel failover", "Reads still working"],
        "metrics": {"redis_write_errors_per_min": 5200},
        "logs": [
            'ERROR io.lettuce.core.RedisCommandExecutionException: READONLY You can\'t write against a read only replica.',
            '+switch-master acme-main 10.42.9.14 6379 10.42.9.31 6379',
        ],
        "steps": [
            ("Restart checkout-api pods", "PARTIAL", 10, "checkout-api recovered but auth-service still failing"),
            ("Point clients at Sentinel for master discovery instead of the static redis-cache service IP", "WORKED", 30, "Both services write to the new primary"),
        ],
        "agent": [("Restart application pods to drop stale Redis connections", True, "PARTIAL", "Helped checkout-api only; the real fix was Sentinel-aware clients")],
        "root_cause": "Clients connected to a static service endpoint that still pointed at the old primary after Sentinel promoted a replica.",
        "postmortem": "All Redis clients must use Sentinel discovery. Restarts are a band-aid for stale connections.",
    },
    {
        "days_ago": 45, "service": "notification-worker", "severity": "SEV2", "pattern": "db-pool-exhaustion",
        "title": "notification-worker failing — inventory-db 'remaining connection slots are reserved'",
        "alert": "notification-worker task failure rate 64%; checkout-api 5xx rising to 6% (shared inventory-db)",
        "symptoms": ["Celery tasks failing with psycopg2 OperationalError", "inventory-db at max_connections", "Celery autoscaler had grown workers from 4 to 20", "checkout-api also degraded"],
        "metrics": {"task_failure_rate": "64%", "pg_connections": "400/400", "celery_workers": 20},
        "logs": [
            'ERROR celery.app.trace: Task notifications.send_order_email[{req}] raised unexpected: OperationalError(\'(psycopg2.OperationalError) connection to server at "inventory-db.acme.internal" (10.42.5.10), port 5432 failed: FATAL:  remaining connection slots are reserved for non-replication superuser connections\')',
            'WARN  sqlalchemy.pool.impl.QueuePool: QueuePool limit of size 10 overflow 20 reached, connection timed out, timeout 30.00',
            'FATAL:  remaining connection slots are reserved for non-replication superuser connections  (inventory-db, client {ip})',
        ],
        "steps": [
            ("Restart notification-worker pods", "FAILED", 7, "Failures returned within 3 minutes once the autoscaler ramped workers up again"),
            ("Terminate sessions idle for >5 minutes on inventory-db (pg_terminate_backend)", "PARTIAL", 8, "Freed ~90 slots briefly"),
            ("Cap SQLAlchemy pool (pool_size=5, max_overflow=0) and Celery autoscale max at 8", "WORKED", 21, "Connections stable at 240/400, tasks succeeding"),
        ],
        "agent": [
            ("Matches INC-031 (inventory-db pool exhaustion). Do not restart pods — that failed in INC-031. Kill idle sessions and cap per-worker pool size.", True, "WORKED", "The engineer had restarted pods before reading the suggestion; the restart failed exactly as in INC-031"),
        ],
        "root_cause": "Connection-pool exhaustion on inventory-db: Celery autoscaling (4 -> 20 workers) with SQLAlchemy pool_size 10 + overflow 20 per worker exceeded max_connections=400.",
        "postmortem": "Second pool-exhaustion incident on inventory-db in a month (see INC-031). Any autoscaled consumer must have its worst-case connection count budgeted against max_connections. Restarting pods failed again.",
    },
    {
        "days_ago": 41, "service": "auth-service", "severity": "SEV2", "pattern": "bcrypt-cost",
        "title": "Login latency p99 9s and CPU 100% after bcrypt cost factor change",
        "alert": "auth-service /login p99 latency 9.2s (threshold 1s); CPU 100% on all pods",
        "symptoms": ["Login requests queueing", "CPU pinned; other endpoints fine when not co-located"],
        "metrics": {"login_p99_ms": 9200, "cpu": "100%"},
        "logs": [
            'WARN  [http] POST /login took 9184ms req={req}',
            'INFO  [password] hash cost=14 duration_ms=1180',
        ],
        "trigger": {"kind": "code", "minutes_before": 30, "version": "auth-service v3.8.0",
                    "description": "auth-service v3.8.0: raise bcrypt cost factor from 10 to 14 for password hashing"},
        "steps": [
            ("Scale auth-service from 6 to 12 pods", "PARTIAL", 12, "p99 improved to 4s but CPU still saturated"),
            ("Roll back auth-service to v3.7.2", "WORKED", 9, "Login p99 back to 180ms"),
        ],
        "agent": [("Deploy auth-service v3.8.0 landed 30 minutes before the alert and changes password hashing cost — roll it back first", True, "WORKED", "Rollback resolved it")],
        "root_cause": "bcrypt cost 14 is 16x more CPU per hash than cost 10; login traffic saturated every pod.",
        "postmortem": "Hashing cost changes need load testing and gradual rollout with rehash-on-login.",
    },
    {
        "days_ago": 37, "service": "inventory-db", "severity": "SEV2", "pattern": "missing-index",
        "title": "Slow order-history queries after migration dropped idx_orders_customer_created",
        "alert": "inventory-db slow query rate 340/min (>1s); checkout-api /orders p99 8.4s",
        "symptoms": ["Sequential scans on orders", "Active (not idle) connections waiting on IO", "Connection count high but below max_connections"],
        "metrics": {"slow_queries_per_min": 340, "pg_connections": "310/400", "orders_seq_scans_per_min": 290},
        "logs": [
            'LOG:  duration: 8423.117 ms  statement: SELECT id, total, status FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20',
            'ERROR c.a.checkout.api.OrderHistoryController - GET /orders timed out after 8000ms req={req}',
        ],
        "trigger": {"kind": "migration", "minutes_before": 95, "version": "checkout-api migration V212",
                    "description": "checkout-api migration V212: rebuild orders indexes (drops idx_orders_customer_created, recreated in V213 not yet deployed)"},
        "steps": [
            ("Route order-history reads to the read replica", "PARTIAL", 15, "Primary recovered, replica now slow"),
            ("CREATE INDEX CONCURRENTLY idx_orders_customer_created ON orders(customer_id, created_at DESC)", "WORKED", 26, "Query time back to 3ms"),
        ],
        "agent": [("Raise pool sizes — symptoms resemble INC-031/INC-038 pool exhaustion", False, "REJECTED", "Engineer rejected: pg_stat_activity showed active queries waiting on IO, not idle-in-transaction sessions. Lesson: check wait_event and seq scans before assuming pool exhaustion.")],
        "root_cause": "Migration V212 dropped the (customer_id, created_at) index; order-history queries fell back to sequential scans.",
        "postmortem": "High connection counts alone do not mean pool exhaustion. Déjà Vu's pool-size suggestion was wrong here; the distinguishing signal is active queries with IO waits and seq scans. Migrations must not drop an index before its replacement exists.",
    },
    {
        "days_ago": 33, "service": "payment-service", "severity": "SEV1", "pattern": "payment-config-psp",
        "title": "Payment authorizations failing — PayFlow TLS handshake timeouts after connection-pool config change",
        "alert": "payment-service authorize success rate 72%; p99 latency 6.1s during evening peak",
        "symptoms": ["TLS handshake timeouts to PayFlow", "New outbound TLS connections up 30x", "Started during peak evening traffic"],
        "metrics": {"authorize_success_rate": "72%", "p99_latency_ms": 6100, "new_tls_conns_per_s": 840},
        "logs": [
            'level=error msg="payflow authorize failed" order_id={order} err="net/http: TLS handshake timeout"',
            'level=error msg="payflow authorize failed" order_id={order} err="dial tcp 52.66.14.201:443: i/o timeout"',
            'level=warn msg="http transport stats" idle_conns=10 new_conns_per_s=840',
        ],
        "trigger": {"kind": "config", "minutes_before": 125, "version": "payment-service config r97",
                    "description": "payment-service config: reduce PayFlow http max_idle_conns_per_host 100 -> 10 and idle_conn_timeout 90s -> 10s to cut memory"},
        "steps": [
            ("Restart payment-service pods", "FAILED", 7, "No improvement"),
            ("Revert PayFlow HTTP transport config (max_idle_conns_per_host=100, idle_conn_timeout=90s)", "WORKED", 11, "Success rate back to 97%"),
        ],
        "agent": [("Matches INC-033: a payment-service PayFlow client config change preceded a SEV1. Revert config r97 first; restarts did not help in INC-033.", True, "WORKED", "Reverting the config resolved it in 11 minutes")],
        "root_cause": "With only 10 idle connections per host, peak traffic forced a new TLS handshake for most PayFlow calls, overwhelming the TLS handshake budget.",
        "postmortem": "Second SEV1 in 5 weeks caused by a payment-service PayFlow client config change (see INC-033). All payment-service PSP config changes now require a canary and an explicit risk review.",
    },
    {
        "days_ago": 29, "service": "redis-cache", "severity": "SEV2", "pattern": "redis-eviction-ttl",
        "title": "Users logged out en masse — redis-cache evicting sessions after session TTL change",
        "alert": "auth-service 'session not found' rate 31%; redis-cache evicted_keys 22k/s",
        "symptoms": ["Users randomly logged out", "Redis at maxmemory", "Session keyspace grew 9x in 2 days"],
        "metrics": {"evicted_keys_per_s": 22000, "used_memory": "6.00G/6.00G", "session_miss_rate": "31%"},
        "logs": [
            'WARN  [session-store] session not found for sid=s:{req} — forcing re-login',
            '# redis-cache INFO: used_memory_human:6.00G maxmemory_human:6.00G evicted_keys:40229118',
        ],
        "trigger": {"kind": "config", "minutes_before": 2700, "version": "auth-service config r54",
                    "description": "auth-service config: extend session TTL from 30m to 7d (remember-me by default)"},
        "steps": [
            ("Restart redis-cache", "FAILED", 9, "Cold cache: every session lost and inventory-db read load spiked"),
            ("Revert session TTL to 30m, set maxmemory-policy volatile-lru and raise maxmemory to 10gb", "WORKED", 18, "Evictions stopped within 10 minutes"),
        ],
        "agent": [("Matches INC-029: a cache TTL change caused a Redis eviction storm. Revert the TTL and raise maxmemory; do NOT flush or restart Redis (flush failed in INC-029).", False, "WORKED", "Engineer restarted Redis first (failed), then applied the suggestion, which worked")],
        "root_cause": "The 7-day session TTL grew the session keyspace 9x past maxmemory, evicting sessions and catalog keys.",
        "postmortem": "Second eviction storm from a TTL change (see INC-029). TTL changes on redis-cache now require a memory estimate. Restarting/flushing Redis failed again.",
    },
    {
        "days_ago": 24, "service": "api-gateway", "severity": "SEV2", "pattern": "rate-limit-nat",
        "title": "Mobile users receiving 429 Too Many Requests after gateway rate-limit deploy",
        "alert": "api-gateway 429 ratio 18% for mobile clients",
        "symptoms": ["429s concentrated on mobile carrier IP ranges", "Web traffic unaffected"],
        "metrics": {"mobile_429_ratio": "18%"},
        "logs": [
            '[error] 30#30: *{n} limiting requests, excess: 100.450 by zone "per_ip", client: {ip}, server: api.acme.shop, request: "GET /api/catalog/home HTTP/2.0"',
        ],
        "trigger": {"kind": "config", "minutes_before": 45, "version": "api-gateway config r203",
                    "description": "api-gateway: add global rate limit of 100 r/s per client IP for bot protection"},
        "steps": [
            ("Allowlist the top 3 mobile carrier ASNs", "PARTIAL", 14, "Helped Jio users, Airtel still limited"),
            ("Change the rate-limit key from client IP to authenticated user ID", "WORKED", 20, "429s back to baseline"),
        ],
        "agent": [("api-gateway config r203 deployed 45 minutes before the alert added per-IP limits; carrier-grade NAT puts many users behind one IP — revert or key by user", True, "WORKED", "Keyed by user ID")],
        "root_cause": "Per-IP rate limiting throttled mobile users behind carrier-grade NAT.",
        "postmortem": "Rate limits for authenticated traffic must be keyed by user or token, not IP.",
    },
    {
        "days_ago": 19, "service": "auth-service", "severity": "SEV1", "pattern": "db-pool-exhaustion",
        "title": "Login failures — auth-service pg pool timeouts, inventory-db out of connection slots",
        "alert": "auth-service login success rate 41%; 'timeout exceeded when trying to connect'",
        "symptoms": ["Logins failing after 10s", "inventory-db at max_connections", "auth-service HPA scaled from 6 to 20 pods after a marketing push notification"],
        "metrics": {"login_success_rate": "41%", "pg_connections": "400/400", "auth_pods": 20},
        "logs": [
            'ERROR [db] Error: timeout exceeded when trying to connect at /app/node_modules/pg-pool/index.js:45:11 req={req}',
            'FATAL:  remaining connection slots are reserved for non-replication superuser connections  (inventory-db, client {ip})',
            'ERROR [login] POST /login 503 — accounts lookup failed: sorry, too many clients already',
        ],
        "steps": [
            ("Restart auth-service pods", "FAILED", 6, "Pool timeouts returned in under 3 minutes"),
            ("Terminate idle sessions on inventory-db and cap pg Pool max from 25 to 10 per pod", "WORKED", 18, "Connections 230/400, login success back to 99%"),
            ("Route auth-service through PgBouncer (transaction mode)", "WORKED", 14, "Permanent fix; connection count independent of pod count"),
        ],
        "agent": [("Matches INC-031 and INC-038: inventory-db connection-pool exhaustion after scale-out. Restarting pods failed in both — skip it. Kill idle sessions and cap pool size per pod.", True, "WORKED", "On-call restarted pods before reading the analysis (failed); the recommended fix worked in 18 minutes")],
        "root_cause": "Connection-pool exhaustion on inventory-db: auth-service HPA scale-out (6 -> 20 pods) x pg Pool max 25 = 500 connections > max_connections=400.",
        "postmortem": "Third inventory-db pool-exhaustion incident (INC-031, INC-038). Restarting pods has now failed in all three. PgBouncer rollout to every service is the top reliability priority.",
    },
    {
        "days_ago": 12, "service": "checkout-api", "severity": "SEV2", "pattern": "jvm-oom",
        "title": "checkout-api pods OOMKilled after JVM heap flag change",
        "alert": "checkout-api pod restarts 14 in 10m (OOMKilled, exit code 137)",
        "symptoms": ["Pods killed by the kernel, not Java OutOfMemoryError", "Started right after a config deploy"],
        "metrics": {"pod_restarts_10m": 14, "container_limit": "3Gi", "xmx": "3g"},
        "logs": [
            'Last State: Terminated  Reason: OOMKilled  Exit Code: 137  (pod {pod})',
            'INFO  JVM flags: -Xmx3g -XX:+UseG1GC -XX:MaxDirectMemorySize=512m',
        ],
        "trigger": {"kind": "config", "minutes_before": 20, "version": "checkout-api config r430",
                    "description": "checkout-api: set -Xmx3g (container limit 3Gi) to reduce GC pauses"},
        "steps": [
            ("Replace -Xmx3g with -XX:MaxRAMPercentage=75 (revert config r430)", "WORKED", 16, "Restarts stopped"),
        ],
        "agent": [("checkout-api config r430 set heap equal to the container limit, leaving no room for metaspace and direct buffers — revert it", True, "WORKED", "Fixed in 16 minutes")],
        "root_cause": "Heap sized equal to the container memory limit; metaspace, thread stacks and direct buffers pushed the container over 3Gi.",
        "postmortem": "Size JVM heap as a percentage of the container limit, never equal to it.",
    },
    {
        "days_ago": 5, "service": "notification-worker", "severity": "SEV3", "pattern": "duplicate-delivery",
        "title": "Duplicate order-confirmation emails after Celery retry policy change",
        "alert": "Customer support tickets: duplicate order confirmation emails (x2-x4)",
        "symptoms": ["Same email delivered 2-4 times", "Only for tasks running longer than 5 minutes"],
        "metrics": {"duplicate_sends_per_hour": 1400},
        "logs": [
            'WARN  kombu.transport.SQS: Message {req} visibility timeout (300s) expired, redelivering',
            'INFO  notifications.email: sent order_confirmation order_id={order} (attempt 3)',
        ],
        "trigger": {"kind": "config", "minutes_before": 240, "version": "notification-worker config r61",
                    "description": "notification-worker: enable acks_late with SQS visibility_timeout 300s"},
        "steps": [
            ("Raise visibility_timeout to 3600s", "WORKED", 12, "Duplicates stopped"),
            ("Add per-order idempotency key to send_order_email", "WORKED", 22, "Defence in depth"),
        ],
        "agent": [("notification-worker config r61 (acks_late + 300s visibility timeout) went out 4h earlier; long tasks are being redelivered — raise the visibility timeout", True, "WORKED", "Resolved")],
        "root_cause": "acks_late with a 300s visibility timeout redelivered tasks that took longer than 5 minutes.",
        "postmortem": "Visibility timeout must exceed the longest task runtime; email sends need idempotency keys.",
    },
]

# Deploys that did not cause incidents (service, kind, version, description).
BENIGN_DEPLOYS = [
    ("checkout-api", "code", "checkout-api v2.24.0", "Add UPI Autopay as a checkout payment option"),
    ("checkout-api", "code", "checkout-api v2.26.1", "Fix rounding of GST in order summary"),
    ("checkout-api", "code", "checkout-api v2.28.0", "Wishlist price-drop banner on cart page"),
    ("payment-service", "code", "payment-service v1.41.0", "Structured logging for PayFlow webhooks"),
    ("payment-service", "code", "payment-service v1.43.2", "Add UPI intent flow for Android"),
    ("payment-service", "config", "payment-service config r92", "Rotate PayFlow webhook signing secret"),
    ("payment-service", "code", "payment-service v1.45.0", "Refund status polling job moved to a separate worker"),
    ("auth-service", "code", "auth-service v3.6.4", "Add OTP login via WhatsApp"),
    ("auth-service", "code", "auth-service v3.9.1", "Dependency bumps (express 4.21, jsonwebtoken 9.0.2)"),
    ("notification-worker", "code", "notification-worker v1.17.0", "Push notification templates for order shipped"),
    ("notification-worker", "code", "notification-worker v1.18.3", "Retry transient SMTP 451 errors"),
    ("inventory-db", "config", "inventory-db param group r19", "Enable pg_stat_statements track_io_timing"),
    ("inventory-db", "migration", "checkout-api migration V209", "Add column orders.gift_message"),
    ("redis-cache", "infra", "redis-cache 7.2.5", "Patch upgrade Redis 7.2.4 -> 7.2.5"),
    ("api-gateway", "config", "api-gateway config r198", "Add security headers (HSTS preload)"),
    ("api-gateway", "infra", "ingress-nginx 1.10.3", "Upgrade ingress-nginx 1.9.4 -> 1.10.3 with upstream-keepalive-timeout=15s"),
    ("checkout-api", "config", "checkout-api config r425", "Feature flag: enable express checkout for 10% of users"),
    ("auth-service", "config", "auth-service config r57", "Raise login rate limit from 5 to 8 attempts per minute"),
]

# ---------------------------------------------------------------------------------------------
# Live demo scenarios — deliberately NOT seeded into memory. Log `offset_s` is relative to the
# moment the scenario starts; deploy `hours_ago` likewise.
# ---------------------------------------------------------------------------------------------
SCENARIOS = [
    {
        "id": "s1-checkout-500s",
        "incident_id": "INC-047",
        "kind": "incident",
        "title": "checkout-api throwing HTTP 500s during the weekend flash sale",
        "service": "checkout-api",
        "severity": "SEV1",
        "alert": "checkout-api HTTP 5xx ratio 31% (threshold 2%) for 5m; p99 latency 29.8s",
        "symptoms": ["31% of POST /checkout/confirm requests return HTTP 500", "Requests hang ~30s before failing", "HPA scaled checkout-api from 10 to 22 pods 15 minutes ago for the flash sale"],
        "metrics": {"http_5xx_ratio": "31%", "p99_latency_ms": 29800, "checkout_pods": 22, "pg_connections": "398/400"},
        "logs": {
            "checkout-api": [
                (-900, "INFO  HorizontalPodAutoscaler checkout-api: scaled from 10 to 22 replicas (cpu 84% > target 60%)"),
                (-420, "WARN  com.zaxxer.hikari.pool.HikariPool - HikariPool-1 - Pool stats (total=20, active=20, idle=0, waiting=57)"),
                (-300, "ERROR o.h.engine.jdbc.spi.SqlExceptionHelper - HikariPool-1 - Connection is not available, request timed out after 30000ms."),
                (-240, "ERROR c.a.checkout.api.OrderController - POST /checkout/confirm failed req=7f3a9c21: org.springframework.jdbc.CannotGetJdbcConnectionException: Failed to obtain JDBC Connection"),
                (-180, "ERROR o.h.engine.jdbc.spi.SqlExceptionHelper - HikariPool-1 - Connection is not available, request timed out after 30000ms."),
                (-60, "ERROR c.a.checkout.api.OrderController - POST /checkout/confirm failed req=b81e04d7: CannotGetJdbcConnectionException: HikariPool-1 - Connection is not available"),
            ],
            "inventory-db": [
                (-330, "FATAL:  remaining connection slots are reserved for non-replication superuser connections  (client 10.42.6.18)"),
                (-200, "FATAL:  remaining connection slots are reserved for non-replication superuser connections  (client 10.42.6.44)"),
                (-120, "LOG:  pg_stat_activity snapshot: total=398 active=121 idle=69 'idle in transaction'=208 (max_connections=400)"),
            ],
        },
        "deploys": [
            {"service": "checkout-api", "kind": "code", "version": "checkout-api v2.31.0", "description": "Wishlist price-drop banner on product page", "hours_ago": 26},
            {"service": "api-gateway", "kind": "config", "version": "api-gateway config r211", "description": "Increase access log retention to 14 days", "hours_ago": 5},
            {"service": "notification-worker", "kind": "code", "version": "notification-worker v1.19.2", "description": "Localised SMS templates (Hindi, Telugu)", "hours_ago": 3},
        ],
        "resolution": {
            "root_cause": "inventory-db connection-pool exhaustion: HPA scale-out (10 -> 22 pods) x Hikari pool 20 exceeded max_connections=400, with ~200 sessions idle in transaction.",
            "worked": ["Terminate idle-in-transaction sessions on inventory-db", "Cap Hikari maximumPoolSize at 10 per pod and set idle_in_transaction_session_timeout=60s"],
            "failed": ["Restart checkout-api pods", "Scale out checkout-api"],
            "ttr_minutes_expected": 18,
        },
    },
    {
        "id": "s2-payment-pool",
        "incident_id": "INC-048",
        "kind": "incident",
        "title": "payment-service failing to confirm payments — database connection errors",
        "service": "payment-service",
        "severity": "SEV1",
        "alert": "payment-service /payments/confirm error rate 27%; 'pgxpool: acquire: context deadline exceeded'",
        "symptoms": ["27% of payment confirmations fail", "Card authorisations at PayFlow succeed but the result cannot be written", "Started ~40 minutes after a payment-service config deploy"],
        "metrics": {"confirm_error_rate": "27%", "pg_connections": "400/400", "payment_pods": 12},
        "logs": {
            "payment-service": [
                (-600, 'level=info msg="pgxpool config loaded" max_conns=60 min_conns=20 pods=12'),
                (-360, 'level=error msg="confirm payment failed" order_id=ORD-88412093 err="pgxpool: acquire: context deadline exceeded"'),
                (-250, 'level=error msg="confirm payment failed" order_id=ORD-88412311 err="failed to connect to `host=inventory-db.acme.internal user=payments database=payments`: server error (FATAL: remaining connection slots are reserved for non-replication superuser connections (SQLSTATE 53300))"'),
                (-90, 'level=error msg="confirm payment failed" order_id=ORD-88412570 err="pgxpool: acquire: context deadline exceeded"'),
            ],
            "inventory-db": [
                (-280, "FATAL:  remaining connection slots are reserved for non-replication superuser connections  (client 10.42.8.12)"),
                (-100, "LOG:  pg_stat_activity snapshot: total=400 by_user payments=246 checkout=98 notifications=56 (max_connections=400)"),
            ],
        },
        "deploys": [
            {"service": "payment-service", "kind": "config", "version": "payment-service config r104", "description": "Raise pgxpool max_conns from 20 to 60 and min_conns to 20 per pod ahead of the sale", "hours_ago": 0.75},
            {"service": "checkout-api", "kind": "code", "version": "checkout-api v2.31.1", "description": "Fix typo in order confirmation page", "hours_ago": 8},
        ],
        "resolution": {
            "root_cause": "inventory-db connection-pool exhaustion: payment-service config r104 raised pgxpool max_conns to 60 x 12 pods, crowding out other services on max_connections=400.",
            "worked": ["Revert payment-service config r104 (max_conns back to 20)", "Terminate idle payments sessions on inventory-db"],
            "failed": ["Restart payment-service pods"],
            "ttr_minutes_expected": 12,
        },
    },
    {
        "id": "s3-deploy-check",
        "incident_id": None,
        "kind": "deploy_check",
        "title": "Deploy check: payment-service PayFlow client tuning before the sale",
        "service": "payment-service",
        "severity": None,
        "planned_change": "payment-service config: lower the PayFlow HTTP client timeout from 8000ms to 2500ms and reduce max_idle_conns_per_host from 100 to 20 to cut memory before the Diwali sale.",
        "resolution": {
            "expected_risk": "high",
            "evidence": ["INC-033", "INC-041"],
            "reason": "Both previous PayFlow client config changes on payment-service preceded SEV1 outages.",
        },
    },
]

BASELINE_LOGS = {
    "checkout-api": ["INFO  c.a.checkout.api.OrderController - POST /checkout/confirm 200 in 142ms", "INFO  com.zaxxer.hikari.pool.HikariPool - HikariPool-1 - Pool stats (total=10, active=3, idle=7, waiting=0)"],
    "payment-service": ['level=info msg="payflow authorize ok" latency_ms=640', 'level=info msg="confirm payment ok" latency_ms=18'],
    "inventory-db": ["LOG:  checkpoint complete: wrote 1822 buffers (1.4%)", "LOG:  pg_stat_activity snapshot: total=164 active=38 idle=126 (max_connections=400)"],
    "auth-service": ["INFO  [http] POST /login 200 184ms", "INFO  [jwks] refreshed keyset (2 keys)"],
    "notification-worker": ["INFO  celery.worker: Task notifications.send_order_email succeeded in 0.41s", "INFO  celery.worker: queue depth 112"],
    "redis-cache": ["# INFO: used_memory_human:3.12G maxmemory_human:10.00G evicted_keys:0", "# INFO: connected_clients:412 instantaneous_ops_per_sec:18422"],
    "api-gateway": ['[info] 200 GET /api/catalog/home 38ms', '[info] 200 POST /api/checkout/confirm 162ms'],
}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Filler:
    """Seeded fill-ins for log templates (pod names, request ids, IPs)."""

    def __init__(self, rng: random.Random):
        self.rng = rng

    def hexid(self, n: int) -> str:
        return "".join(self.rng.choice("0123456789abcdef") for _ in range(n))

    def fill(self, template: str, service: str) -> str:
        suffix = "".join(self.rng.choice("bcdfghjklmnpqrstvwxz2456789") for _ in range(5))
        return template.format(
            pod=f"{service}-{self.hexid(9)}-{suffix}",
            req=self.hexid(8),
            ip=f"10.42.{self.rng.randint(1, 12)}.{self.rng.randint(2, 250)}",
            order=f"ORD-{self.rng.randint(80000000, 88000000)}",
            n=self.rng.randint(1000, 99999),
        )


def build(seed: int = SEED) -> tuple[list[dict], list[dict], dict]:
    rng = random.Random(seed)
    filler = Filler(rng)
    engineers = ENGINEERS[:]

    raw_deploys: list[dict] = []
    incidents: list[dict] = []

    for bp in sorted(BLUEPRINTS, key=lambda b: -b["days_ago"]):
        start = (ANCHOR - timedelta(days=bp["days_ago"])).replace(hour=rng.randint(3, 17), minute=rng.randint(0, 59))
        detect = rng.randint(2, 7)
        commander, *responders = rng.sample(engineers, 3)
        assisted = start >= DEJAVU_ADOPTED
        # Time spent diagnosing before the first remediation step. Without memory, on-call
        # starts from zero; with Déjà Vu the matching history arrives with the alert.
        triage = rng.randint(4, 12) if assisted else rng.randint(25, 55)

        clock = start + timedelta(minutes=detect + triage)
        steps = []
        for action, outcome, minutes, note in bp["steps"]:
            clock += timedelta(minutes=minutes)
            steps.append({"action": action, "outcome": outcome, "minutes": minutes, "notes": note,
                          "by": rng.choice([commander, *responders]), "at": _iso(clock)})
        ttr = int((clock - start).total_seconds() // 60)

        logs = []
        for i, template in enumerate(bp["logs"]):
            ts = start + timedelta(seconds=30 + i * rng.randint(20, 90))
            logs.append(f"{_iso(ts)} {filler.fill(template, bp['service'])}")

        incident = {
            "id": None,  # assigned below in chronological order
            "title": bp["title"],
            "service": bp["service"],
            "severity": bp["severity"],
            "pattern": bp["pattern"],
            "started_at": _iso(start),
            "resolved_at": _iso(clock),
            "ttr_minutes": ttr,
            "triage_minutes": triage,
            "commander": commander,
            "responders": responders,
            "alert": bp["alert"],
            "symptoms": bp["symptoms"],
            "metrics": bp["metrics"],
            "logs": logs,
            "steps": steps,
            "root_cause": bp["root_cause"],
            "postmortem": bp["postmortem"],
            "trigger_deploy_id": None,
            "agent_suggestions": [
                {"suggestion": s, "accepted": acc, "outcome": out, "notes": note}
                for s, acc, out, note in bp.get("agent", [])
            ],
            "dejavu_assisted": assisted,
        }
        incidents.append(incident)

        if trig := bp.get("trigger"):
            raw_deploys.append({
                "service": bp["service"] if trig["kind"] != "migration" else "inventory-db",
                "kind": trig["kind"],
                "version": trig["version"],
                "description": trig["description"],
                "author": rng.choice(engineers),
                "deployed_at": start - timedelta(minutes=trig["minutes_before"]),
                "_incident": incident,
            })

    for service, kind, version, description in BENIGN_DEPLOYS:
        at = ANCHOR - timedelta(days=rng.randint(2, 89), hours=rng.randint(0, 20), minutes=rng.randint(0, 59))
        raw_deploys.append({"service": service, "kind": kind, "version": version, "description": description,
                            "author": rng.choice(engineers), "deployed_at": at, "_incident": None})

    for n, incident in enumerate(incidents, start=27):
        incident["id"] = f"INC-{n:03d}"
    # Agent suggestions and postmortems cite earlier incidents by ID; keep them honest.
    by_pattern = lambda p: [i["id"] for i in incidents if i["pattern"] == p]  # noqa: E731
    assert by_pattern("db-pool-exhaustion") == ["INC-031", "INC-038", "INC-044"]
    assert by_pattern("payment-config-psp") == ["INC-033", "INC-041"]
    assert by_pattern("redis-eviction-ttl") == ["INC-029", "INC-042"]

    deploys = []
    for n, d in enumerate(sorted(raw_deploys, key=lambda d: d["deployed_at"]), start=2201):
        dep_id = f"DEP-{n}"
        linked = d.pop("_incident")
        if linked is not None:
            linked["trigger_deploy_id"] = dep_id
        deploys.append({"id": dep_id, **d, "deployed_at": _iso(d["deployed_at"]),
                        "linked_incident_id": linked["id"] if linked else None})

    scenarios = {
        "services": SERVICES,
        "baseline_logs": BASELINE_LOGS,
        "scenarios": [
            {**s, "logs": {svc: [{"offset_s": o, "line": line} for o, line in lines] for svc, lines in s.get("logs", {}).items()}}
            for s in SCENARIOS
        ],
    }
    return incidents, deploys, scenarios


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if data/ differs from generated output")
    args = parser.parse_args()

    incidents, deploys, scenarios = build()
    outputs = {"incidents.json": _dump(incidents), "deploys.json": _dump(deploys), "scenarios.json": _dump(scenarios)}

    if args.check:
        stale = [name for name, text in outputs.items()
                 if not (DATA_DIR / name).exists() or (DATA_DIR / name).read_text(encoding="utf-8") != text]
        if stale:
            print(f"out of date: {', '.join(stale)} — run scripts/generate_data.py")
            return 1
        print("data/ is up to date")
        return 0

    DATA_DIR.mkdir(exist_ok=True)
    for name, text in outputs.items():
        (DATA_DIR / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(incidents)} incidents, {len(deploys)} deploys, {len(scenarios['scenarios'])} scenarios to {DATA_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
