import logging
import asyncio
from .. import price_publisher

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(price_publisher.main())