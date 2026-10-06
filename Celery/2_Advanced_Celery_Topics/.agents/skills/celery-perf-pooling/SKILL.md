---
name: celery-perf-pooling
description: >-
  Configure and optimize high-performance resource management, database connection
  pool budgeting, PgBouncer multiplexing, L1/L2 caching, index optimization, and
  PostgreSQL engine tuning for Celery and FastAPI. Use this skill when managing database
  connections, client pooling, process lifecycle warm-up, caching, or query performance.
---

# High-Performance Resource Management, Pooling & Database Tuning

This skill defines the technical standards, architectural patterns, and configurations required to achieve sub-25ms P99 latency, zero connection starvation, and strict ACID financial durability in distributed FastAPI and Celery systems.

---

## 1. High-Performance Resource Management & Pooling Invariants

### A. Eager Singleton Initialization at Module Load
* **Rationale**: Lazy initialization of clients, database engines, or thread pools creates severe cold-start / first-call latency spikes, causing unpredictable P99 latency in production.
* **Standard**: Initialize all shared client singletons, SQLAlchemy database engines (`_engine`), session factories (`_session_factory`), and thread pool singletons (`_sync_executor`) eagerly at module load time.
* **Invariant**: Never defer client or engine creation to the first request or transaction handler.

### B. Shared Client Connection Factories & Persistent Keep-Alive Sockets
* **Rationale**: Opening and closing ephemeral HTTP sockets per task or request causes rapid TCP port exhaustion and socket pileup in the OS `TIME_WAIT` state.
* **Standard**: Outgoing network clients (e.g., `BankSimulatorClient`, payment gateway adapters) must share a process-level client instance configured with explicit connection pooling:
  ```python
  import httpx

  SHARED_LIMITS = httpx.Limits(
      max_keepalive_connections=20,
      max_connections=50,
      keepalive_expiry=30.0,
  )

  _shared_client = httpx.AsyncClient(
      limits=SHARED_LIMITS,
      timeout=httpx.Timeout(10.0, connect=5.0),
  )
  ```
* **Invariant**: Tasks reuse persistent TCP keep-alive connections rather than tearing down connections per invocation.

### C. Role-Based Database Connection Pool Budgeting
* **Rationale**: Celery prefork worker pools spawn separate single-threaded child processes. If each of $N$ worker processes uses a default pool of 20–30 connections, PostgreSQL's `max_connections` ceiling is quickly exhausted ($N \times 30 \gg 100$), leading to fatal connection rejections.
* **Budgeting Standard**:
  - **Headless Worker Child Processes**: Single-threaded child processes execute strictly one task at a time and must be budgeted with minimal, dedicated pools:
    ```python
    # services/worker/db.py
    engine = create_async_engine(
        DATABASE_URL,
        pool_size=2,
        max_overflow=2,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    ```
  - **API Gateway (FastAPI)**: Asynchronous event loop serving concurrent HTTP requests allocates higher capacity:
    ```python
    # app/db.py
    engine = create_async_engine(
        DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    ```
* **Invariant**: Budget total connections across API and all worker pods such that $\sum (\text{pool\_size} + \text{max\_overflow}) < \text{PostgreSQL max\_connections}$.

### D. Connection Multiplexing (PgBouncer Invariant)
* **Rationale**: Decouples application concurrency from PostgreSQL backend connection limits.
* **Standard**: Deploy PgBouncer in transaction pooling mode (`POOL_MODE=transaction`).
* **asyncpg Requirement**: Because transaction pooling does not guarantee the same physical backend connection across successive transactions, prepared statement caches collide. Always configure `connect_args={"statement_cache_size": 0}` in SQLAlchemy asyncpg:
  ```python
  engine = create_async_engine(
      DATABASE_URL,
      connect_args={"statement_cache_size": 0},
      pool_size=...,
  )
  ```

### E. Multi-Tier Caching Architecture
* **L1 Process-Local Memory Cache**:
  - Cache read-heavy, low-churn reference data (e.g., account limits, currency metadata, static routing tables) in Python process memory (`dict` with TTL expiration or `cachetools.TTLCache`).
  - Delivers instant sub-microsecond validation without network or database round-trips.
  - **Isolation Hook**: Always expose explicit eviction hooks (`clear_*_cache()`) to guarantee test isolation.
* **L2 Distributed Cache (Redis)**:
  - Fast-path idempotency checks using atomic `SET NX EX` with TTL.
  - Distributed token-bucket rate limiting and ephemeral coordination.
  - **Source of Truth**: Redis is an ephemeral acceleration layer; PostgreSQL remains the ultimate ACID source of truth.

