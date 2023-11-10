# Securing 

This project start from 02_BusinessLayer, from there security configuration and implementation will be added.layer.

## Setup

```bash
$ mkdir 04_Securing                         # Create project folder 
$ cd 04_Securing                            # Move to project folder 
$ cp -r ../02_BusinessLayer/* .             # Copy project files
$ . .venv/bin/activate                      # Activate venv
(.venv) $ pip install cryptography pyjwt # Install depencencies
```

## Definitions
***OAuth*** : open standard that allows users to grant access (issuing a token) to
third-party applications to their information on other websites.



#### Generate public key
```
$ openssl req -x509 -nodes -newkey rsa:2048 -keyout private_key.pem \
-out public_key.pem -subj "/CN=coffeemesh"
``````
#### Use key pair to sign and validate tokens
Create jwt_generator.py

<details><summary>jwt_generator.py</summary>

```python
from datetime import datetime, timedelta
from pathlib import Path
import jwt
from cryptography.hazmat.primitives import serialization

def generate_jwt():
    now = datetime.utcnow()
    payload = {
        "iss": "https://auth.coffeemesh.io/",
        "sub": "ec7bbccf-ca89-4af3-82ac-b41e4831a962",
        "aud": "http://127.0.0.1:8000/orders",
        "iat": now.timestamp(),
        "exp": (now + timedelta(hours=24)).timestamp(),
        "scope": "openid",
    }
    private_key_text = Path("private_key.pem").read_text()
    private_key = serialization.load_pem_private_key(
        private_key_text.encode(),
        password=None,
    )
    return jwt.encode(payload=payload, key=private_key, algorithm="RS256")

print(generate_jwt())
```
</details>

#### Run Script to generate jwt
```python jwt_generatory.py```
<details>

```
eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2F1dGguY29mZmVlbWVzaC5pby8iLCJzdWIiOiJlYzdiYmNjZi1jYTg5LTRhZjMtODJhYy1iNDFlNDgzMWE5NjIiLCJhdWQiOiJodHRwOi8vMTI3LjAuMC4xOjgwMDAvb3JkZXJzIiwiaWF0IjoxNjk5NDQzMTY1LjcyNjMxNywiZXhwIjoxNjk5NTI5NTY1LjcyNjMxNywic2NvcGUiOiJvcGVuaWQifQ.hpfxFqDtFz3KG0RQEoA0hBNyPbegnwKL76ZGuaGeLmdi7l61-MOfasQZzKTp6blYAspjF_E7N4nzd3al2RFMHQH9PGZznAD9_llKaSq3NRzNgOvabMOgCLxEaWKHcNAyiyo3vvlpHVsQjkhi-dH3V1mpiBxu_jA8EqvdU2w76_7YKxZowa38UddTi6UCXSdx6Psg8k_EIQRNklorDU1YLzPUHctdsbhtbNecstlmCWHwLYV_yc-KrlnH62c_4r1RpIBijtR1GW_nEW_nPQ_JE5iOzudZE78wbb3O6-XMWZzbvIfz03sCA1OwPhWnOhXqxdNLZVkHYJVIulkP-bgx9A
```
</details>
</br>
To extract the public key from our public certificate use the following command: \
```$ openssl x509 -pubkey -noout < public_key.pem > pubkey.pem```

### Inspect payloads
- https://jwt.io (copy generated string)
- Run:
    ```bash
    $ echo eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9 | base64 --decode```
    {"alg":"RS256","typ":"JWT"}
    ```
Create *jwt_decode.py* :
<details> 

```python
from math import e
import jwt
import sys
from cryptography.x509 import load_pem_x509_certificate
from pathlib import Path

print("Token validation Use: python3 jwt_decode public_key.pem access_token")

public_key_text = Path("public_key.pem").read_text()
public_key = load_pem_x509_certificate(public_key_text.encode("utf-8")).public_key()
access_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2F1dGguY29mZmVlbWVzaC5pby8iLCJzdWIiOiJlYzdiYmNjZi1jYTg5LTRhZjMtODJhYy1iNDFlNDgzMWE5NjIiLCJhdWQiOiJodHRwOi8vMTI3LjAuMC4xOjgwMDAvb3JkZXJzIiwiaWF0IjoxNjk5NDQzMTY1LjcyNjMxNywiZXhwIjoxNjk5NTI5NTY1LjcyNjMxNywic2NvcGUiOiJvcGVuaWQifQ.hpfxFqDtFz3KG0RQEoA0hBNyPbegnwKL76ZGuaGeLmdi7l61-MOfasQZzKTp6blYAspjF_E7N4nzd3al2RFMHQH9PGZznAD9_llKaSq3NRzNgOvabMOgCLxEaWKHcNAyiyo3vvlpHVsQjkhi-dH3V1mpiBxu_jA8EqvdU2w76_7YKxZowa38UddTi6UCXSdx6Psg8k_EIQRNklorDU1YLzPUHctdsbhtbNecstlmCWHwLYV_yc-KrlnH62c_4r1RpIBijtR1GW_nEW_nPQ_JE5iOzudZE78wbb3O6-XMWZzbvIfz03sCA1OwPhWnOhXqxdNLZVkHYJVIulkP-bgx9A"

if len(sys.argv) == 1:
    print("No params passed, using defaults")
    print("public_key.pem file : public_key.pem")
    print("access_token : ", access_token)
elif len(sys.argv) == 3:
    public_key_text = Path(sys.argv[1]).read_text()
    public_key = load_pem_x509_certificate(public_key_text.encode("utf-8")).public_key()
    access_token = sys.argv[2]

try:
    decode = jwt.decode(
        access_token,
        key=public_key,
        algorithms=["RS256"],
        audience=["http://127.0.0.1:8000/orders"],
    )
    print(decode)
except Exception as error:
    print("Decoding error : ", error)
```
</details> 

