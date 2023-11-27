# GraphQL

GraphQL is a query language for APIs and a runtime for fulfilling those queries with your existing data. 

GraphQL APIs get all the needed data in a single request from one or multiple sources so it is suitable for cases where we need to work with agregated data reducing over-fetching and under-fetching of data.

A GraphQL API specification is called a schema, and it’s written using the Schema
Definition Language (SDL).

#### Create GraphQL API specification
<details><summary>schema.graphql</summary>

```graphql
scalar Datetime

type Supplier {
    id: ID!
    name: String!
    address: String!
    contactNumber: String!
    email: String!
    ingredients: [Ingredient!]!
}

enum MeasureUnit {
    LITERS
    KILOGRAMS
    UNITS
}

type Stock {
    quantity: Float!
    unit: MeasureUnit!
}

type Ingredient {
    id: ID!
    name: String!
    stock: Stock!
    products: [Product!]!
    supplier: Supplier
    description: [String!]
    lastUpdated: Datetime!
}

type IngredientRecipe {
    ingredient: Ingredient!
    quantity: Float!
    unit: MeasureUnit!
}

enum Sizes {
    SMALL
    MEDIUM
    BIG
}

interface ProductInterface {
    id: ID!
    name: String!
    price: Float
    size: Sizes
    ingredients: [IngredientRecipe!]
    available: Boolean!
    lastUpdated: Datetime!
}

type Beverage implements ProductInterface {
    id: ID!
    name: String!
    price: Float
    size: Sizes
    ingredients: [IngredientRecipe!]!
    available: Boolean!
    lastUpdated: Datetime!
    hasCreamOnTopOption: Boolean!
    hasServeOnIceOption: Boolean!
}

type Cake implements ProductInterface {
    id: ID!
    name: String!
    price: Float
    size: Sizes
    ingredients: [IngredientRecipe!]
    available: Boolean!
    lastUpdated: Datetime!
    hasFilling: Boolean!
    hasNutsToppingOption: Boolean!
}

union Product = Beverage | Cake

enum SortingOrder {
    ASCENDING
    DESCENDING
}

enum SortBy {
    price
    name
}

input ProductsFilter {
    maxPrice: Float
    minPrice: Float
    available: Boolean=true
    sortBy: SortBy=price
    sort: SortingOrder=DESCENDING
    resultsPerPage: Int = 10
    page: Int = 1
}

type Query {
    allProducts: [Product!]!
    allIngredients: [Ingredient!]!
    products(input: ProductsFilter!): [Product!]!
    product(id: ID!): Product
    ingredient(id: ID!): Ingredient
}

input IngredientRecipeInput {
    ingredient: ID!
    quantity: Float!
    unit: MeasureUnit!
}

input AddProductInput {
    price: Float
    size: Sizes
    ingredients: [IngredientRecipeInput!]!
    hasFilling: Boolean = false
    hasNutsToppingOption: Boolean = false
    hasCreamOnTopOption: Boolean = false
    hasServeOnIceOption: Boolean = false
}

input AddIngredientInput {
    supplier: AddSupplier
    stock: AddStock
    description: [String!]!
}

input AddStock {
    quantity: Float!
    unit: MeasureUnit!
}

input AddSupplier {
    address: String!
    contactNumber: String!
    email: String!
}

enum ProductType {
    cake
    beverage
}

type Mutation {
    addSupplier(name: String!, input: AddSupplier!): Supplier!
    addIngredient(name: String!, input: AddIngredientInput!): Ingredient!
    addProduct(name: String!, type: ProductType!, input: AddProductInput!): Product!
    updateProduct(id: ID!, input: AddProductInput!): Product!
    deleteProduct(id: ID!): Boolean!
    updateStock(id: ID!, changeAmount: AddStock): Ingredient!
}

schema {
    query: Query,
    mutation: Mutation
}
```
</details>

## Setup
#### Use nvm for installing node.js and associated npm (Recommended)

1. Install nvm
    ```bash
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.5/install.sh | bash
    source ~/.bashrc
    ```
2. Install node.js & npm
    ```bash
    nvm install 21
    ```

