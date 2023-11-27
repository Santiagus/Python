import random, string
from ariadne import QueryType
from web.data import ingredients, products

query = QueryType()


@query.field("hello")
def resolve_hello(*_):
    return "".join(random.choice(string.ascii_letters) for _ in range(10))


@query.field("allIngredients")
def resolve_all_ingredients(*_):
    return ingredients


@query.field("allProducts")
def resolve_all_products(*_):
    return products


@query.field("products")
def resolve_products(*_, input=None):
    filtered = [product for product in products]
    if input is None:
        return filtered
    filtered = [
        product for product in filtered if product["available"] is input["available"]
    ]
    if input.get("minPrice") is not None:
        filtered = [
            product for product in filtered if product["price"] >= input["minPrice"]
        ]
    if input.get("maxPrice") is not None:
        filtered = [
            product for product in filtered if product["price"] <= input["maxPrice"]
        ]
    filtered.sort(
        key=lambda product: product.get(input["sortBy"], 0),
        reverse=input["sort"] == "DESCENDING",
    )
    return filtered
