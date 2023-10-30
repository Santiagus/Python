from urllib.parse import scheme_chars
import uuid
from datetime import datetime

from flask.views import MethodView
from flask_smorest import Blueprint

blueprint = Blueprint("kitchen", __name__, description="Kitchen API")

# hardcoded schedules list
schedules = [
    {
        "id": str(uuid.uuid4()),
        "scheduled": datetime.now(),
        "status": "pending",
        "order": [{"product": "capuccino", "quantity": 1, "size": "big"}],
    }
]


@blueprint.route("/kitchen/schedules")
class KitchenSchedules(MethodView):
    def get(self):
        return {"schedules": schedules}, 200
