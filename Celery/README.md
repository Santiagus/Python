# Celery Getting Started: First Steps

This directory contains the code and environment setup for following the official [First Steps with Celery](https://docs.celeryq.dev/en/stable/getting-started/first-steps-with-celery.html) tutorial.

---

## 1. Directory Structure

Ensure your `celery/` directory is organized as follows:

```text
celery/
├── .venv/               # Isolated Python virtual environment with Celery dependencies
├── README.md            # Setup instructions, configuration notes, and execution steps
├── requirements.txt     # Python package dependencies (celery, redis, amqp drivers)
├── docker-compose.yml   # Container definitions for local broker services (RabbitMQ / Redis)
└── tasks.py             # Celery app initialization, broker config, and task definitions
```

## 2. Broker Setup
Celery requires a message broker.

You can use either RabbitMQ (recommended default) or Redis.
Run either service locally via Docker:

#### RabbitMQ (Default)
```Bash
docker run -d -p 5672:5672 -p 15672:15672 --name celery-rabbitmq rabbitmq:3-management
```
Broker URL: `pyamqp://guest@localhost//`

#### Redis
```Bash
docker run -d -p 6379:6379 --name celery-redis redis:7-alpine
```
Broker URL: `redis://localhost:6379/03`


## 3. Environment Setup
Create and Activate Virtual Environment
```Bash
# Create virtual environment
python3 -m venv .venv
# Activate virtual environment
source .venv/bin/activate
```
Populate `requirements.txt` based on your chosen broker:
```bash
# Core Celery
celery>=5.4.0
# Broker & Result Backend Drivers
# redis>=5.0.0      # Required if using Redis as broker or backend
# amqp>=5.2.0     # Included by default with Celery for RabbitMQ
```

**Install dependencies:**

```Bash
pip install --upgrade pip
pip install -r requirements.txt
```
## 4. Application Implementation
Create `tasks.py` with your Celery instance and a sample task:
```Python
from celery import Celery

# RabbitMQ broker URL using the pyamqp (librabbitmq/amqp) driver
BROKER_URL = 'pyamqp://guest:guest@localhost:5672//'

# Celery RPC result backend (returns results via transient RabbitMQ reply queues)
# Set to None if you do not need to retrieve return values with result.get()
BACKEND_URL = 'rpc://'

app = Celery('tasks', broker=BROKER_URL, backend=BACKEND_URL)


@app.task
def add(x, y):
    return x + y

```

## 5. Running the Worker
Start the Celery worker process from within this directory:
```Bash
celery -A tasks worker --loglevel=INFO
```

**Note for Windows users (outside WSL):**

If running directly on Windows without WSL, Celery 5+ requires the --pool=solo or --pool=threads flag:

```Bash
celery -A tasks worker --loglevel=INFO --pool=solo
```

## 6. Invoking Tasks
Open a separate terminal window, activate the virtual environment, and launch a Python shell:
```Bash
source .venv/bin/activate
```


Execute the task asynchronously:
```python
>>> from tasks import add
>>> result = add.delay(4, 4)

# Check if the task finished execution
>>> result.ready()
True

# Retrieve the result (blocks until task is finished if not ready)
>>> result.get(timeout=1)
8

# Inspect task ID and execution state
>>> result.id
'b89c3a64-7548-4394-bb9e-1dc6b85672b1'
>>> result.status
'SUCCESS'
```

A ready to run python script at `test_task.py`

## 7. Running Tests

Install the development dependencies:
```Bash
pip install -r requirements_dev.txt
```

### Unit tests

`test/test_unit.py` tests the `add` task directly with `add.run(...)`. These
tests verify the task's calculation for normal, negative, and fractional input
without starting Celery, RabbitMQ, Docker, or a worker process.

```Bash
pytest -v test/test_unit.py
```

### Integration tests

`test/test_integration.py` verifies that the Celery task, broker, worker, and
result backend work together in one test process. It uses Celery's in-memory
transport and an in-process worker, so it is fast and does not require Docker
or an external RabbitMQ service.

```Bash
pytest -v test/test_integration.py
```

### End-to-end tests

`test/test_e2e.py` verifies the production-like process boundary. It starts a
disposable RabbitMQ container, builds the runtime broker configuration, starts
a separate Celery worker process, waits for that worker to become ready, and
then submits a task through RabbitMQ before checking the result.

This test requires Docker and uses `testcontainers` and `pika`. The RabbitMQ
container and worker process are cleaned up automatically after the test.

```Bash
pytest -v test/test_e2e.py
```

### Full suite

Run all three test layers with:
```Bash
pytest -v
```

Tests are organized in `test/test_unit.py`, `test/test_integration.py`, and
`test/test_e2e.py`.

## 8. Useful Worker Commands & Debugging

| Command | Purpose |
| --- | --- |
| `celery -A tasks status` | Check if workers are alive |
| `celery -A tasks inspect active` | View currently executing tasks |
| `celery -A tasks purge` | Discard all pending messages from queues |


## 9. Load config from configuration module
Sample config at `celeryconfig.py`
```bass
broker_url = 'pyamqp://guest:guest@localhost:5672//'
result_backend = 'rpc://'

task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'Europe/Oslo'
enable_utc = True
```

Config can be applied after app creation:
```python
app = Celery('tasks')
app.config_from_object('celeryconfig')
```