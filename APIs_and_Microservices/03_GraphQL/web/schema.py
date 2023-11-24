from pathlib import Path
from ariadne import make_executable_schema
from web.queries import query
from web.types import product_type

schema = make_executable_schema(
    (Path(__file__).parent / "products.graphql").read_text(), [query, product_type]
)
