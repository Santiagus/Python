# file: orders/app.py
from fastapi import FastAPI

app = FastAPI(debug=True)

from orders.api import api