#### Alternative for installing last node.js version (from the repository)
[node.js source](https://github.com/nodesource/distributions)
1. Download and import the Nodesource GPG key
    ```bash
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
    ```
2. Create deb repository
    ```bash
    NODE_MAJOR=21
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list
    ```
3. Run Update and Install
    ```bash
    sudo apt-get update
    sudo apt-get install nodejs -y
    ```

4. Check version
    ```bash
    node --version
    v21.2.0
    ```

#### Alternative using docker 
Mount current folder as */workdir* and pass schema sdl file path \
```$ docker run -v=${PWD}:/workdir apisguru/graphql-faker schema.graphql```

#### Alternative Build Source code 
1. Clone repository
    ```bash
    git clone https://github.com/graphql-kit/graphql-faker
    ```
2. Move schema file inside cloned repository and rename to default schema.faker.graphql

    ```mv schema.sdl schema.faker.graphql```
3. Build and Start server
    ```bash
    npm i
    npm run build
    npm run start
    ```

## Official way (that does not work...)
### Install a  GraphQL mock server.
```$ npm install graphql-faker```

### Run the installed server
```$ ./node_modules/.bin/graphql-faker schema.graphql```

GraphQL Faker normally runs on port 9002, and it exposes three endpoints:

- **/editor** : Interactive editor
- **/graphql** :Interface to the GraphQL API. It allows to explore the API and run queries.
- **/voyager** : Interactive display of your API,shows relationships and dependencies between types.

  ❯ Interactive Editor: http://localhost:9002/editor \
  ❯ GraphQL API:        http://localhost:9002/graphql \
  ❯ GraphQL Voyager:    http://localhost:9002/voyager 

### Running simple queries in graphql
http://localhost:9002/graphql

On the left panel run:
```json
{
    allIngredients {
        name
    }
}
```
<details><summary>output</summary>

```json
{
  "data": {
    "allIngredients": [
      {
        "name": "string"
      },
      {
        "name": "string"
      }
    ]
  }
}
```
</details>

#### Sample query with parameters

```bash
{
    ingredient (id: "asdg"){
            name
        }
}
```

<details><summary>Sample error output</summary>

```json
{
  "errors": [
    {
      "message": "Field \"ingredient\" argument \"id\" of type \"ID!\" is required, but it was not provided.",
      "locations": [
        {
          "line": 2,
          "column": 1
        }
      ]
    }
  ]
}
```
</details>

If any Error occurs, output indicate missing required parameters and the exact location in the given query.

#### Multiple types Query

When a GraphQL query returns multiple types we must create selections sets for each type using *inline fragments*

An inline fragment is an anonymous selection set on a specific type.

```GraphQL
{
allProducts { 
  ...on ProductInterface{
  	name
	}
  ...on Cake {
  	name
	}
  ...on Beverage {
  	name
	}
}
}
```

Define fragments as standalone variables.

<details>

```GraphQL
{
    allProducts {
        ...commonProperties
        ...cakeProperties
        ...beverageProperties
    }
}
fragment commonProperties on ProductInterface {
    name
}

fragment cakeProperties on Cake {
    hasFilling
}

fragment beverageProperties on Beverage {
    hasCreamOnTopOption
}
```
</details>

#### Running queries with input parameters
```GraphQL
{
    products(input: {maxPrice: 10}) {
        ...on ProductInterface {
            name
        }
    }
}
```

#### Querying nested object types
<details><summary>sample 1</summary>

```GraphQL
{
  allProducts {
    ... on ProductInterface {
      name
      ingredients {
        ingredient {
          name
        }
      }
    }
  }
}
```
</details>

<details><summary>sample 2</summary>

```GraphQL
{
  allProducts {
    ... on ProductInterface {
      name
      ingredients {
        ingredient {
          name
          supplier {
            name
          }
        }
      }
    }
  }
}
```
</details>

#### Multiple querys in one request
```GraphQL
{
  allProducts {
    ...commonProperties
  }
  allIngredients {
    name
  }
}

fragment commonProperties on ProductInterface {
  name
}
```

#### Query aliasing
**product** alias for *allProcuts* \
**ingredients** alias for *allIngredients*
```GraphQL
{
  products: allProducts {
    ...commonProperties
  }
  ingredients: allIngredients {
    name
  }
}

fragment commonProperties on ProductInterface {
  name
}
```
Mandatory if requesting several query multiple times

```GraphQL
{
  availableProducts: products(input: {available: true}) {
    ...commonProperties
  }
  unavailableProducts: products(input: {available: false}) {
    ...commonProperties
  }
}

fragment commonProperties on ProductInterface {
  name
}
```

### GraphQL mutations

Mutations are GraphQL functions that allow us to create resources or change the state of the server.

Queries are meant to read data from the server, while mutations are meant to
create or change data in the server.

```GraphQL
mutation {
    deleteProduct(id: "asdf")
}
```

```GraphQL
mutation {
  addProduct(name: "Mocha", type: beverage,
    input: {
      price: 10,
      size: BIG,
      ingredients: [{
         ingredient: 1,
         quantity: 1,
         unit: LITERS
      }]
    })
  {
    ...commonProperties
  }
}

fragment commonProperties on ProductInterface {
  name
}
```

#### Parameterized syntax

Parameterized queries allow us to decouple our query/mutation calls from the
data.

The parameterized argument is marked with a dollar sign ($)

<details><summary>Query document</summary>

```GraphQL
mutation CreateProduct($name: String!, $type: ProductType!, $input: AddProductInput!) {
  addProduct(name: $name, type: $type, input: $input) {
    ...commonProperties
  }
}

fragment commonProperties on ProductInterface {
  name
}
```
</details>
</br>

Separately, we define our query variables as a JSON document.

<details><summary>Query variables</summary>

```GraphQL
{
  "name": "Mocha",
  "type": "beverage",
  "input": {
    "price": 10,
    "size": "BIG",
    "ingredients": [
      {
        "ingredient": 1,
        "quantity": 1,
        "unit": "LITERS"
      }
    ]
  }
}
```
</details>

### Adding deletion in the same request

<details><summary>Query document</summary>

```GraphQL
mutation CreateAndDeleteProduct($name: String!, $type: ProductType!, $input: AddProductInput!, $id: ID!) {
  addProduct(name: $name, type: $type, input: $input) {
    ...commonProperties
  }
  deleteProduct(id: $id)
}

fragment commonProperties on ProductInterface {
  name
}

```
</details>
</br>

<details><summary>Query variables</summary>

```GraphQL
{
  "name": "Mocha",
  "type": "beverage",
  "input": {
    "price": 10,
    "size": "BIG",
    "ingredients": [
      {
        "ingredient": 1,
        "quantity": 1,
        "unit": "LITERS"
      }
    ]
  },
  "id": "asdf"
}
```
</details>

In Examples until now we are using GraphiQL client to explore the GraphQL API and to interact with it.
GraphiQL translates our query documents into HTTP requests that the GraphQL server understands.

HTTP request can be sent directly to the API using cURL or others.

GET or POST methods can be used to send a request.
- GET : send query document using URL query parameters
- POST: send query in the request payload.

```bash
$ curl http://localhost:9002/graphql --data-urlencode 'query={allIngredients{name}}'
```

#### Calling a GraphQL query using Python

```python
import requests
URL = "http://localhost:9002/graphql"
query_document = """
{
  allIngredients {
    name
  }
}
"""
result = requests.get(URL, params={"query": query_document})
print(result.json())
```
## Building GraphQL APIs with Python

The choosen library to develop GraphQL API is Ariadne (https://github.com/mirumee/ariadne).

It is a library built for schemafirst (or documentation-driven) development that handles schema validation and serialization automatically.

```pip install ariadne uvicorn```

To serve data, a GraphQL server uses resolvers, which are functions that know how to build the payload for a given query.

<details open><summary>server.py</summary>

```python
from ariadne import make_executable_schema
from ariadne.asgi import GraphQL
schema = '''
  type Query {
  hello: String
}
'''
server = GraphQL(make_executable_schema(schema), debug=True)
```
</details>

To run the server, execute: \
```$ uvicorn server:server --reload```

Server web interface will be available at http://127.0.0.1:8000/

Run Sample query
```GraphQL
  {
    hello
  }
```

<details open><summary>response</summary>

```json
{
  "data": {
    "hello": null
  }
}

```
</details>

The query returns null, to return other value a resolver has to be implemented.

#### Resolver parameters in Ariadne
Ariadne’s resolvers always have two positional-only parameters, which are commonly called obj and info.

*Sample signature*

```python
def simple_resolver(obj: Any, info: GraphQLResolveInfo):
  pass
```

<details><summary>server.py</summary>

```python
import random
import string
from ariadne import QueryType, make_executable_schema
from ariadne.asgi import GraphQL

query = QueryType()


@query.field("hello")
def resolve_hello(*_):
    return "".join(random.choice(string.ascii_letters) for _ in range(10))

schema = """
type Query {
hello: String
}
"""
server = GraphQL(make_executable_schema(schema, [query]), debug=True)
```

Now the response is a string with 10 random characters.

<details open><summary>response</summary>

```json
{
  "data": {
    "hello": "XTaPhWUDTa"
  }
}

```
</details>

#### Define project structure

```bash
.
├── server.py
└── web
    ├── data.py          # In memory data
    ├── exceptions.py    # exceptions hadling examples
    ├── mutations.py     # resolvers for the mutations in the APi
    ├── products.graphql #
    ├── queries.py       # resolvers for queries
    ├── schema.py        # code to load and executable schema
    └── types.py         # resolvers for object types, custom scalar types, and object properties.
```

<details><summary>web/schema.py</summary>

```python
from pathlib import Path
from ariadne import make_executable_schema

schema = make_executable_schema(
    (Path(__file__).parent / "products.graphql").read_text()
)

```
</details>

<details><summary>server.py</summary>

```python
from ariadne.asgi import GraphQL
from web.schema import schema

server = GraphQL(schema, debug=True)
```
</details>

Query example:
```GraphQL
{
  allIngredients {
    name
  }
}
```

Output will show errors because there is no query resolver implemented:
```
“Cannot return null for non-nullable field Query.allProducts.”
```

## Implementing query resolvers


#### Specification for the Ingredient type

  <details><summary>web/products.graphql</summary>

  ```python
  scalar Datetime

  type Supplier {
      id: ID!
      name: String!
      address: String!
      contactNumber: String!
      email: String!
      ingredients: [Ingredient!]!
  }

  enum MeasureUnit {
      LITERS
      KILOGRAMS
      UNITS
  }

  type Stock {
      quantity: Float!
      unit: MeasureUnit!
  }

  type Ingredient {
      id: ID!
      name: String!
      stock: Stock!
      products: [Product!]!
      supplier: Supplier
      description: [String!]
      lastUpdated: Datetime!
  }

  type IngredientRecipe {
      ingredient: Ingredient!
      quantity: Float!
      unit: MeasureUnit!
  }

  enum Sizes {
      SMALL
      MEDIUM
      BIG
  }

  interface ProductInterface {
      id: ID!
      name: String!
      price: Float
      size: Sizes
      ingredients: [IngredientRecipe!]
      available: Boolean!
      lastUpdated: Datetime!
  }

  type Beverage implements ProductInterface {
      id: ID!
      name: String!
      price: Float
      size: Sizes
      ingredients: [IngredientRecipe!]!
      available: Boolean!
      lastUpdated: Datetime!
      hasCreamOnTopOption: Boolean!
      hasServeOnIceOption: Boolean!
  }

  type Cake implements ProductInterface {
      id: ID!
      name: String!
      price: Float
      size: Sizes
      ingredients: [IngredientRecipe!]
      available: Boolean!
      lastUpdated: Datetime!
      hasFilling: Boolean!
      hasNutsToppingOption: Boolean!
  }

  union Product = Beverage | Cake

  type Query {
      allIngredients: [Ingredient!]!
  }
  ```
  </details>

#### Add In-memory data (static)

  <details><summary>web/data.py</summary>

  ```JSON

  ingredients = [
      {
          "id": "602f2ab3-97bd-468e-a88b-bb9e00531fd0",
          "name": "Milk",
          "stock": {
              "quantity": 100.00,
              "unit": "LITRES",
          },
          "supplier": "92f2daae-a4f8-4aae-8d74-51dd74e5de6d",
          "products": [],
          "lastUpdated": datetime.utcnow(),
      },
      {
          "id": "987f2ab3-54bd-468e-a88b-bb9e00531fd0",
          "name": "Cocoa",
          "stock": {
              "quantity": 50.00,
              "unit": "KILOGRAMS",
          },
          "supplier": "64Y2daae-a4f8-4aae-8d74-51dd74e5R8Jd",
          "products": [],
          "lastUpdated": datetime.utcnow(),
      },
  ]

  ```
  </details>

#### Add allIngredients() query resolver

  <details><summary>web/queries.py</summary>

  ```python
  from ariadne import QueryType
  from web.data import ingredients

  query = QueryType()


  @query.field("allIngredients")
  def resolve_all_ingredients(*_):
      return ingredients

  ```
  </details>

#### Enable the query resolver

- Import query from web.queries
- Add *query* to the schema

  <details><summary>web/schema.py</summary>

  ```python
  from web.queries import query
  schema = make_executable_schema(
    (Path(__file__).parent / 'products.graphql').read_text(),
    [query]
  )
  ```
  </details>

Run
```uvicorn server:server```

#### Execute query:
```json
{
  allIngredients {
    name
  }
}
```
<details><summary>output</summary>

```json
{
  "data": {
    "allIngredients": [
      {
        "name": "Milk"
      },
      {
        "name": "Cocoa"
      }
    ]
  }
}
```
</details>

#### Another query:
```json
{
  allIngredients {
    id
    name
    products {
      ... on ProductInterface {
        name
      }
    }
    description
  }
}
```
<details><summary>output</summary>

```json
{
  "data": {
    "allIngredients": [
      {
        "id": "602f2ab3-97bd-468e-a88b-bb9e00531fd0",
        "name": "Milk",
        "products": [],
        "description": null
      },
      {
        "id": "987f2ab3-54bd-468e-a88b-bb9e00531fd0",
        "name": "Cocoa",
        "products": [],
        "description": null
      }
    ]
  }
}
```
</details>

### Add products to data.py
<details><summary>web/data.py</summary>

```json
products = [
    {
        "id": "6961ca64-78f3-41d4-bc3b-a63550754bd8",
        "name": "Walnut Bomb",
        "price": 37.00,
        "size": "MEDIUM",
        "available": False,
        "ingredients": [
            {
                "ingredient": "602f2ab3-97bd-468e-a88b-bb9e00531fd0",
                "quantity": 100.00,
                "unit": "LITRES",
            }
        ],
        "hasFilling": False,
        "hasNutsToppingOption": True,
        "lastUpdated": datetime.utcnow(),
    },
    {
        "id": "e4e33d0b-1355-4735-9505-749e3fdf8a16",
        "name": "Cappuccino Star",
        "price": 12.50,
        "size": "SMALL",
        "available": True,
        "ingredients": [
            {
                "ingredient": "602f2ab3-97bd-468e-a88b-bb9e00531fd0",
                "quantity": 100.00,
                "unit": "LITRES",
            }
        ],
        "hasCreamOnTopOption": True,
        "hasServeOnIceOption": True,
        "lastUpdated": datetime.utcnow(),
    },
]
```
</details>

### Add resolver for allProducts()

<details><summary>web/queries.py</summary>

```python
from web.data import ingredients, products

@query.field('allProducts')
def resolve_all_products(*_):
  return products
```
</details>


#### Type resolver for the Product union type

<details><summary>web/types.py</summary>

```python
from ariadne import UnionType

product_type = UnionType("Product")


@product_type.type_resolver
def resolve_product_type(obj, *_):
    if "hasFilling" in obj:
        return "Cake"
    return "Beverage"
```
</details>

<details><summary>web/schema.py</summary>

```python
from web.types import product_type
schema = make_executable_schema(
  (Path(__file__).parent / 'products.graphql').read_text(),
  [query, product_type]
)
```
</details>


### Handling query parameters
Example defining *products()* query, which accepts an input filter object
whose type is *ProductsFilter*.

Update *products.graphql*
```graphql
enum SortingOrder {
    ASCENDING
    DESCENDING
}

enum SortBy {
    price
    name
}

input ProductsFilter {
    maxPrice: Float
    minPrice: Float
    available: Boolean=true
    sortBy: SortBy=price
    sort: SortingOrder=DESCENDING
    resultsPerPage: Int = 10
    page: Int = 1
}

type Query {
    products(input: ProductsFilter!): [Product!]!
}
```

Add query resolver to *queries.py*
```python
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
```

Run Query to test the resolver:
- Run : ```$ uvicorn server:server```
- Execute query in web interface :  http://127.0.0.1:8000
```GraphQL
{
products(input: {available: true}) {
    ...on ProductInterface {
      name
    }
  }
}
```