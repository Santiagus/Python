# import random
# import string
# from ariadne import QueryType, make_executable_schema
# from ariadne.asgi import GraphQL

# query = QueryType()


# @query.field("hello")
# def resolve_hello(*_):
#     return "".join(random.choice(string.ascii_letters) for _ in range(10))


# schema = """
# type Query {
# hello: String
# }
# """
# server = GraphQL(make_executable_schema(schema, [query]), debug=True)

from ariadne.asgi import GraphQL
from web.schema import schema

server = GraphQL(schema, debug=True)
