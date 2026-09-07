# 07: Failure and Recovery Lab

Use RabbitMQ and workers in containers to test real failure boundaries.

## Experiments

- Kill a worker before acknowledgement and during task execution.
- Stop and restart the broker.
- Compare early and late acknowledgements.
- Test durable queues, persistent messages, redelivery, and dead-letter handling.
- Measure recovery time and identify duplicated or lost work.

## Evidence

Keep an experiment log with configuration, observed behavior, and the guarantees the system can actually provide.
