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