#### Run Script to check payload jwt
```python jwt_decode.py```

Values should match the ones in `jwt_generator.py`

### Adding authorization to the API server

<details><summary>orders/web/api/auth.py</summary>

```python
from pathlib import Path
import jwt
from cryptography.x509 import load_pem_x509_certificate

public_key_text = (Path(__file__).parent / "../../../public_key.pem").read_text()
public_key = load_pem_x509_certificate(public_key_text.encode()).public_key()

def decode_and_validate_token(access_token):
    """
    Validates an access token. If the token is valid, it returns the token payload.
    """
    return jwt.decode(
        access_token,
        key=public_key,
        algorithms=["RS256"],
        audience=["http:/ /127.0.0.1:8000/orders"],
    )
```
</details>

<details><summary>orders/web/app.py</summary>

```python
import os
from pathlib import Path
import yaml
from fastapi import FastAPI
from jwt import (
    ExpiredSignatureError,
    ImmatureSignatureError,
    InvalidAlgorithmError,
    InvalidAudienceError,
    InvalidKeyError,
    InvalidSignatureError,
    InvalidTokenError,
    MissingRequiredClaimError,
)
from starlette import status
from starlette.middleware.base import (
    RequestResponseEndpoint,
    BaseHTTPMiddleware,
)
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from orders.web.api.auth import decode_and_validate_token

app = FastAPI(debug=True)

class AuthorizeRequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if os.getenv("AUTH_ON", "False") != "True":
            request.state.user_id = "test"
            return await call_next(request)
        if request.url.path in ["/docs/orders", "/openapi/orders.json"]:
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)

        bearer_token = request.headers.get("Authorization")
        if not bearer_token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "detail": "Missing access token",
                    "body": "Missing access token",
                },
            )
        try:
            auth_token = bearer_token.split(" ")[1].strip()
            token_payload = decode_and_validate_token(auth_token)
        except (
            ExpiredSignatureError,
            ImmatureSignatureError,
            InvalidAlgorithmError,
            InvalidAudienceError,
            InvalidKeyError,
            InvalidSignatureError,
            InvalidTokenError,
            MissingRequiredClaimError,
        ) as error:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": str(error), "body": str(error)},
            )
        else:
            request.state.user_id = token_payload["sub"]
        return await call_next(request)
app.add_middleware(AuthorizeRequestMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
from orders.web.api import api
```
</details>



### Check app
- Launch it \
    **CLI:** ```$ AUTH_ON=True uvicorn orders.web.app:app --reload```

    **VSCODE:** add ```"env": {"AUTH_ON": "True"}``` to the *launch.json* config file:
    <details><summary>launch.json</summary>
    ```JSON
        "configurations": [
        {
            "name": "Python: Current File",
            "type": "python",
            "request": "launch",
            "program": "${file}",
            "console": "integratedTerminal",
            "justMyCode": true,
            "env": {
                "AUTH_ON": "True"
            }
        },
    ```
    </details>
    </br>
- Request orders without token \
```$ curl -i http://localhost:8000/orders```
    ```bash
    HTTP/1.1 401 Unauthorized
    date: Wed, 08 Nov 2023 12:04:24 GMT
    server: uvicorn
    content-length: 63
    content-type: application/json

    {"detail":"Missing access token","body":"Missing access token"}
    ```

