import os
import pika
import json
import time
from pricing.pricing_data_fetcher import get_api_info

def read_config():
    try:
        with open('config.json', 'r') as file:
            config = json.load(file)
    except FileNotFoundError:
        print("config.json Not Found")
        return None
    return config

def on_connection_open_error_callback(connection, error_message, max_retries=10, retry_delay=5):
    print(f"Connection open error: {error_message}")

    for attempt in range(1, max_retries + 1):
        print(f"Retrying connection (attempt {attempt}/{max_retries})...")
        time.sleep(retry_delay)

        try:
            # Retry opening the connection
            connection.ioloop.stop()
            connection.ioloop.start()                        
        except pika.exceptions.AMQPConnectionError as e:
            print(f"Retry attempt {attempt}/{max_retries} failed: {e}")
    print("Exceeded maximum retry attempts. Exiting.")

def on_open_error_callback(connection, error_message):
    print(f"Channel open error: {error_message}")
    connection.ioloop.stop()

    # Handle the error or implement retry logic here

def on_close_callback(connection, exception):
    if exception:
        print(f"Connection closed unexpectedly: {exception}")
    else:
        print("Connection closed.")


def generate_response(request_data):    
    print("Generating response...")    
    return get_api_info()

def on_request(ch, method, properties, body):
    try:
        # request_data = json.loads(body.decode('utf-8'))
        request_data = body.decode('utf-8')
        print(f"Received request: {request_data}")

        # Process the request and generate a response
        response_data = generate_response(request_data)
        print("Response ready...")
        ch.basic_ack(delivery_tag = method.delivery_tag)
        print("ACK sent...")

        ch.queue_declare(queue=RESPONSE_EXCHANGE)

        # Publish the response to the response_exchange with the specified routing key
        ch.basic_publish(
            exchange='',
            routing_key=RESPONSE_ROUTING_KEY,
            body=json.dumps(response_data))

        print(f"Sent response: {response_data}")

    except json.JSONDecodeError:
        print("Invalid JSON format in the received message")


def on_open_callback(connection):
    print("Connection opened.")
    # Create a channel when the connection is opened
    channel = connection.channel(on_open_callback=on_channel_open)

def on_channel_open(channel):
    print("Channel opened.")
    try:
        channel.queue_declare(queue=REQUEST_QUEUE)
        channel.basic_consume(queue=REQUEST_QUEUE, 
                              on_message_callback=on_request)
        print("Waiting for requests. To exit press CTRL+C")
    except Exception as e:
        print(f"Error setting up consumer: {e}")
        connection.ioloop.stop()


if __name__ == '__main__':
    print("Current working directory:", os.getcwd())

    config = read_config()
    if config is None:
        print("Listener config file can not be loaded. Start cancelled.")
        exit(1)

    # Use the RabbitMQ connection parameters from the config
    try:
        RABBITMQ_HOST = config.get('RABBITMQ_HOST')
        RABBITMQ_PORT = int(config.get('RABBITMQ_PORT'))
        REQUEST_QUEUE = config.get('REQUEST_QUEUE')
        RESPONSE_EXCHANGE = config.get('RESPONSE_EXCHANGE')
        RESPONSE_ROUTING_KEY = config.get('RESPONSE_ROUTING_KEY')
    except Exception:
        print("Config file is not compatible. Check file values")
        exit(1)

    # Establish connection to RabbitMQ    
    connection_params = pika.ConnectionParameters('localhost')
    
    # Attempt to establish a connection to RabbitMQ
    connection = pika.SelectConnection(
        parameters=connection_params,
        on_open_callback=on_open_callback,
        on_close_callback=on_close_callback,
        on_open_error_callback=lambda conn, err_msg: on_connection_open_error_callback(conn, err_msg)
    )

    try:
        # Start the IOLoop to continuously monitor the connection
        connection.ioloop.start()
    except KeyboardInterrupt:
        # Gracefully handle keyboard interrupt to close the connection
        connection.close()
        connection.ioloop.start()
    
