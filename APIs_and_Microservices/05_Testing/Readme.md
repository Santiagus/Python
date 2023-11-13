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

## Property-based testing with Hypothesis

This approach uses hypothesis framework to generate all possible types of payloads and test them against our API server.


Create *orders/test.py*
<details><summary>orders/test.py</summary>

```python
from pathlib import Path
import hypothesis.strategies as st
import jsonschema
import yaml
from fastapi.testclient import TestClient
from hypothesis import given, Verbosity, settings
from jsonschema import ValidationError, RefResolver
from orders.app import app

orders_api_spec = yaml.full_load((Path(__file__).parent / "oas.yaml").read_text())
create_order_schema = orders_api_spec["components"]["schemas"]["CreateOrderSchema"]

def is_valid_payload(payload, schema):
    try:
        jsonschema.validate(
            payload, schema=schema, resolver=RefResolver("", orders_api_spec)
        )
    except ValidationError:
        return False
    else:
        return True

test_client = TestClient(app=app)
values_strategy = [...]
order_item_strategy = [...]
strategy = [...]

@given(strategy)
def test(payload):
    response = test_client.post("/orders", json=payload)
    if is_valid_payload(payload, create_order_schema):
        assert response.status_code == 201
    else:
        assert response.status_code == 422
```
</details>
</br>

**1. Run server in background (or just other terminal)** \
```$ uvicorn orders.app:app --reload --log-level trace &```
**2. Run schemathesis** \
```$ schemathesis run oas.yaml --base-url=http://127.0.0.1:8000 --hypothesis-database=none```

<details><summary>output</summary>

```bash
============= Schemathesis test session starts =============
Schema location: file:///05_Testing/oas.yaml
Base URL: http://127.0.0.1:8000
Specification version: Open API 3.0.3
Workers: 1
Collected API operations: 7

GET /orders .                                         [ 14%]
POST /orders .                                        [ 28%]
GET /orders/{order_id} .                              [ 42%]
PUT /orders/{order_id} .                              [ 57%]
DELETE /orders/{order_id} .                           [ 71%]
POST /orders/{order_id}/pay .                         [ 85%]
POST /orders/{order_id}/cancel .                      [100%]

========================== SUMMARY ==========================

Performed checks:
    not_a_server_error                    705 / 705 passed          PASSED
Tip: Use the `--report` CLI option to visualize test results via Schemathesis.io.
We run additional conformance checks on reports from public repos.
```
</details>
</br>


**NOTES:**