- Request orders with token (and format with ***jq***)
    <details>

    ```bash
    $ curl http://127.0.0.1:8000/orders -H 'Authorization: Bearerey JhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2F1dGguY29mZmVlbWVzaC5pby8iLCJzdWIiOiJlYzdiYmNjZi1jYTg5LTRhZjMtODJhYy1iNDFlNDgzMWE5NjIiLCJhdWQiOiJodHRwOi8vMTI3LjAuMC4xOjgwMDAvb3JkZXJzIiwiaWF0IjoxNjk5NDQzMTY1LjcyNjMxNywiZXhwIjoxNjk5NTI5NTY1LjcyNjMxNywic2NvcGUiOiJvcGVuaWQifQ.hpfxFqDtFz3KG0RQEoA0hBNyPbegnwKL76ZGuaGeLmdi7l61-MOfasQZzKTp6blYAspjF_E7N4nzd3al2RFMHQH9PGZznAD9_llKaSq3NRzNgOvabMOgCLxEaWKHcNAyiyo3vvlpHVsQjkhi-dH3V1mpiBxu_jA8EqvdU2w76_7YKxZowa38UddTi6UCXSdx6Psg8k_EIQRNklorDU1YLzPUHctdsbhtbNecstlmCWHwLYV_yc-KrlnH62c_4r1RpIBijtR1GW_nEW_nPQ_JE5iOzudZE78wbb3O6-XMWZzbvIfz03sCA1OwPhWnOhXqxdNLZVkHYJVIulkP-bgx9A
    ' | jq
    ```
    </details>
    <details><summary>Output</summary>

    ```json
    {
        "orders": [
            {
            "order": [
                {
                "product": "capuccino",
                "size": "big",
                "quantity": 1
                },
                {
                "product": "latte",
                "size": "medium",
                "quantity": 2
                }
            ],
            "id": "07eae3cb-c73d-4733-b258-cc2d3f4776cf",
            "created": "2023-11-06T16:47:07.812091",
            "status": "created"
            },
            {
            "order": [
                {
                "product": "string",
                "size": "small",
                "quantity": 1
                }
            ],
            "id": "b96d8e0d-f954-4b1e-8c1d-9030b75dd306",
            "created": "2023-11-06T16:48:06.022688",
            "status": "created"
            }
        ]
    }
    ```
    </details>

### Add CORS Middleware
CORS middleware takes care of populating responses with the right information.
In the example wildards are used ("*"), for production that should be defined in a proper way.

```python
# file: orders/app.py
from starlette.middleware.cors import CORSMiddleware
...
app.add_middleware(AuthorizeRequestMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Updating the database to link users and orders

#### Remove current stored orders
Current orders are not associated with a user and will not work after enforcing the association.

```$ python3```
```bash
>>> from orders.repository.orders_repository import OrdersRepository
>>> from orders.repository.unit_of_work import UnitOfWork
>>> with UnitOfWork() as unit_of_work:
    orders_repository = OrdersRepository(unit_of_work.session)
    orders = orders_repository.list()
    for order in orders: orders_repository.delete(order.id)
    unit_of_work.commit()
```

***NOTE:*** Code added in file *clean_database.py*

Adding user ID foreign key to the order table

```python
# file: orders/repository/models.py
class OrderModel(Base):
    __tablename__ = 'order'
    user_id = Column(String, nullable=False)
```

#### Update database schema using Alembic

- Update *migrations/env.py* adding *render_as_batch=True* 

    ```python
    def run_migrations_online() -> None:
        ...
        with connectable.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, render_as_batch=True
            )    
    ```

- Add user id to order table:
    ```bash
    (.venv) $ PYTHONPATH=`pwd` alembic revision --autogenerate -m "Add user id to order table"
    INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
    INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
    INFO  [alembic.autogenerate.compare] Detected added column 'order.user_id'
    Generating /mnt/e/repos/Python/APIs_and_Microservices/04_Securing/migrations/versions/79d8d6d95a81_add_user_id_to_order_table.py ...  done
    ```
- Run migration:
    ```bash
    (.venv) $ PYTHONPATH=`pwd` alembic upgrade heads
    INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
    INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
    INFO  [alembic.runtime.migration] Running upgrade d8aff52545c0 -> 79d8d6d95a81, Add user id to order table
    ```

### Restrict user access to own resources

##### Update api to capture user_id
<details>

```python
# file: orders/web/api/api.py
def create_order(request: Request, payload: CreateOrderSchema):
    order = orders_service.place_order(order, request.state.user_id)

def get_orders(request: Request, cancelled: Optional[bool] = None, limit: Optional[int] = None):
    with UnitOfWork() as unit_of_work:
        results = orders_service.list_orders(limit=limit, cancelled=cancelled, 
            user_id=request.state.user_id
        )

def get_order(request: Request, order_id: UUID):
    try:
        with UnitOfWork() as unit_of_work:        
            order = orders_service.get_order(order_id=order_id, user_id=request.state.user_id)


# file: orders/orders_service/orders_service.py    
class OrdersService:
    def place_order(self, items, user_id):
        return self.orders_repository.add(items, user_id)
    def get_order(self, order_id, **filters):
        order = self.orders_repository.get(order_id, **filters)
# file: orders/repository/orders_repository.py
class OrdersRepository:
    def add(self, items, user_id):
        record = OrderModel(
        items=[OrderItemModel(**item) for item in items],
        user_id=user_id
        )
    def _get(self, id_, **filters):
        return (
        self.session.query(OrderModel)
        .filter(OrderModel.id == str(id_)).filter_by(**filters)
        .first()
        )
        def get(self, id_, **filters):
        order = self._get(id_, **filters)
```
<details>