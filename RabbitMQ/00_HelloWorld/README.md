# RabbitMQ

RabbitMQ is lightweight and easy to deploy on premises and in the cloud. It supports multiple messaging protocols and streaming. RabbitMQ can be deployed in distributed and federated configurations to meet high-scale, high-availability requirements.

# Quick Start

- Run docker container: \
`docker run -it --rm --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3.12-management`

- Install Pika (RabbitMQ Python client): \
`python -m pip install pika --upgrade`

- To connect to the running container: \
`docker exec -it rabbitmq /bin/bash`

- To check lists and messagges: \
`rabbitmqctl list_queues`

## Example
<details><summary>consumer.py</summary>

```python
import pika, sys, os


def main():
    # Establish a connection with RabbitMQ server
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()

    # Declare the queue
    channel.queue_declare(queue='hello')

    # Define a callback function to process the messages
    def callback(ch, method, properties, body):
        print(" [x] Received %r" % body)

    # Tell RabbitMQ that this particular callback function should receive messages from our 'hello' queue
    channel.basic_consume(queue='hello',
                        auto_ack=True,
                        on_message_callback=callback)

    print(' [*] Waiting for messages. To exit press CTRL+C')
    channel.start_consuming()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted')
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
```
</details>

<details><summary>producer.py</summary>

```python
import pika

# Establish a connection with RabbitMQ server
connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

# Create a queue named 'hello'
channel.queue_declare(queue='hello')

# Send a message
channel.basic_publish(exchange='',
                    routing_key='hello',
                    body='Hello World!')
print(" [x] Sent 'Hello World!'")

connection.close()
```
</details>