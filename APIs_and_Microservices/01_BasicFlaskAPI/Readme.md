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

    oas_doc = yaml.safe_load((Path(__file__).parent / './oas.yaml').read_text())

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


#### Update paths where FastAPI server the APIs

- orders/orders/app.py

```python
    app = FastAPI(debug=True, openapi_url='/openapi/orders.json', docs_url='/docs/orders')
```

#### Complete Open Api Specification
<details><summary>orders/oas.yaml</summary>

```yaml
openapi: 3.0.3

info:
  title: Orders API
  description: API that allows you to manage orders for CoffeeMesh
  version: 1.0.0

servers:
  - url: http://localhost:8000
    description: local development server
  - url: https://coffeemesh.com
    description: main production server
  - url: https://coffeemesh-staging.com
    description: staging server for testing purposes only

paths:
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
        '422':
          $ref: '#/components/responses/UnprocessableEntity'

    post:
      summary: Creates an order
      operationId: createOrder
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateOrderSchema'
      responses:
        '201':
          description: A JSON representation of the created order
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/GetOrderSchema'
        '422':
          $ref: '#/components/responses/UnprocessableEntity'

  /orders/{order_id}:
    parameters:
      - in: path
        name: order_id
        required: true
        schema:
          type: string
          format: uuid
    get:
      summary: Returns the details of a specific order
      operationId: getOrder
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/GetOrderSchema'
        '404':
          $ref: '#/components/responses/NotFound'
        '422':
          $ref: '#/components/responses/UnprocessableEntity'

    put:
      summary: Replaces an existing order
      operationId: updateOrder
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateOrderSchema'
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref:  '#/components/schemas/GetOrderSchema'
        '404':
          $ref: '#/components/responses/NotFound'
        '422':
          $ref: '#/components/responses/UnprocessableEntity'

    delete:
      summary: Deletes an existing order
      operationId: deleteOrder
      responses:
        '204':
          description: The resource was deleted successfully
        '404':
          $ref: '#/components/responses/NotFound'
        '422':
          $ref: '#/components/responses/UnprocessableEntity'

  /orders/{order_id}/pay:
    parameters:
      - in: path
        name: order_id
        required: true
        schema:
          type: string
          format: uuid
    post:
      summary: Processes payment for an order
      operationId: payOrder
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/GetOrderSchema'
        '404':
          $ref: '#/components/responses/NotFound'
        '422':
          $ref: '#/components/responses/UnprocessableEntity'


  /orders/{order_id}/cancel:
    parameters:
      - in: path
        name: order_id
        required: true
        schema:
          type: string
          format: uuid
    post:
      summary: Cancels an order
      operationId: cancelOrder
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/GetOrderSchema'
        '404':
          $ref: '#/components/responses/NotFound'
        '422':
          $ref: '#/components/responses/UnprocessableEntity'

components:
  responses:
    NotFound:
      description: The specified resource was not found.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
    UnprocessableEntity:
      description: The payload contains invalid values.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'

  securitySchemes:
    openId:
      type: openIdConnect
      openIdConnectUrl: https://coffeemesh-dev.eu.auth0.com/.well-known/openid-configuration
    oauth2:
      type: oauth2
      flows:
        clientCredentials:
          tokenUrl: https://coffeemesh-dev.eu.auth0.com/oauth/token
          scopes: {}
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT

  schemas:
    Error:
      type: object
      properties:
        detail:
          oneOf:
            - type: string
            - type: array
      required:
        - detail
      additionalProperties: false

    OrderItemSchema:
      additionalProperties: false
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
          format: int64
          default: 1
          minimum: 1
          maximum: 1000000

    CreateOrderSchema:
      additionalProperties: false
      type: object
      required:
        - order
      properties:
        order:
          type: array
          minItems: 1
          items:
            $ref: '#/components/schemas/OrderItemSchema'

    GetOrderSchema:
      additionalProperties: false
      type: object
      required:
        - id
        - created
        - updated
        - status
        - order
      properties:
        id:
          type: string
          format: uuid
        created:
          type: string
          format: date-time
        status:
          type: string
          enum:
            - created
            - updated
            - paid
            - progress
            - cancelled
            - dispatched
            - delivered
        order:
          type: array
          minItems: 1
          items:
            $ref: '#/components/schemas/OrderItemSchema'

security:
  - oauth2:
      - getOrders
      - createOrder
      - getOrder
      - updateOrder
      - deleteOrder
      - payOrder
      - cancelOrder
  - bearerAuth:
      - getOrders
      - createOrder
      - getOrder
      - updateOrder
      - deleteOrder
      - payOrder
      - cancelOrder
```
</details>
</br>

