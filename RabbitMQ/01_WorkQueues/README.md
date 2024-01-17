# Work Queues

In this project we'll create a Work Queue that will be used to distribute time-consuming tasks among multiple workers.

Work Queues (aka: Task Queues) avoids doing a resource-intensive task immediately and having to wait for it to complete. 

Task is encapsulated as a message and send it to the queue. 

Worker process/es will pop the tasks and eventually execute the job.

To fake the complex task we will send a string with dots, amount of dots in the string will be as amount of seconds to sleep in a `time.sleep()` blocking instrucction.

# References

- Run docker container: \
`docker run -it --rm --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3.12-management`

- Install Pika (RabbitMQ Python client): \
`python -m pip install pika --upgrade`

- To connect to the running container: \
`docker exec -it rabbitmq /bin/bash`

- To check lists and messagges: \
`rabbitmqctl list_queues`

## Example code

<details><summary>worker.py</summary>

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

<details><summary>new_task.py</summary>

```python
import pika, sys

# Establish a connection with RabbitMQ server
connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

# Create a queue named 'hello'
channel.queue_declare(queue='hello')

# Send a message
message = ' '.join(sys.argv[1:]) or "Hello World!"
channel.basic_publish(exchange='',
                      routing_key='hello',
                      body=message)
print(f" [x] Sent {message}")
connection.close()
```
</details>


### Execution

#### shell 1
```bash
python worker.py
# => [*] Waiting for messages. To exit press CTRL+C
```

#### shell 2
```bash
python worker.py
# => [*] Waiting for messages. To exit press CTRL+C
```
#### shell 3
```bash
python new_task.py First message.
python new_task.py Second message..
python new_task.py Third message...
python new_task.py Fourth message....
python new_task.py Fifth message.....
```


## Message acknowledgment

With our current code once RabbitMQ delivers message to the consumer, it immediately marks it for deletion. In case you terminate a worker the message it was just processing is lost. The messages that were dispatched to this particular worker but were not yet handled are also lost.

In order to make sure a message is never lost, RabbitMQ supports message acknowledgments. If a consumer dies without sending an ack, RabbitMQ will understand that a message wasn't processed fully and will re-queue it. If there are other consumers online at the same time, it will then quickly redeliver it to another consumer. 

A timeout (30 minutes by default) is enforced on consumer delivery acknowledgement.

Manual message acknowledgments are turned on by default. In previous examples we explicitly turned them off via the `auto_ack=True` flag.
To send the acknowledge add: \
`ch.basic_ack(delivery_tag = method.delivery_tag)` 
after the "Done" message.

to print the messages_unacknowledged field: \
`rabbitmqctl list_queues name messages_ready messages_unacknowledged`

## Message durability

When RabbitMQ quits or crashes it will forget the queues and messages unless you tell it not to. 
To make sure that messages aren't lost mark queue and messages as durable (already declared can't be redefined). 
```python
# Worker
channel.queue_declare(queue='task_queue', durable=True)

# Sender
channel.basic_publish(exchange='',
                      routing_key="task_queue",
                      body=message,
                      properties=pika.BasicProperties(
                         delivery_mode = pika.DeliveryMode.Persistent
                      ))
```

Marking messages as persistent tells RabbitMQ to save it to disk but there is still a short time window when RabbitMQ has accepted a message and hasn't saved it yet. 

If you need a stronger guarantee then you can use publisher confirms.
`https://www.rabbitmq.com/confirms.html``

### Fair dispatch
RabbitMQ dispatches a message when the message enters the queue. It doesn't look at the number of unacknowledged messages for a consumer. It just blindly dispatches every n-th message to the n-th consumer.

Using the Channel#basic_qos channel method with the prefetch_count=1 setting tells RabbitMQ don't dispatch a new message to a worker until it has processed and acknowledged the previous one. 

`channel.basic_qos(prefetch_count=1)`