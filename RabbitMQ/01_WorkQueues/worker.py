import pika, sys, os, time


def main():
    # Establish a connection with RabbitMQ server
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()

    # Declare the queue
    channel.queue_declare(queue='hello')
    # Persistend mode
    # channel.queue_declare(queue='task_queue', durable=True)

    # Define a callback function to process the messages
    def callback(ch, method, properties, body):
        print(f" [x] Received {body.decode()}")
        time.sleep(body.count(b'.'))
        print(" [x] Done")
        ch.basic_ack(delivery_tag = method.delivery_tag)

    # Tell RabbitMQ that this particular callback function should receive messages from our 'hello' queue
    
    # Avoid receiving more than 1 message to be process. 
    # channel.basic_qos(prefetch_count=1)

    channel.basic_consume(queue='hello',
                        # auto_ack=True,
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
