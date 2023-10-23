# file: orders/api/schemas.py
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Annotated
from uuid import UUID


class Size(Enum):
    small = "small"
    medium = "medium"
    big = "big"


class Status(Enum):
    created = "created"
    progress = "progress"
    cancelled = "cancelled"
    dispatched = "dispatched"
    delivered = "delivered"


class OrderItemSchema(BaseModel):
    product: str
    size: Size
    # quantity: Optional[conint(ge=1, strict=True)] = 1
    quantity: Annotated[int, Field(strict=True, ge=1)]


class CreateOrderSchema(BaseModel):
    # order: conlist(OrderItemSchema, min_items=1)
    order: Annotated[List[OrderItemSchema], Field(min_length=1)]


class GetOrderSchema(CreateOrderSchema):
    id: UUID
    created: datetime
    status: Status


class GetOrdersSchema(BaseModel):
    orders: List[GetOrderSchema]
