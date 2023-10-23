# file: orders/api/api.py
from datetime import datetime
from uuid import UUID
from starlette.responses import Response
from starlette import status
from orders.app import app
from orders.api.schemas import (
    GetOrderSchema,
    CreateOrderSchema,
    GetOrdersSchema,
)
from http import HTTPStatus

# Static order for testing purpose
order = {
    "id": "ff0f1355-e821-4178-9567-550dec27a373",
    "status": "delivered",
    "created": datetime.utcnow(),
    "updated": datetime.utcnow(),
    "order": [{"product": "cappuccino", "size": "medium", "quantity": 1}],
}


@app.get("/orders", response_model=GetOrdersSchema)
def get_orders():
    return {"orders": [order]}


@app.post("/orders", status_code=status.HTTP_201_CREATED, response_model=GetOrderSchema)
def create_order(order_details: CreateOrderSchema):
    return order


@app.get("/orders/{order_id}")
def get_order(order_id: UUID):
    return order


@app.put("/orders/{order_id}")
def update_order(order_id: UUID, order_details: CreateOrderSchema):
    return order


@app.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: UUID):
    return Response(status_code=HTTPStatus.NO_CONTENT.value)


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: UUID):
    return order


@app.post("/orders/{order_id}/pay")
def pay_order(order_id: UUID):
    return order