## Notes:
Check Request URL (Eg.: http://localhost:8000/orders) in Swagger UI match the URL used to access the API (http://localhost:8000/docs/orders). Both must be *localhost* or *127.0.0.1* to avoid the following error:

```
Undocumented
Failed to fetch.
Possible Reasons:

CORS
Network Failure
URL scheme must be "http" or "https" for CORS request.
```

## Flask app Initialization

From this points proceed with the equivalent to ***orders*** implementation with FastAPI but using ***Flask***

#### Create kitchen folder
```mkdir kitchen```

#### Create First Flask app file
<details><summary>kitchen/app.py</summary>

```python
from flask import Flask
from flask_smorest import Api

app = Flask(__name__)

@app.route("/")
def index():
    return "Index Page"

@app.route("/hello")
def hello():
    return "Hello, World"
```
</details>

#### Run App:
Terminal Command: \
```flask --app kitchen.app --debug run --port 9000```

VSCode config:

<details><summary>launch.json</summary>

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Flask",
            "type": "python",
            "pythonArgs": [
                "-Xfrozen_modules=off"
            ],
            "request": "launch",
            "module": "flask",
            "args": [
                "--app",
                "kitchen.app",
                "--debug",
                "run",
                "--port",
                "9000",
            ],
            "jinja": true,
            "justMyCode": true,
        }
    ]
}
```
</details>
</br>

App should be running on http://127.0.0.1:9000 \
and showing "Hello, World" at http://127.0.0.1:9000/hello

#### Set configuration for the Kitchen API

<details><summary>kitchen/config.py</summary>

```python
class BaseConfig:
    API_TITLE = 'Kitchen API'
    API_VERSION = 'v1'
    OPENAPI_VERSION = '3.0.3'
    OPENAPI_JSON_PATH = 'openapi/kitchen.json'
    OPENAPI_URL_PREFIX = '/'
    OPENAPI_REDOC_PATH = '/redoc'
    OPENAPI_REDOC_URL = 'https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js'
    OPENAPI_SWAGGER_UI_PATH = '/docs/kitchen'
    OPENAPI_SWAGGER_UI_URL = 'https://cdn.jsdelivr.net/npm/swagger-ui-dist/'
```
</details>

#### Load configuration *kitcken/app.py*
```python
from flask import Flask
from flask_smorest import Api
from kitchen.config import BaseConfig

app = Flask(__name__)
app.config.from_object(BaseConfig)
kitchen_api = Api(app)
```

## Implement endpoints

#### Simple cases : Route decorator
```python
@app.route('/orders')
def process
  pass
```
#### Complex cases: Flask Blueprints
It allows to provide specific configuratin for a group of URLs
```python
@blueprint.route('/info')
def get_info():
  pass
```

#### Multiple method cases : Route decorator
When a URL exposes multiple HTTP methods (GET, POST, PUT, DELETE) use class-based routes using MethodView. Each method is a class function:

```python
class Kitchen(MethodView):
  def get(self):
    pass
  def post(self):
    pass
