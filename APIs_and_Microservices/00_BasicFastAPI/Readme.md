


# Create Orders API for a coffee web shop



1. Create OAS (OpenAPI specification)

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

OAS stands for OpenAPI specification, which is a standard format for documenting
REST APIs.

2. Install packages 
```pip install fastapi uvicorn```


3. Create FastAPI app
    <details>
    <summary>orders/app.py</summary>
 
    ```python
    from datetime import datetime
    from uuid import UUID
    from starlette.responses import Response
    from starlette import status
    from orders.app import app

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
    ```

4. Orders API Minimal Implementation 
    <details>
    <summary>orders/api/api.py</summary>

    ```python
    from datetime import datetime
    from uuid import UUID
    from starlette.responses import Response
    from starlette import status
    from orders.app import app

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
    return {'orders': [orders]}

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


5. Run app
```$ uvicorn orders.app:app --reload```

6. Check API  
+ [Swagger UI](http://127.0.0.1:8000/docs)
+ [Redoc](http://127.0.0.1:8000/redoc)