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
