
from fastapi import Query
from pydantic import BaseModel
from datetime import datetime

class GetTopCryptoListSchema(BaseModel):    
    limit: int = Query(default=10, title="The number of items to retrieve", ge=1)
    timestamp: datetime = Query(None, title="The timestamp of the request", description="Optional timestamp parameter")
