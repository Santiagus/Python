# FlaskAPI 

This project start from 01_BasicFlaskAPI project (orders and kitchen APIs implementation)


## Initial Setup

**1. Copy 01_BasicFlaskAPI/ to 05_Testing/** \
```cp -R 01_BasicFlaskAPI/ 05_Testing/```

**2. Activate virtual environment** \
```. .venv/bin/activate```

**3. Install dependencies** \
```$ pip install pytest schemathesis dredd_hooks``` \
```$ npm install dredd```

**4. Save requirements** \
```pip freeze > requirements.txt```

**5. Move Open Api Specification File to project root (check inner folders)**
```$ mv /orders/oas.yaml .```

**6. Update references to oas.yaml in the code**
```python
# file: orders/app.py
oas_doc = yaml.safe_load((Path(__file__).parent / "../oas.yaml").read_text())
```
**7. Check simple dreed command** \
```$ ./node_modules/.bin/dredd oas.yaml http://127.0.0.1:8000 --server "uvicorn orders.app:app"```

It will complain about No examples provided in the oas.yaml
```bash
error: API description URI parameters validation error in /mnt/e/repos/Python/APIs_and_Microservices/05_Testing/oas.yaml (Orders API > /orders/{order_id}/pay > Processes payment for an order > 200 > application/json): Required URI parameter 'order_id' has no example or default value.
```

## Implementations

#### Specify examples in oas.yaml (for each order_id parameter in the file):
```yaml
# file: orders/oas.yaml
/orders/{order_id}:
  parameters:
    - in: path
      name: order_id
      required: true
      schema:
        type: string
    example: d222e7a3-6afb-463a-9709-38eb70cc670d
```
output
```bash
...
complete: 7 passing, 12 failing, 0 errors, 0 skipped, 19 total
complete: Tests took 116ms
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [24276]
```

#### Customizing Dredd’s test suite with hooks
<details><summary>orders/hooks.py</summary>

```python
import json
import dredd_hooks
import requests

response_stash = {}

@dredd_hooks.after("/orders > Creates an order > 201 > application/json")
def save_created_order(transaction):
    response_payload = transaction["real"]["body"]
    order_id = json.loads(response_payload)["id"]
    response_stash["created_order_id"] = order_id


@dredd_hooks.before(
    "/orders/{order_id} > Returns the details of a specific order > 200 > "
    "application/json"
)
def before_get_order(transaction):
    transaction["fullPath"] = "/orders/" + response_stash["created_order_id"]
    transaction["request"]["uri"] = "/orders/" + response_stash["created_order_id"]


@dredd_hooks.before(
    "/orders/{order_id} > Replaces an existing order > 200 > " "application/json"
)
def before_put_order(transaction):
    transaction["fullPath"] = "/orders/" + response_stash["created_order_id"]
    transaction["request"]["uri"] = "/orders/" + response_stash["created_order_id"]


@dredd_hooks.before("/orders/{order_id} > Deletes an existing order > 204")
def before_delete_order(transaction):
    transaction["fullPath"] = "/orders/" + response_stash["created_order_id"]
    transaction["request"]["uri"] = "/orders/" + response_stash["created_order_id"]


@dredd_hooks.before(
    "/orders/{order_id}/pay > Processes payment for an order > 200 > "
    "application/json"
)
def before_pay_order(transaction):
    response = requests.post(
        "http://127.0.0.1:8000/orders",
        json={"order": [{"product": "string", "size": "small", "quantity": 1}]},
    )
    id_ = response.json()["id"]
    transaction["fullPath"] = "/orders/" + id_ + "/pay"
    transaction["request"]["uri"] = "/orders/" + id_ + "/pay"


@dredd_hooks.before(
    "/orders/{order_id}/cancel > Cancels an order > 200 > application/json"
)
def before_cancel_order(transaction):
    response = requests.post(
        "http://127.0.0.1:8000/orders",
        json={"order": [{"product": "string", "size": "small", "quantity": 1}]},
    )
    id_ = response.json()["id"]
    transaction["fullPath"] = "/orders/" + id_ + "/cancel"
    transaction["request"]["uri"] = "/orders/" + id_ + "/cancel"


@dredd_hooks.before("/orders > Creates an order > 422 > application/json")
def fail_create_order(transaction):
    transaction["request"]["body"] = json.dumps(
        {"order": [{"product": "string", "size": "asdf"}]}
    )


@dredd_hooks.before(
    "/orders/{order_id} > Returns the details of a specific order > 422 > "
    "application/json"
)
@dredd_hooks.before(
    "/orders/{order_id}/cancel > Cancels an order > 422 > application/json"
)
@dredd_hooks.before(
    "/orders/{order_id}/pay > Processes payment for an order > 422 > "
    "application/json"
)
@dredd_hooks.before(
    "/orders/{order_id} > Replaces an existing order > 422 > " "application/json"
)
@dredd_hooks.before(
    "/orders/{order_id} > Deletes an existing order > 422 > " "application/json"
)
def fail_target_specific_order(transaction):
    transaction["fullPath"] = transaction["fullPath"].replace(
        "d222e7a3-6afb-463a-9709-38eb70cc670d", "8"
    )
    transaction["request"]["uri"] = transaction["request"]["uri"].replace(
        "d222e7a3-6afb-463a-9709-38eb70cc670d", "8"
    )
```
</details>

#### RUNNING DREDD WITH CUSTOM HOOKS

```./node_modules/.bin/dredd oas.yaml http://127.0.0.1:8000 --server "uvicorn orders.app:app" --hookfiles=orders/hooks.py --language=python```

***NOTE:*** Check URLs in hooks.py, oas.yaml and command are all using same one (127.0.0.1 | localhost)

It's possible a timeout error to appear if server takes a bit to start up.
```error: Connection timeout 1.5s to hooks handler on 127.0.0.1:61321 exceeded. Try increasing the limit.```

In that case try:
- Run again the same command
- Start the server in a separate command and then run dredd (check server is up befor running dredd)


output

```bash
...
pass: POST (404) /orders/d222e7a3-6afb-463a-9709-38eb70cc670d/cancel duration: 100ms
INFO:     127.0.0.1:54120 - "POST /orders/8/cancel HTTP/1.1" 422 Unprocessable Entity
pass: POST (422) /orders/d222e7a3-6afb-463a-9709-38eb70cc670d/cancel duration: 100ms
complete: 18 passing, 0 failing, 0 errors, 0 skipped, 18 total
complete: Tests took 3904ms
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [31376]
```