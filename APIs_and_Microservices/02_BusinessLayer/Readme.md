# Business layer of a microservice

This project start from the previous one, it will be reorganice to create a Data Layer and a Business layer.

## Setup

```bash
$ python -m venv .venv                              # Create virtual environment 
$ . .venv/bin/activate                              # Activate venv
(.venv) $ cp ../01_BasicFlaskAPI/requirements.txt . # Copy requirements file
(.venv) $ pip install -r requirements.txt           # Install depencencies
```

## Reorganization

```bash
└── orders
    ├── oas.yaml            # Orders Open API Specification
    ├── kitchen.yaml        # Kitchen orders Open API Specification
    ├── orders_service      # business layer
    ├── repository          # data layer
    └── web                 # web adapters
        ├── api             # Rest API implementation
        │    ├── api.py
        │    └── schemas.py
        └── app.py          # web server
```
#### Update references where needed according to the new structure
**orders/web/app.py**
```
from orders.web.api import api
oas_doc = yaml.safe_load((Path(__file__).parent / "../../oas.yaml").read_text())
```

**orders/web/api/api.py**
```
from orders.web.app import app
from orders.web.api.schemas import (GetOrderSchema, CreateOrderSchema, GetOrdersSchema, )
```

#### Test service
```uvicorn orders.web.app:app```

### Implementing the database models
Install:
- ***SQLAlchemy*** : ORM (object relational mapper) that implements the data mapper pattern,
which allows us to map the tables in our database to objects.
- ***Alembic*** : schema migration librery that integrates with SQLAlchemy

```(.venv) $ pip install sqlalchemy alembic```

Create migrations folder \
```(.venv) 02_BusinessLayer $ alembic init migrations```

Update ***alembic.ini*** \
```sqlalchemy.url = sqlite:///orders.db```

Add model's MetaData in **orders/migrations/env.py**:
```python
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
# target_metadata = None
from orders.repository.models import Base
target_metadata = Base.metadata
```

Create models:
<details><summary>repository/models.py</summary>

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


def generate_uuid():
    return str(uuid.uuid4())


class OrderModel(Base):
    __tablename__ = "order"
    id = Column(String, primary_key=True, default=generate_uuid)
    items = relationship("OrderItemModel", backref="order")
    status = Column(String, nullable=False, default="created")
    created = Column(DateTime, default=datetime.utcnow)
    schedule_id = Column(String)
    delivery_id = Column(String)

    def dict(self):
        return {
            "id": self.id,
            "items": [item.dict() for item in self.items],
            "status": self.status,
            "created": self.created,
            "schedule_id": self.schedule_id,
            "delivery_id": self.delivery_id,
        }


class OrderItemModel(Base):
    __tablename__ = "order_item"
    id = Column(String, primary_key=True, default=generate_uuid)
    order_id = Column(Integer, ForeignKey("order.id"))
    product = Column(String, nullable=False)
    size = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)

    def dict(self):
        return {
            "id": self.id,
            "product": self.product,
            "size": self.size,
            "quantity": self.quantity,
        }
```
</details>


Apply models to the database:

```(.venv) /02_BusinessLayer $ PYTHONPATH=`pwd` alembic revision --autogenerate -m 
"Initial migration"```

```bash
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.autogenerate.compare] Detected added table 'order'
INFO  [alembic.autogenerate.compare] Detected added table 'order_item'
  Generating /02_BusinessLayer/migrations/versions/d8aff52545c0_initial_migration.py ...  done
```

Apply the migrations and create the schemas for these models in the database \

```$ PYTHONPATH=`pwd` alembic upgrade heads``` 

```bash
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> d8aff52545c0, Initial migration
```

### Implementing the repository pattern
<details><summary>orders/repository/orders_repository.py</summary>

```python
from orders.orders_service.orders import Order
from orders.repository.models import OrderModel, OrderItemModel