Hypothesis caches some test in *.hypothesis/* folder that causes misleading results in subsequent test executions.

Set the --hypothesisdatabase flag to none makes Schemathesis to not cache test cases.

### Add links in oas.yaml

<details><summary>oas_with_links.yaml</summary>

```yaml
  /orders:
    get:
      parameters:
      - name: cancelled
        in: query
        required: false
        schema:
          type: boolean
      - name: limit
        in: query
        required: false
        schema:
          type: integer
      summary: Returns a list of orders
      operationId: getOrders
      description: >
        A list of orders made by the customer
        sorted by date. Allows to filter orders
        by range of dates.
      responses:
        '200':
          description: A JSON array of orders
          content:
            application/json:
              schema:
                type: object
                additionalProperties: false
                properties:
                  orders:
                    type: array
                    items:
                      $ref: '#/components/schemas/GetOrderSchema'
          links:
            GetOrder:
              operationId: getOrder
              parameters:
                order_id: '$response.body#/id'
              description: >
                The `id` value returned in the response can be used as
                the `order_id` parameter in `GET /orders/{order_id}`
                        UpdateOrder:
              operationId: updateOrder
              parameters:
                order_id: '$response.body#/id'
              description: >
                The `id` value returned in the response can be used as
                the `order_id` parameter in `PUT /orders/{order_id}
            DeleteOrder:
              operationId: deleteOrder
              parameters:
                order_id: '$response.body#/id'
              description: >
                The `id` value returned in the response can be used as
                the `order_id` parameter in `DELETE /orders/{order_id}
            CancelOrder:
              operationId: cancelOrder
              parameters:
                order_id: '$response.body#/id'
              description: >
                The `id` value returned in the response can be used as
                the `order_id` parameter in `DELETE /orders/{order_id}/cancel
            PayOrder:
              operationId: payOrder
              parameters:
                order_id: '$response.body#/id'
              description: >
                The `id` value returned in the response can be used as
                the `order_id` parameter in `DELETE /orders/{order_id}/pay
```
</details>

<details><summary>output</summary>

```bash
================== Schemathesis test session starts ==================
Schema location: file:///mnt/e/repos/Python/APIs_and_Microservices/05_Testing/oas_with_links.yaml
Base URL: http://127.0.0.1:8000
Specification version: Open API 3.0.3
Workers: 1
Collected API operations: 7

GET /orders .                                           [ 14%]
    -> PUT /orders/{order_id} .                         [ 25%]
    -> DELETE /orders/{order_id} .                      [ 33%]
    -> POST /orders/{order_id}/cancel .                 [ 40%]
    -> POST /orders/{order_id}/pay .                    [ 45%]
POST /orders .                                          [ 54%]
GET /orders/{order_id} .                                [ 63%]
PUT /orders/{order_id} .                                [ 72%]
DELETE /orders/{order_id} .                             [ 81%]
POST /orders/{order_id}/pay .                           [ 90%]
POST /orders/{order_id}/cancel .                        [100%]
=============================== SUMMARY ===============================

Performed checks:
    not_a_server_error                    1109 / 1109 passed          PASSED 

Tip: Use the `--report` CLI option to visualize test results via Schemathesis.io.
We run additional conformance checks on reports from public repos.
```
</details>

To save a report use the flag `--report [file.tar.gz]`

`schemathesis run oas_with_links.yaml --base-url=http://127.0.0.1:8000 --stateful=links --report report_file.tar.gz`

This test indicates that our API passed all checks in the not_a_
server_error category. By default, Schemathesis only checks that the API doesn’t raise server errors.

To also verify status codes, content types, headers, and schemas use the `--checks all`:
```schemathesis run oas_with_links.yaml --base-url=http://127.0.0.1:8000 --hypothesis-database=none --stateful=links --checks all --report report_file.tar.gz```

***NOTES:***

Somehow testcases with *Authorization: Bearer* causes problems when running the test but when testing the equivalent CURL command indicated in the output it works without any problem. To solve this a value for that header has to be provided from the command. 
```-H 'Authorization: Bearer  '```

Used command:
```schemathesis run oas_with_links.yaml --base-url=http://127.0.0.1:8000 --stateful=links --checks all --validate-schema True --hypothesis-derandomize --fixups fast_api --sanitize-output False -H 'Authorization: Bearer '```

<details><summary>output</summary>

```bash
================================ Schemathesis test session starts ===============================
Schema location: file:///mnt/e/repos/Python/APIs_and_Microservices/05_Testing/oas_with_links.yaml
Base URL: http://127.0.0.1:8000
Specification version: Open API 3.0.3
Workers: 1
Collected API operations: 7

GET /orders .                                                                              [ 14%]
POST /orders .                                                                             [ 28%]
    -> PUT /orders/{order_id} .                                                            [ 37%]
    -> DELETE /orders/{order_id} .                                                         [ 44%]
    -> POST /orders/{order_id}/cancel .                                                    [ 50%]
    -> POST /orders/{order_id}/pay .                                                       [ 54%]
GET /orders/{order_id} .                                                                   [ 63%]
PUT /orders/{order_id} .                                                                   [ 72%]
DELETE /orders/{order_id} .                                                                [ 81%]
POST /orders/{order_id}/pay .                                                              [ 90%]
POST /orders/{order_id}/cancel .                                                           [100%]
=============================================== SUMMARY =========================================

Performed checks:
    not_a_server_error                              1109 / 1109 passed          PASSED
    status_code_conformance                         1109 / 1109 passed          PASSED
    content_type_conformance                        1109 / 1109 passed          PASSED
    response_headers_conformance                    1109 / 1109 passed          PASSED
    response_schema_conformance                     1109 / 1109 passed          PASSED

Tip: Use the `--report` CLI option to visualize test results via Schemathesis.io.
We run additional conformance checks on reports from public repos.

========================================= 11 passed in 11.24s ===================================
```
</details>