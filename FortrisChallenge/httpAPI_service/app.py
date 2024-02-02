from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging
import logging.config
import yaml
import json
from tenacity import RetryError
from shared.data_fetcher import DataFetcher
from common.redis_utils import connect_to_redis
from common.utils import load_config_from_json

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Async context manager for managing the lifespan of a FastAPI application.

    This context manager is typically used to handle setup and cleanup operations
    during the application's lifespan, such as initializing and closing connections
    or resources.

    Parameters:
        - `app` (FastAPI): The FastAPI application instance.

    Yields:
        - None: The async context manager yields control to the enclosed block.

    Example:
        ```python
        async with lifespan(my_app):
            # Perform setup operations here

        # Perform cleanup operations here, after the lifespan block exits
        ```
    """
    
    try:
        app.state.redis = None
        app.state.config = load_config_from_json('httpAPI_service/config.json')

        # Set up logging based on the configuration
        logging.config.dictConfig(app.state.config["logging"])

        logging.info(f"Service start. Loading configuration...")
        
        app.state.redis = await connect_to_redis(app.state.config["redis"])

        # Setup data fetchers for direct data adquisition
        price_config = load_config_from_json('config/price_config.json')
        rank_config = load_config_from_json('config/rank_config.json')
        app.state.price_fetcher = DataFetcher(price_config)
        app.state.rank_fetcher = DataFetcher(rank_config)


    except json.decoder.JSONDecodeError as e:
        logging.error(f"Config load error : {e}")
    except ConnectionRefusedError as e:
        logging.error(f"Failed to connect to Redis: {e}")
    except RetryError:
        logging.error("Failed to connect to Redis after retries.")
    except Exception as e:
        logging.error(f"An unexpected error occurred during startup: {e}")
    finally:
        yield
        # Shutdown (Close connections to msg broker, db, ...)
        if app.state.redis is not None:
            app.state.redis.close()


app = FastAPI(
    title="Your API",
    version="1.0.0",
    lifespan=lifespan
)

with open("httpAPI_service/oas.yaml", "r") as file:
    oas_doc = yaml.safe_load(file)
app.openapi = lambda: oas_doc

from httpAPI_service.api import api