class OrdersRepository:
    def __init__(self, session):
        self.session = session

    def add(self, items):
        record = OrderModel(items=[OrderItemModel(**item) for item in items])
        self.session.add(record)
        return Order(**record.dict(), order_=record)

    def _get(self, id_):
        return (
            self.session.query(OrderModel)
            .filter(OrderModel.id == str(id_))
            .filter_by(**filters)
            .first()
        )

    def get(self, id_):
        order = self._get(id_)
        if order is not None:
            return Order(**order.dict())

    def list(self, limit=None, **filters):
        query = self.session.query(OrderModel)
        if "cancelled" in filters:
            cancelled = filters.pop("cancelled")
            if cancelled:
                query = query.filter(OrderModel.status == "cancelled")
            else:
                query = query.filter(OrderModel.status != "cancelled")
        records = query.filter_by(**filters).limit(limit).all()
        return [Order(**record.dict()) for record in records]

    def update(self, id_, **payload):
        record = self._get(id_)
        if "items" in payload:
            for item in record.items:
                self.session.delete(item)
            record.items = [OrderItemModel(**item) for item in payload.pop("items")]
        for key, value in payload.items():
            setattr(record, key, value)
        return Order(**record.dict())

    def delete(self, id_):
        self.session.delete(self._get(id_))
```
</details>

<details><summary>orders/orders_service/orders_service.py</summary>

```python
class OrdersService:
    def __init__(self, orders_repository):
        self.orders_repository = orders_repository

    def place_order(self, items):
        pass

    def get_order(self, order_id):
        pass

    def update_order(self, order_id, items):
        pass

    def list_orders(self, **filters):
        pass

    def pay_order(self, order_id):
        pass

    def cancel_order(self, order_id):
        pass
```
</details>
<details><summary>orders/orders_service/orders.py</summary>

```python
# file: orders/orders_service/orders.py
class OrderItem:
    def __init__(self, id, product, quantity, size):
        self.id = id
        self.product = product
        self.quantity = quantity
        self.size = size


class Order:
    def __init__(self, id, created, items, status, schedule_id=None,
        delivery_id=None, order_=None,
    ):
        self._id = id
        self._created = created
        self.items = [OrderItem(**item) for item in items]
        self._status = status
        self.schedule_id = schedule_id
        self.delivery_id = delivery_id

    @property
    def id(self):
        return self._id or self._order.id

    @property
    def created(self):
        return self._created or self._order.created

    @property
    def status(self):
        return self._status or self._order.status
```
</details>


#### Install yarn (and dependencies - NodeJS -)
```bash
sudo apt update
sudo apt upgrade
sudo apt install nodejs npm -y
sudo apt-get install yarnpkg
```
Check versions
```
(.venv) $ node -v
v18.13.0
(.venv) $ npm -v
9.2.0
(.venv) $ yarnpkg --version
1.22.19
(.venv) $ lsb_release -a
No LSB modules are available.
Distributor ID: Debian
Description:    Debian GNU/Linux trixie/sid
Release:        n/a
Codename:       trixie
```
#### Install Prism CLI
```yarnpkg add @stoplight/prism-cli```

#### Run Prism with kitchen API
```./node_modules/.bin/prism mock kitchen.yaml --port 3000```

#### Install jq - commandline JSON processor
```sudo apt install jq```

#### Check response parsing it with jq to get a beautiful display
```curl http://localhost:3000/kitchen/schedules | jq```
<details>

```JSON
{
  "schedules": [
    {
      "id": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
      "scheduled": "2019-08-24T14:15:22Z",
      "status": "pending",
      "order": [
        {
          "product": "string",
          "size": "small",
          "quantity": 1
        }
      ]
    }
  ]
}
```
</details>

#### Run Prism with Payments API
```./node_modules/.bin/prism mock payments.yaml --port 3001```

***NOTE:*** Payments only have a POST endpoint to inform about the payment

</br>

## Implement API integration
#### Install request python library
```(.venv) $ pipenv install requests```

#### Encapsulating per-order capabilities within the Order class
<details><summary>orders/orders_service/orders.py</summary>

