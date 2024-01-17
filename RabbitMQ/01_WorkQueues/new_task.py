import pika, sys
from datetime import datetime

# Establish a connection with RabbitMQ server
connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

# Create a queue named 'hello'
channel.queue_declare(queue='rank_queue')

# message = ' '.join(sys.argv[1:]) or "Hello World!"
message = datetime.now().isoformat()
channel.basic_publish(exchange='',
                      routing_key='rank_queue',
                      body=message)

# Persistent mode
# channel.queue_declare(queue='task_queue', durable=True)
# channel.basic_publish(exchange='',
#                       routing_key="task_queue",
#                       body=message,
#                       properties=pika.BasicProperties(
#                          delivery_mode = pika.DeliveryMode.Persistent
#                       ))
print(f" [x] Sent {message}")
connection.close()