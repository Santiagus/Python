from flask import Flask
from flask_smorest import Api

from kitchen.config import BaseConfig

app = Flask(__name__)

# @app.route("/")
# def index():
#     return "Index Page"


# @app.route("/hello")
# def hello():
#     return "Hello, World"

app.config.from_object(BaseConfig)
kitchen_api = Api(app)