```

## Kitchen API Implementation

Register blueprint with API object ***kitcken/app.py***
```python
from kitchen.api.api import blueprint
kitchen_api.register_blueprint(blueprint)
```

Implement Get schedules ***/kitchen/schedules*** endpoint
<details><summary>kitchen/api/api.py</summary>

```python
from urllib.parse import scheme_chars
import uuid
from datetime import datetime

from flask.views import MethodView
from flask_smorest import Blueprint

blueprint = Blueprint("kitchen", __name__, description="Kitchen API")

# hardcoded schedules list
schedules = [
    {
        "id": str(uuid.uuid4()),
        "scheduled": datetime.now(),
        "status": "pending",
        "order": [{"product": "capuccino", "quantity": 1, "size": "big"}],
    }
]

@blueprint.route("/kitchen/schedules")
class KitchenSchedules(MethodView):
    def get(self):
        return {"schedules": schedules}, 200

```
</details>
</br>

Check kitchen api at http://127.0.0.1:9000/docs/kitchen \
(specified at ***config.py*** file)

#### Implement resting endpoints

<details><summary>kitchen/api/api.py</summary>

```python
@blueprint.route("/kitchen/schedules")
class KitchenSchedules(MethodView):
    def get(self):
        return {"schedules": schedules}, 200

    def post(self, payload):
        return schedules[0], 201


@blueprint.route("/kitchen/schedules/<schedule_id>")
class KitchenSchedule(MethodView):
    def get(self, schedule_id):
        return schedules[0], 200

    def put(self, payload, schedule_id):
        return schedules[0], 200

    def delete(self, schedule_id):
        return "", 204

@blueprint.route("/kitchen/schedules/<schedule_id>/cancel", methods=["POST"])
def cancel_schedule(schedule_id):
    return schedules[0], 200


@blueprint.route("/kitchen/schedules/<schedule_id>/status", methods=["GET"])
def get_schedule_status(schedule_id):
    return schedules[0], 200

```
</details>
</br>

### Adding validation to the API endpoints
Schema definitions for the orders API
<details><summary>kitchen/api/schemas.py</summary>

```python
from dataclasses import field
from itertools import product
from operator import truediv
from typing import Required
from marshmallow import Schema, fields, validate, EXCLUDE


class OrderItemSchema(Schema):
    # Meta class to ban unknown properties
    class Meta:
        unknown = EXCLUDE

    product = fields.String(required=True)
    size = fields.String(
        required=True, validate=validate.OneOf(["small", "medium", "big"])
    )
    quantity = fields.Integer(
        validate=validate.Range(1, min_inclusive=True), required=True
    )


class ScheduleOrderSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    order = fields.List(fields.Nested(OrderItemSchema), required=True)


class GetScheduledOrderSchema(ScheduleOrderSchema):
    id = fields.UUID(required=True)
    scheduled = fields.DateTime(required=True)
    status = fields.String(
        required=True,
        validate=validate.OneOf(["pending", "progress", "cancelled", "finished"]),
    )


class GetScheduledOrdersSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    schedules = fields.List(fields.Nested(GetScheduledOrderSchema), required=True)


class ScheduleStatusSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    status = fields.String(
        required=True,
        validate=validate.OneOf(["pending", "progress", "cancelled", "finished"]),
    )
```
</details>
</br>

Adding validation to the API endpoints
<details><summary>kitchen/api/api.py</summary>

```python
from urllib.parse import scheme_chars
import uuid
from datetime import datetime

from flask.views import MethodView
from flask_smorest import Blueprint

# Marshmallow models
from kitchen.api.schemas import (
    GetScheduledOrderSchema,
    ScheduleOrderSchema,
    GetScheduledOrdersSchema,
    ScheduleStatusSchema,
)

blueprint = Blueprint("kitchen", __name__, description="Kitchen API")

# hardcoded schedules list
schedules = [
    {
        "id": str(uuid.uuid4()),
        "scheduled": datetime.now(),
        "status": "pending",
        "order": [{"product": "capuccino", "quantity": 1, "size": "big"}],
    }
]


