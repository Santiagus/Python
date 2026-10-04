"""Unit tests for Docker Compose multi-container infrastructure declaration.

Verifies service definitions, container names, healthcheck commands, port mappings,
dependency graphs, and volume mount configurations.
"""

from pathlib import Path

import yaml


def test_docker_compose_file_exists_and_parses(workspace_root: Path) -> None:
    """Verify docker-compose.yml exists and contains valid YAML."""
    compose_path = workspace_root / "docker-compose.yml"
    assert compose_path.is_file(), "docker-compose.yml must exist at workspace root"

    with open(compose_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert isinstance(data, dict), "docker-compose.yml must parse to a dictionary"
    assert "services" in data, "docker-compose.yml must define 'services'"


def test_required_services_defined(workspace_root: Path) -> None:
    """Verify that all 6 required distributed services are declared."""
    compose_path = workspace_root / "docker-compose.yml"
    with open(compose_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    services = data.get("services", {})
    required = {
        "postgres",
        "rabbitmq",
        "bank_simulator_api",
        "api",
        "worker_1",
        "worker_2",
    }
    for req in required:
        assert req in services, (
            f"Service '{req}' must be declared in docker-compose.yml"
        )


def test_postgres_service_configuration(workspace_root: Path) -> None:
    """Verify PostgreSQL 16 service ports, image, volume mounts, and healthcheck."""
    compose_path = workspace_root / "docker-compose.yml"
    with open(compose_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    pg = data["services"]["postgres"]
    assert pg["image"] == "postgres:16-alpine"
    assert "5432:5432" in pg.get("ports", [])
    assert "healthcheck" in pg

    # Check volume mounts
    volumes = pg.get("volumes", [])
    assert any("init.sql" in str(v) for v in volumes), (
        "init.sql must be mounted to docker-entrypoint-initdb.d"
    )


def test_rabbitmq_service_configuration(workspace_root: Path) -> None:
    """Verify RabbitMQ 3.13 service ports, definitions volume mount, and healthcheck."""
    compose_path = workspace_root / "docker-compose.yml"
    with open(compose_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    rabbit = data["services"]["rabbitmq"]
    assert rabbit["image"] == "rabbitmq:3.13-management-alpine"
    ports = rabbit.get("ports", [])
    assert "5672:5672" in ports
    assert "15672:15672" in ports
    assert "healthcheck" in rabbit

    # Check definitions mount
    volumes = rabbit.get("volumes", [])
    assert any("definitions.json" in str(v) for v in volumes), (
        "definitions.json must be mounted to rabbitmq"
    )


def test_worker_fleet_configuration(workspace_root: Path) -> None:
    """Verify worker fleet contains 2 isolated worker pods with correct queues."""
    compose_path = workspace_root / "docker-compose.yml"
    with open(compose_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    w1 = data["services"]["worker_1"]
    w2 = data["services"]["worker_2"]

    # Verify both pods are configured
    assert w1["container_name"] == "wire_worker_1"
    assert w2["container_name"] == "wire_worker_2"
    assert w1["hostname"] == "worker-pod-1"
    assert w2["hostname"] == "worker-pod-2"

    # Verify listening to wire.settlement.critical queue
    assert "wire.settlement.critical" in " ".join(w1.get("command", []))
    assert "wire.settlement.critical" in " ".join(w2.get("command", []))


def test_rabbitmq_definitions_file_exists_and_valid(workspace_root: Path) -> None:
    """Verify docker/rabbitmq/definitions.json exists and specifies required topology."""
    import json

    def_path = workspace_root / "docker" / "rabbitmq" / "definitions.json"
    assert def_path.is_file(), "docker/rabbitmq/definitions.json must exist"

    data = json.loads(def_path.read_text(encoding="utf-8"))
    queues = {q["name"]: q for q in data.get("queues", [])}
    exchanges = {e["name"]: e for e in data.get("exchanges", [])}

    assert "wire.settlement.critical" in queues
    assert "wire.settlement.dlq" in queues
    assert "wire.direct" in exchanges
    assert "wire.dlx" in exchanges

    # Verify DLX arguments on critical queue
    crit_args = queues["wire.settlement.critical"].get("arguments", {})
    assert crit_args.get("x-dead-letter-exchange") == "wire.dlx"
    assert crit_args.get("x-dead-letter-routing-key") == "wire.settlement.dlq"


def test_centralized_dockerfiles_exist_and_referenced(workspace_root: Path) -> None:
    """Verify centralized Dockerfiles in docker/ exist and are mapped in docker-compose.yml."""
    expected_dockerfiles = [
        workspace_root / "docker" / "Dockerfile.api",
        workspace_root / "docker" / "Dockerfile.worker",
        workspace_root / "docker" / "Dockerfile.bank_simulator_api",
    ]
    for df in expected_dockerfiles:
        assert df.is_file(), f"Centralized Dockerfile must exist: {df}"

    compose_path = workspace_root / "docker-compose.yml"
    with open(compose_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for svc_name in ["bank_simulator_api", "api", "worker_1", "worker_2"]:
        svc = data["services"][svc_name]
        assert "build" in svc, f"Service '{svc_name}' must have a build configuration"
        dockerfile_rel = svc["build"].get("dockerfile")
        assert dockerfile_rel is not None, f"Service '{svc_name}' must specify a dockerfile"
        assert dockerfile_rel.startswith("docker/Dockerfile."), (
            f"Service '{svc_name}' must reference centralized dockerfile, got {dockerfile_rel}"
        )
        assert (workspace_root / dockerfile_rel).is_file(), (
            f"Referenced dockerfile must exist on disk: {dockerfile_rel}"
        )

