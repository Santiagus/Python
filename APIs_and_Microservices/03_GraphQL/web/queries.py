from copy import deepcopy
import random, string
from ariadne import QueryType
from web.data import ingredients, products
from itertools import islice

query = QueryType()


@query.field("hello")
def resolve_hello(*_):
    return "".join(random.choice(string.ascii_letters) for _ in range(10))


@query.field("allIngredients")
def resolve_all_ingredients(*_):
    return ingredients


@query.field("allProducts")
def resolve_all_products(*_):
    # return products
    products_with_ingredients = [deepcopy(product) for product in products]
    for product in products_with_ingredients:
        for ingredient_recipe in product["ingredients"]:
            for ingredient in ingredients:
                if ingredient["id"] == ingredient_recipe["ingredient"]:
                    ingredient_recipe["ingredient"] = ingredient
    return products_with_ingredients


def get_page(items, items_per_page, page):
    page = page - 1
    start = items_per_page * page if page > 0 else page
    stop = start + items_per_page
    return list(islice(items, start, stop))


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
    return get_page(filtered, input["resultsPerPage"], input["page"])
    # return filtered