@blueprint.route("/kitchen/schedules")
class KitchenSchedules(MethodView):
    @blueprint.response(status_code=200, schema=GetScheduledOrdersSchema)
    def get(self):
        # return {"schedules": schedules}, 200
        return {"schedules": schedules}

    @blueprint.arguments(ScheduleOrderSchema)
    @blueprint.response(status_code=201, schema=GetScheduledOrderSchema)
    def post(self, payload):
        # return schedules[0], 201
        return schedules[0]


@blueprint.route("/kitchen/schedules/<schedule_id>")
class KitchenSchedule(MethodView):
    @blueprint.response(status_code=200, schema=GetScheduledOrderSchema)
    def get(self, schedule_id):
        # return schedules[0], 200
        return schedules[0]

    @blueprint.arguments(ScheduleOrderSchema)
    @blueprint.response(status_code=200, schema=GetScheduledOrderSchema)
    def put(self, payload, schedule_id):
        # return schedules[0], 200
        return schedules[0]

    @blueprint.response(status_code=204)
    def delete(self, schedule_id):
        # return "", 204
        return


@blueprint.response(status_code=200, schema=GetScheduledOrderSchema)
@blueprint.route("/kitchen/schedules/<schedule_id>/cancel", methods=["POST"])
def cancel_schedule(schedule_id):
    # return schedules[0], 200
    return schedules[0]


@blueprint.response(status_code=200, schema=ScheduleStatusSchema)
@blueprint.route("/kitchen/schedules/<schedule_id>/status", methods=["GET"])
def get_schedule_status(schedule_id):
    # return schedules[0], 200
    return schedules[0]
```
</details>
</br>

Check Swagger UI now shows schema for the request and sample payloads based on schema: \
 ***http://127.0.0.1:9000/docs/kitchen***


### Validating URL query parameters

Register schema

```python
class GetKitchenScheduleParameters(Schema):
    class Meta:
        unknown = EXCLUDE

    progress = fields.Boolean()
    limit = fields.Integer()
    since = fields.DateTime()
```

Adding URL query parameters to GET /kitchen/schedules
<details><summary>kitchen/api/api.py</summary>

```python
@blueprint.route("/kitchen/schedules")
class KitchenSchedules(MethodView):
    @blueprint.arguments(GetKitchenScheduleParameters, location="query")
    @blueprint.response(status_code=200, schema=GetScheduledOrdersSchema)
    def get(self, parameters):
        if not parameters:
            return {"schedules": schedules}

        query_set = [schedule for schedule in schedules]

        # Filter by progress
        in_progress = parameters.get("progress")
        if in_progress is not None:
            if in_progress:
                query_set = [
                    schedule
                    for schedule in query_set
                    if schedule["status"] == "progress"
                ]
            else:
                query_set = [
                    schedule
                    for schedule in query_set
                    if schedule["status"] != "progress"
                ]

        # Filter by date
        since = parameters.get("since")
        if since is not None:
            query_set = [
                schedule for schedule in query_set if schedule["scheduled"] >= since
            ]

        # Filter by limit
        limit = parameters.get("limit")
        if limit is not None and len(query_set) > limit:
            query_set = query_set[:limit]

        return {"schedules": query_set}
```
</details>
</br>

***NOTE:*** schedules is a harcoded value by now, add some values and play around with filters in Swagger UI


#### Validating data before serialization
<details><summary>kitchen/api/api.py</summary>

```python
# file: kitchen/api/api.py
import copy
from marshmallow import ValidationError
...
@blueprint.route('/kitchen/schedules')
class KitchenSchedules(MethodView):
  @blueprint.arguments(GetKitchenScheduleParameters, location='query')
  @blueprint.response(status_code=200, schema=GetScheduledOrdersSchema)
  def get(self, parameters):
    for schedule in schedules:
      schedule = copy.deepcopy(schedule)
      schedule['scheduled'] = schedule['scheduled'].isoformat()
      errors = GetScheduledOrderSchema().validate(schedule)
      if errors:
        raise ValidationError(errors)
  ...
  return {'schedules': query_set}
