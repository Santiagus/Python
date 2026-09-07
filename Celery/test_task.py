import sys
from kombu.exceptions import OperationalError
from tasks import add, app


def check_broker_connection() -> bool:
    """Check if the broker is reachable before attempting to publish tasks."""
    print("Checking broker connection...")
    try:
        # Establish a short-timeout connection to test connectivity
        with app.connection_for_write() as conn:
            conn.connect()
            print(f"Broker reachable at: {conn.as_uri()}")
            return True
    except (OperationalError, ConnectionRefusedError) as exc:
        print("\n[ERROR] Broker connection failed!")
        print(f"Details: {exc}")
        print("\nTroubleshooting:")
        print("1. Ensure your RabbitMQ container is running:")
        print("   docker start celery-rabbitmq")
        print("2. Check if port 5672 is mapped correctly:")
        print("   docker ps --filter name=celery-rabbitmq")
        return False


def test_worker_execution():
    """Dispatch a task and wait for the worker to return the result."""
    print("\nDispatching task: add.delay(4, 4)...")
    try:
        result = add.delay(4, 4)
        print(f"Task submitted with ID: {result.id}")
        print(f"Initial status: {result.status}")

        print("Waiting up to 5 seconds for a worker to process the task...")
        # timeout raises TimeoutError if no active worker consumes the message
        value = result.get(timeout=5)

        print(f"Task completed successfully! Result: {value}")
        print(f"Final status: {result.status}")

    except TimeoutError:
        print("\n[WARNING] Task timed out waiting for results!")
        print("The broker accepted the message, but no worker picked it up.")
        print("Make sure your worker is running in a separate terminal:")
        print("   celery -A tasks worker --loglevel=INFO")
    except Exception as exc:
        print(f"\n[ERROR] Task execution failed: {exc}")


if __name__ == "__main__":
    broker_ok = check_broker_connection()
    if not broker_ok:
        sys.exit(1)

    test_worker_execution()