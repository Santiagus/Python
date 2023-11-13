# file: orders/api/api.py
import logging

from typing import Annotated, List, Optional
import uuid

from datetime import datetime
from http import HTTPStatus
from fastapi import HTTPException, Header
from uuid import UUID
from starlette.responses import Response
from starlette import status
from orders.app import app
from orders.api.schemas import (
    GetOrderSchema,
    CreateOrderSchema,
    GetOrdersSchema,
)

# Static order for testing purpose
# order = {
#     "id": "ff0f1355-e821-4178-9567-550dec27a373",
#     "status": "delivered",
#     "created": datetime.utcnow(),
#     "updated": datetime.utcnow(),
#     "order": [{"product": "cappuccino", "size": "medium", "quantity": 1}],
# }

ORDERS = []

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

fail_cases = ["wlbkjM", "Ub1tOc", "ZPFWdj", "hSOGIF", "gM7BIO"]


@app.get("/orders", response_model=GetOrdersSchema)
def get_orders(
    cancelled: Optional[bool] = None,
    limit: Optional[int] = None,
    x_schemathesis_testcaseid: Optional[str] = Header(None),
):
    try:
        if x_schemathesis_testcaseid in fail_cases:
            print(x_schemathesis_testcaseid)

        if cancel_order is None and limit is None:
            return GetOrdersSchema(orders=ORDERS)
            # return {"orders": ORDERS}

        query_set = [order for order in ORDERS]

        if cancelled is not None:
            if cancelled:
                query_set = [
                    order for order in query_set if order["status"] == "cancelled"
                ]
                # query_set = filter(lambda ord: ord[status] == "cancelled", query_set)
            else:
                query_set = [
                    order for order in query_set if order["status"] != "cancelled"
                ]
                # query_set = filter(lambda ord: ord[status] != "cancelled", query_set)

        if limit is not None and len(query_set) > limit:
            return {"orders": query_set[:limit]}

        return {"orders": query_set}
    except Exception as e:
        logger.exception(f"get_orders Error: {e}")
        # raise HTTPException(status_code=500, detail="Internal Server Error")


@app.post(
    "/orders",
    status_code=status.HTTP_201_CREATED,
    # response_model=Annotated[GetOrderSchema, list],
    response_model=GetOrderSchema,
)
def create_order(order_details: CreateOrderSchema):
    try:
        # return order
        order = order_details.model_dump()
        order["id"] = uuid.uuid4()
        order["created"] = datetime.utcnow()
        # order["updated"] = datetime.utcnow()
        order["status"] = "created"
        ORDERS.append(order)
        return order
    except Exception as e:
        logger.exception(f"create_order error: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@app.get("/orders/{order_id}")
def get_order(order_id: UUID):
    # return order
    # try:
    for order in ORDERS:
        if order["id"] == order_id:
            return order
    raise HTTPException(status_code=404, detail=f"Order with ID {order_id} not found")
    # except Exception as e:
    #     logger.exception(f"get_order with ID {order_id} Error: {e}")


@app.put("/orders/{order_id}")
def update_order(order_id: UUID, order_details: CreateOrderSchema):
    # try:
    # return order
    for order in ORDERS:
        if order["id"] == order_id:
            order.update(order_details.model_dump())
            return order
    raise HTTPException(status_code=404, detail=f"Order with ID {order_id} not found")
    # except Exception as e:
    #     logger.exception(f"update_order with ID {order_id} Error: {e}")


@app.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: UUID):
    # try:
    # return Response(status_code=HTTPStatus.NO_CONTENT.value)
    for index, order in enumerate(ORDERS):
        if order["id"] == order_id:
            ORDERS.pop(index)
            return Response(status_code=HTTPStatus.NO_CONTENT.value)
    raise HTTPException(status_code=404, detail=f"Order with ID {order_id} not found")
    # except Exception as e:
    #     logger.exception(f"delete_order with ID {order_id} Error: {e}")


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: UUID):
    # try:
    # return order
    for order in ORDERS:
        if order["id"] == order_id:
            order["status"] = "cancelled"
            return order
    raise HTTPException(status_code=404, detail=f"Order with ID {order_id} not found")
    # except Exception as e:
    #     logger.exception(f"cancel_order with ID {order_id} Error: {e}")


@app.post("/orders/{order_id}/pay")
def pay_order(order_id: UUID):
    # try:
    # return order
    for order in ORDERS:
        if order["id"] == order_id:
            order["status"] = "progress"
            try:
                order_model = GetOrderSchema(**order)
                order_model.model_validate()  # type: ignore
                print("Order is valid according to GetOrderSchema.")
            except Exception as e:
                print(f"Validation error: {e}")
            return order
    print(f"No order found")
    raise HTTPException(status_code=404, detail=f"Order with ID {order_id} not found")
    # except Exception as e:
    #     logger.exception({f"pay_order with ID {order_id} Error: {e} "})
