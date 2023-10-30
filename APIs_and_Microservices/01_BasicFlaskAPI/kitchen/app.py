from flask import Flask
from flask_smorest import Api

from kitchen.config import BaseConfig
from kitchen.api.api import blueprint

app = Flask(__name__)
app.config.from_object(BaseConfig)

kitchen_api = Api(app)
kitchen_api.register_blueprint(blueprint)

# @app.route("/")
# def index():
#     return "Index Page"


# @app.route("/hello")
# def hello():
#     return "Hello, World"
