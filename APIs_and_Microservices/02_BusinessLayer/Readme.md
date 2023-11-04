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
└── orders                  # orders service
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