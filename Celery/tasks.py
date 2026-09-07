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