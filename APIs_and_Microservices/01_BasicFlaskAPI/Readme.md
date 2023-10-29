# FlaskAPI 

This project start from previous one adding a new API for kitchen orders that will be implemented using flask-smorest.

Flask-smorest is a REST API framework built on top of Flask and marshmallow


## Initial Setup

**1. Create project folder** \
```mkdir 01_BasicFlaskAPI```

**2. Create virtual environment** \
```python -m venv .venv```

**3. Copy ../00_BasicFastAPI/orders folder** \
```cp -r ../00_BasicFastAPI/orders/ .```

**4. Activate virtual environment** \
```. .venv/bin/activate```

**5.Install dependencies** 
- From scratch: \
 ```pip install uvicorn FastAPI flask-smorest``` 
- From requirements.txt \
```pip install -r requirements.txt```

**6. Save requirements** \
```pip freeze > requirements.txt```

**7. Check app is working** \
Run : ```uvicorn orders.app:app --reload``` \
Check: http://localhost:8000/docs

## Implementations

#### Add query parameters to orders:

<details>

```python
from typing import Annotated, List, Optional

@app.get("/orders", response_model=GetOrdersSchema)
def get_orders(cancelled: Optional[bool] = None, limit: Optional[int] = None):
    if cancel_order is None and limit is None:
        return GetOrdersSchema(orders=ORDERS)

    query_set = [order for order in ORDERS]

    if cancelled is not None:
        if cancelled:
            query_set = [order for order in query_set if order["status"] == "cancelled"]
        else:
            query_set = [order for order in query_set if order["status"] != "cancelled"]

    if limit is not None and len(query_set) > limit:
        return {"orders": query_set[:limit]}

    return {"orders": query_set}
```
</details>
</br>

####  Check orders endpoint filtering
Run : ```uvicorn orders.app:app --reload``` \
Check: http://localhost:8000/docs

#### Disallowing additional properties in models
<details> <summary> Update oas.yaml </summary>

```yaml
    OrderItemSchema:
      additionalProperties: false

    CreateOrderSchema:
        additionalProperties: false

    GetOrderSchema:
        additionalProperties: false
```
</details>

<details> <summary> Update schemas.py </summary>

```python
    from pydantic import Extra

    class OrderItemSchema(BaseModel):
        ...
        class Config:
            extra = "forbid"

    class CreateOrderSchema(BaseModel):
        ...
        class Config:
            extra = "forbid"

    class GetOrdersSchema(BaseModel):
        ...
        class Config:
            extra = "forbid"
```
</details>

### Override FastAPI generated specification

```pip install pyyaml```

<details><summary>orders/orders/app.py</summary>

```python
    from pathlib import Path
    import yaml

    from fastapi import FastAPI
    app = FastAPI(debug=True)

    oas_doc = yaml.safe_load((Path(__file__).parent / '../oas.yaml').read_text())

    app.openapi = lambda: oas_doc

    from orders.api import api
```
</details>

<details><summary>orders/oas.yaml</summary>

```yaml
openapi: 3.0.3

servers:
    - url: http://localhost:8000
    description: URL for local development and testing
    - url: https://coffeemesh.com
    description: main production server
    - url: https://coffeemesh-staging.com
    description: staging server for testing purposes only
```
</details>