```python
import requests
from orders.orders_service.exceptions import APIIntegrationError, InvalidActionError

class OrderItem:
    def __init__(self, id, product, quantity, size):
        self.id = id
        self.product = product
        self.quantity = quantity
        self.size = size

class Order:
    def __init__(self, id, created, items, status, schedule_id=None, delivery_id=None, order_=None,):
        self._id = id
        self._created = created
        self.items = [OrderItem(**item) for item in items]
        self._status = status
        self.schedule_id = schedule_id
        self.delivery_id = delivery_id

    @property
    def id(self):
        return self._id or self._order.id

    @property
    def created(self):
        return self._created or self._order.created

    @property
    def status(self):
        return self._status or self._order.status

    def cancel(self):
        if self.status == "progress":
            kitchen_base_url = "http:/ /localhost:3000/kitchen"
            response = requests.post(
                f"{kitchen_base_url}/schedules/{self.schedule_id}/cancel",
                json={"order": [item.dict() for item in self.items]},
            )
            if response.status_code == 200:
                return
            raise APIIntegrationError(f"Could not cancel order with id {self.id}")
        if self.status == "delivery":
            raise InvalidActionError(f"Cannot cancel order with id {self.id}")

    def pay(self):
        response = requests.post(
            "http:/ /localhost:3001/payments", json={"order_id": self.id}
        )
        if response.status_code == 201:
            return
        raise APIIntegrationError(
            f"Could not process payment for order with id {self.id}"
        )

    def schedule(self):
        response = requests.post(
            "http:/ /localhost:3000/kitchen/schedules",
            json={"order": [item.dict() for item in self.items]},
        )
        if response.status_code == 201:
            return response.json()["id"]
        raise APIIntegrationError((f"Could not schedule order with id {self.id}"))
```
</details>

#### Define orders_service custom exceptions
<details><summary>orders/orders_service/exceptions.py</summary>

```python
class OrderNotFoundError(Exception):
    pass
class APIIntegrationError(Exception):
    pass
class InvalidActionError(Exception):
    pass
```
</details>

#### Implementation of the OrdersService
<details><summary>orders/orders_service/orders_service.py</summary>

```python
from orders.orders_service.exceptions import OrderNotFoundError


class OrdersService:
    def __init__(self, orders_repository):
        self.orders_repository = orders_repository

    def place_order(self, items):
        return self.orders_repository.add(items)

    def get_order(self, order_id):
        order = self.orders_repository.get(order_id)
        if order is not None:
            return order
        raise OrderNotFoundError(f"Order with id {order_id} not found")

    def update_order(self, order_id, items):
        order = self.orders_repository.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"Order with id {order_id} not found")
        return self.orders_repository.update(order_id, {"items": items})

    def list_orders(self, **filters):
        limit = filters.pop("limit", None)
        return self.orders_repository.list(limit, **filters)

    def pay_order(self, order_id):
        order = self.orders_repository.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"Order with id {order_id} not found")
        order.pay()
        schedule_id = order.schedule()
        return self.orders_repository.update(
            order_id, {"status": "scheduled", "schedule_id": schedule_id}
        )

    def cancel_order(self, order_id):
        order = self.orders_repository.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"Order with id {order_id} not found")
        order.cancel()
        return self.orders_repository.update(order_id, status="cancelled")
```
</details>


### Implementing the unit of work pattern
<details><summary>orders/repository/unit_of_work.py</summary>

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

class UnitOfWork:
    def __init__(self):
        self.session_maker = sessionmaker(
            bind=create_engine('sqlite:///orders.db')
        )
    def __enter__(self):
        self.session = self.session_maker()
        return self
    def __exit__(self, exc_type, exc_val, traceback):
        if exc_type is not None:
            self.rollback()
            self.session.close()
        self.session.close()
    def commit(self):
        self.session.commit()
    def rollback(self):
        self.session.rollback()
```
</details>


#### Template of how to use the unit_of_work

```python
with UnitOfWork() as unit_of_work:
    repo = OrdersRepository(unit_of_work.session)
    orders_service = OrdersService(repo)
    orders_service.place_order(order_details)
    unit_of_work.commit()
```

#### Integration between API layer and service layer

Enter the unit of work context

<details><summary>orders/web/api/api.py</summary>

```python
from orders.orders_service.exceptions import OrderNotFoundError
from orders.orders_service.orders_service import OrdersService
from orders.repository.orders_repository import OrdersRepository
from orders.repository.unit_of_work import UnitOfWork


```
<details>