```
</details>
</br>

***NOTE:*** In Marshmallow, there isn't a built-in way to validate an entire list of objects in one step using a schema.


## In memory implementation

Refactor schedule validation
```python
# Data validation code refactored to function
def validate_schedule(schedule):
    schedule = copy.deepcopy(schedule)
    schedule["scheduled"] = schedule["scheduled"].isoformat()
    errors = GetScheduledOrderSchema().validate(schedule)
    if errors:
        raise ValidationError(errors)
```

Modify schedules in-memory list when using endpoints
</br>

<details><summary>kitchen/api/api.py</summary>

```python
@blueprint.route("/kitchen/schedules")
class KitchenSchedules(MethodView):
...
    @blueprint.arguments(ScheduleOrderSchema)
    @blueprint.response(status_code=201, schema=GetScheduledOrderSchema)
    def post(self, payload):
        payload["id"] = str(uuid.uuid4())
        payload["scheduled"] = datetime.now()
        payload["status"] = "pending"
        schedules.append(payload)
        validate_schedule(payload)
        return payload

@blueprint.route("/kitchen/schedules/<schedule_id>")
class KitchenSchedule(MethodView):
    @blueprint.response(status_code=200, schema=GetScheduledOrderSchema)
    def get(self, schedule_id):
        for schedule in schedules:
            if schedule["id"] == schedule_id:
                validate_schedule(schedule)
                return schedule
        abort(404, description=f"Resource with ID {schedule_id} not found")

    @blueprint.arguments(ScheduleOrderSchema)
    @blueprint.response(status_code=200, schema=GetScheduledOrderSchema)
    def put(self, payload, schedule_id):
        for schedule in schedules:
            if schedule["id"] == schedule_id:
                schedule.update(payload)
                validate_schedule(schedule)
                return schedule
        abort(404, description=f"Resource with ID {schedule_id} not found")

    @blueprint.response(status_code=204)
    def delete(self, schedule_id):
        for index, schedule in enumerate(schedules):
            if schedule["id"] == schedule_id:
                schedules.pop(index)
                return
        abort(404, description=f"Resource with ID {schedule_id} not found")

@blueprint.response(status_code=200, schema=GetScheduledOrderSchema)
@blueprint.route("/kitchen/schedules/<schedule_id>/cancel", methods=["POST"])
def cancel_schedule(schedule_id):
    for schedule in schedules:
        if schedule["id"] == schedule_id:
            schedule["status"] = "cancelled"
            validate_schedule(schedule)
            return schedule
    abort(404, description=f"Resource with ID {schedule_id} not found")

@blueprint.response(status_code=200, schema=ScheduleStatusSchema)
@blueprint.route("/kitchen/schedules/<schedule_id>/status", methods=["GET"])
def get_schedule_status(schedule_id):
    for schedule in schedules:
        if schedule["id"] == schedule_id:
            validate_schedule(schedule)
            return {"status": schedule["status"]}
    abort(404, description=f"Resource with ID {schedule_id} not found")
```
</details>

### Overriding flask-smorest’s dynamically generated API specification

Install pyyaml

```pipenv install pyyaml```

Override the API object’s spec property with a custom APISpec object.

<details><summary>kitchen/app.py</summary>

```python
from pathlib import Path
import yaml
from apispec import APISpec
...
api_spec = yaml.safe_load((Path(__file__).parent / "oas.yaml").read_text())
spec = APISpec(
    title=api_spec["info"]["title"],
    version=api_spec["info"]["version"],
    openapi_version=api_spec["openapi"],
)
spec.to_dict = lambda: api_spec
kitchen_api.spec = spec
```
</details>