### F. Shared Process Thread Pool for Sync-in-Async Bridging
* **Rationale**: Reconstructing ephemeral `ThreadPoolExecutor` instances inside `run_sync()` or `asyncio.to_thread()` wastes thread spawn overhead and OS context switches.
* **Standard**: Reuse a module-level eagerly-initialized singleton thread pool:
  ```python
  from concurrent.futures import ThreadPoolExecutor

  _sync_executor = ThreadPoolExecutor(max_workers=4)

  async def run_sync(func, *args, **kwargs):
      loop = asyncio.get_running_loop()
      return await loop.run_in_executor(_sync_executor, functools.partial(func, *args, **kwargs))
  ```

### G. Kombu AMQP Broker Pooling
* **Standard**: Configure Celery with connection pooling and startup resilience:
  ```python
  celery_app.conf.update(
      broker_pool_limit=10,
      broker_connection_retry_on_startup=True,
  )
  ```

### H. Eager Boot Warm-Up (`@signals.worker_process_init` & FastAPI `lifespan`)
* **Worker Process Warm-Up**: When Celery child processes fork, the OS copy-on-write event loop and DB pools become invalid. Listen to `@signals.worker_process_init` to immediately re-initialize and warm the event loop, worker-budgeted DB pool, and HTTP client at process boot time so the first task executes with sub-25ms P99 latency:
  ```python
  from celery import signals

  @signals.worker_process_init.connect
  def init_worker_process(**kwargs):
      # Re-initialize event loop, database connection pool, and HTTP clients
      ...
  ```
* **FastAPI Lifespan Ping**: In FastAPI `lifespan`, pre-warm database connections on startup with a lightweight ping (`SELECT 1`) to eliminate first-request connection latency:
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      async with engine.begin() as conn:
          await conn.execute(text("SELECT 1"))
      yield
      await engine.dispose()
  ```

---

## 2. Database Index Architecture & Query Minimization

### A. Index Deduplication
* **Rule**: Never create an explicit `CREATE INDEX` on a column that already possesses a `UNIQUE` constraint or is a primary key.
* **Rationale**: PostgreSQL automatically provisions a B-Tree index for unique constraints; duplicate indexes double write amplification, disk waste, and WAL volume without any query benefit.

### B. Partial Indexes for State Machines
* **Rule**: Ban full-table indexes on low-cardinality status columns (`status VARCHAR(20)`) where 95%+ of rows reach terminal states (`settled`, `completed`, `failed`).
* **Standard**: Mandate partial B-Tree indexes targeting only active in-flight rows:
  ```sql
  CREATE INDEX idx_transactions_in_flight 
  ON transactions (created_at) 
  WHERE status IN ('pending', 'processing');
  ```
* **Rationale**: Keeps the active working index tiny enough to fit entirely inside CPU L3 cache and eliminates write amplification on settled/completed transactions.

### C. Database Query Minimization
* **Standard**: Minimize SQL round-trips per request cycle (reducing $4 \to 1$ round-trips).
* **Technique**: Use `RETURNING`, `INSERT ... ON CONFLICT`, and composite single-query updates to eliminate connection holding latency and reduce database contention by 75%.

---

## 3. PostgreSQL Engine Tuning & Financial Durability

### Modern NVMe Engine Configuration
```ini
# Recommended PostgreSQL engine settings for modern NVMe SSDs
shared_buffers = 512MB          # Or 25-40% of available system RAM
wal_buffers = 16MB
max_wal_size = 4GB
random_page_cost = 1.1          # Reflects NVMe random read performance
effective_io_concurrency = 200
```

### Strict Financial Durability (`synchronous_commit = on`)
* **Standard**: Default to `synchronous_commit = on` in banking and financial ledgers to guarantee zero data loss on power failure or node crash.
* **Performance Characteristic**: Single-query transactions keep physical NVMe `fsync` overhead negligible ($P_{99} \le 83\text{ ms}$ at 300 req/s).
* **Telemetry Exception**: Reserve `synchronous_commit = off` strictly for non-critical telemetry, transient logs, or ephemeral queue states.

---

## 4. Root-Cause Configuration Over Log Masking (The No-Masking Invariant)

* **Rule**: Whenever encountering driver, protocol, broker, or library warnings, errors, or unexpected handshakes (such as third-party probes like Redis `CLIENT MAINT_NOTIFICATIONS` on open-source instances, or AMQP channel negotiation rejections), **strictly prioritize eliminating the root cause via explicit driver/client configuration, connection arguments, or Pydantic `Settings`**.
* **Banning Log-Level Alteration as a Fix**: Modifying logger levels (e.g., bumping `setLevel(logging.INFO)` or suppressing library loggers) to silence errors or warnings is strictly forbidden as a primary solution. Silencing loggers merely masks underlying issues, hides protocol mismatches, leaves wasted CPU/network round-trips in place, and prevents operators from diagnosing real failures.
