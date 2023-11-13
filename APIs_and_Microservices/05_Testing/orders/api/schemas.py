# file: orders/api/schemas.py
from enum import Enum
from datetime import datetime
from pydantic import (
    BaseModel,
    Field,
    validator,
    ConfigDict,
)
from typing import List, Annotated
from uuid import UUID


class Size(Enum):
    small = "small"
    medium = "medium"
    big = "big"


class Status(Enum):
    created = "created"
    updated = "updated"
    paid = "paid"
    progress = "progress"
    cancelled = "cancelled"
    dispatched = "dispatched"
    delivered = "delivered"


class OrderItemSchema(BaseModel):
    product: str
    size: Size
    # quantity: Optional[conint(ge=1, strict=True)] = 1
    quantity: Annotated[int, Field(strict=True, ge=1, le=1000000)] = 1

    @validator("quantity")
    def quantity_non_nullable(cls, value):
        assert value is not None, "quantity may not be None"
        return value

    class Config:
        extra = "forbid"


class CreateOrderSchema(BaseModel):
    order: Annotated[List[OrderItemSchema], Field(min_length=1)]

    model_config = ConfigDict(extra="forbid")

    # class Config:
    #     extra = "forbid"


class GetOrderSchema(CreateOrderSchema):
    id: UUID
    created: datetime
    updated: datetime
    status: Status


class GetOrdersSchema(BaseModel):
    # orders: List[GetOrderSchema]
    orders: Annotated[List[GetOrderSchema], Field(min_length=0)]

    class Config:
        extra = "forbid"

    # order: List[OrderItemSchema]
    # @root_validator(pre=True)
    # def validate_data(cls, orders):
    #     if orders == []:
    #         return dict(list())
