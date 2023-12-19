import uuid
from datetime import datetime
from ariadne import MutationType
from web.data import products

mutation = MutationType()


@mutation.field("addProduct")
def resolve_add_product(*_, name, type, input):
    product = {
        "id": uuid.uuid4(),
        "name": name,
        "available": input.get("available", False),
        "ingredients": input.get("ingredients", []),
        "lastUpdated": datetime.utcnow(),
    }
    if type == "cake":
        product.update(
            {
                "hasFilling": input["hasFilling"],
                "hasNutsToppingOption": input["hasNutsToppingOption"],
            }
        )
    else:
        product.update(
            {
                "hasCreamOnTopOption": input["hasCreamOnTopOption"],
                "hasServeOnIceOption": input["hasServeOnIceOption"],
            }
        )
    products.append(product)
    return product
