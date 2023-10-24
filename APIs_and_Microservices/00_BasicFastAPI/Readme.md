


# Create Orders API for a coffee web shop



**1. Create OAS (OpenAPI specification)**

<details><summary>oas.yaml</summary>

```yaml
OrderItemSchema:
type: object
required:
    - product
    - size
properties:
    product:
    type: string
    size:
    type: string
    enum:
        - small
        - medium
        - big
    quantity:
    type: integer
    default: 1
    minimum: 1
```
</details>
</br>
OAS stands for OpenAPI specification, which is a standard format for documenting
REST APIs.
</br>
</br>

**2. Install packages** \
```pip install fastapi uvicorn```


**3. Create FastAPI app**
<details>
<summary>orders/app.py</summary>

```python
from fastapi import FastAPI
app = FastAPI(debug=True)
from orders.api import api
```
</details>
</br>

**4. Orders API Minimal Implementation** 
<details>
<summary>orders/api/api.py</summary>

```python
from datetime import datetime
from uuid import UUID
from starlette.responses import Response
from starlette import status
from orders.app import app
from http import HTTPStatus

# Static order for testing purpose
order = {
    'id': 'ff0f1355-e821-4178-9567-550dec27a373',
    'status': "delivered",
    'created': datetime.utcnow(),
    'order': [
        {
            'product': 'cappuccino',
            'size': 'medium',
            'quantity': 1
        }
    ]
}

@app.get('/orders')
def get_orders():
    return {'orders': [order]}

@app.post('/orders', status_code=status.HTTP_201_CREATED)
def create_order():
    return order

@app.get('/orders/{order_id}')
def get_order(order_id: UUID):
    return order

@app.put('/orders/{order_id}')
def update_order(order_id: UUID):
    return order

@app.delete('/orders/{order_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: UUID):
    return Response(status_code=HTTPStatus.NO_CONTENT.value)

@app.post('/orders/{order_id}/cancel')
def cancel_order(order_id: UUID):    
    return order

@app.post('/orders/{order_id}/pay')
def pay_order(order_id: UUID):
    return order
```
</details>
</br>

**5. Run app** \
```$ uvicorn orders.app:app --reload```

**6. Check REST API**
+ [Swagger UI](http://127.0.0.1:8000/docs)
+ [Redoc](http://127.0.0.1:8000/redoc)

*order_id* is static at this point : ***ff0f1355-e821-4178-9567-550dec27a373***

Method | Description               | Endpoint
-------| ------------------------- | ----------
GET    | /orders                   | http://127.0.0.1:8000/orders
POST   | /orders                   | http://127.0.0.1:8000/orders
GET    | /orders/{order_id}        | http://127.0.0.1:8000/ff0f1355-e821-4178-9567-550dec27a373
PUT    | /orders/{order_id}        | http://127.0.0.1:8000/ff0f1355-e821-4178-9567-550dec27a373
DELETE | /orders/{order_id}        | http://127.0.0.1:8000/ff0f1355-e821-4178-9567-550dec27a373
POST   | /orders/{order_id}/cancel | http://127.0.0.1:8000/ff0f1355-e821-4178-9567-550dec27a373/cancel
POST   | /orders/{order_id}/pay    | http://127.0.0.1:8000/ff0f1355-e821-4178-9567-550dec27a373/pay


All but DELETE should return the following response body:

<details><summary>Server Response</summary>

```json
{
  "orders": [
    {
      "id": "ff0f1355-e821-4178-9567-550dec27a373",
      "status": "delivered",
      "created": "2023-10-23T09:34:18.722191",
      "order": [
        {
          "product": "cappuccino",
          "size": "medium",
          "quantity": 1
        }
      ]
    }
  ]
}
```
</details>
</br>

**7. Add validation models using pydantic**
<details><summary>orders/api/api.py</summary>

```python
from orders.api.schemas import CreateOrderSchema

@app.post('/orders', status_code=status.HTTP_201_CREATED)
def create_order(order_details: CreateOrderSchema):
    return order

@app.put('/orders/{order_id}')
def update_order(order_id: UUID, order_details: CreateOrderSchema):
    return order
```
</details>
</br>

<details><summary>orders/api/schemas.py</summary>

```python
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field, validator, root_validator
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
    quantity: Annotated[int, Field(strict=True, ge=1, le=10)] = 1

    @validator("quantity")
    def quantity_non_nullable(cls, value):
        assert value is not None, "quantity may not be None"
        return value

class CreateOrderSchema(BaseModel):
    order: Annotated[List[OrderItemSchema], Field(min_length=1)]

class GetOrderSchema(CreateOrderSchema):
    id: UUID
    created: datetime
    updated: datetime
    status: Status


class GetOrdersSchema(BaseModel):
    orders: List[GetOrderSchema]
```
</details>
</br>


**8. Response payloads validation**
<details><summary>orders/api/api.py</summary>

```python
from orders.api.schemas import (
GetOrderSchema,
CreateOrderSchema,
GetOrdersSchema,
)

@app.get('/orders', response_model=GetOrdersSchema)
def get_orders():
    return GetOrdersSchema(orders=ORDERS)


@app.post('/orders', status_code=status.HTTP_201_CREATED, response_model=GetOrderSchema,)
def create_order(order_details: CreateOrderSchema):
    return order
```
</details>
</br>

**9. Add in-memory orders list to the API**
<details><summary>orders/api/api.py</summary>

```python
import uuid
from fastapi import HTTPException

ORDERS = []

@app.get("/orders", response_model=GetOrdersSchema)
def get_orders():
    return ORDERS

@app.post("/orders", status_code=status.HTTP_201_CREATED, response_model=GetOrderSchema)
def create_order(order_details: CreateOrderSchema):
    order = order_details.model_dump()
    order["id"] = uuid.uuid4()
    order["created"] = datetime.utcnow()
    order["status"] = "created"
    ORDERS.append(order)
    return order


@app.get("/orders/{order_id}")
def get_order(order_id: UUID):
    for order in ORDERS:
        if order["id"] == order_id:
            return order
    raise HTTPException(status_code=404, detail=f"Order with ID {order_id} not found")

@app.put("/orders/{order_id}")
def update_order(order_id: UUID, order_details: CreateOrderSchema):
    for order in ORDERS:
        if order["id"] == order_id:
            order.update(order_details.dict())
            return order
    raise HTTPException(status_code=404, detail=f"Order with ID {order_id} not found")

@app.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: UUID):
    for index, order in enumerate(ORDERS):
        if order["id"] == order_id:
            ORDERS.pop(index)
            return Response(status_code=HTTPStatus.NO_CONTENT.value)
    raise HTTPException(status_code=404, detail=f"Order with ID {order_id} not found")

@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: UUID):
    for order in ORDERS:
        if order["id"] == order_id:
            order["status"] = "cancelled"
            return order
    raise HTTPException(status_code=404, detail=f"Order with ID {order_id} not found")


@app.post("/orders/{order_id}/pay")
def pay_order(order_id: UUID):
    for order in ORDERS:
        if order["id"] == order_id:
            order["status"] = "progress"
            return order
    raise HTTPException(status_code=404, detail=f"Order with ID {order_id} not found")
```
</details>