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

#### Run Prism iwith kitchen API
```./node_modules/.bin/prism mock kitchen.yaml --port 3000```

#### Install jq - commandline JSON processor
```sudo apt install jq```

Check response parsing it with jq to get a beautiful display

```curl http://localhost:3000/kitchen/schedules | jq```

pipenv install requests

