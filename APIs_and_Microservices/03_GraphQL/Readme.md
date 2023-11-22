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