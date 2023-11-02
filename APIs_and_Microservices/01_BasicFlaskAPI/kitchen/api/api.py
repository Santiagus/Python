from urllib.parse import scheme_chars
import copy
import uuid
from datetime import datetime, timedelta

from flask import abort
from flask import jsonify
from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import ValidationError

# Marshmallow models
from kitchen.api.schemas import (
    GetScheduledOrderSchema,
    ScheduleOrderSchema,
    GetScheduledOrdersSchema,
    ScheduleStatusSchema,
    GetKitchenScheduleParameters,
)

blueprint = Blueprint("kitchen", __name__, description="Kitchen API")

# hardcoded schedules list
schedules = [
    {
        "id": str(uuid.uuid4()),
        "scheduled": datetime.now() + timedelta(minutes=15),
        "status": "pending",
        "order": [{"product": "Expresso", "quantity": 1, "size": "big"}],
    },
    {
        "id": str(uuid.uuid4()),
        "scheduled": datetime.now() + timedelta(minutes=2),
        "status": "progress",
        "order": [{"product": "caffe latte", "quantity": 2, "size": "medium"}],
    },
    {
        "id": str(uuid.uuid4()),
        "scheduled": datetime.now(),
        "status": "finished",
        "order": [{"product": "capuccino", "quantity": 3, "size": "small"}],
    },
]

# schedules = []


# Data validation code refactored to function
def validate_schedule(schedule):
    schedule = copy.deepcopy(schedule)
    schedule["scheduled"] = schedule["scheduled"].isoformat()
    errors = GetScheduledOrderSchema().validate(schedule)
    if errors:
        raise ValidationError(errors)


@blueprint.route("/kitchen/schedules")
class KitchenSchedules(MethodView):
    @blueprint.arguments(GetKitchenScheduleParameters, location="query")
    @blueprint.response(status_code=200, schema=GetScheduledOrdersSchema)
    # @blueprint.response(status_code=200)
    def get(self, parameters):
        # return {"schedules": schedules}, 200
        query_set = [schedule for schedule in schedules]

        # In Marshmallow, there isn't a built-in way to validate an entire list of objects in one step using a schema.
        for schedule in query_set:
            try:
                # GetScheduledOrderSchema().load(schedule)
                validate_schedule(schedule)
                print("Schedule data is valid.")
            except ValidationError as e:
                print("Validation failed. Errors:", e)

        # in_progress = parameters.get(GetKitchenScheduleParameters.progress)

        # Filter by progress
        in_progress = parameters.get("progress")
        if in_progress is not None:
            if in_progress:
                query_set = [
                    schedule
                    for schedule in query_set
                    if schedule["status"] == "progress"
                ]
            else:
                query_set = [
                    schedule
                    for schedule in query_set
                    if schedule["status"] != "progress"
                ]

        # Filter by date
        since = parameters.get("since")
        if since is not None:
            query_set = [
                schedule for schedule in query_set if schedule["scheduled"] >= since
            ]

        # Filter by limit
        limit = parameters.get("limit")
        if limit is not None and len(query_set) > limit:
            query_set = query_set[:limit]

        return {"schedules": query_set}

    @blueprint.arguments(ScheduleOrderSchema)
    @blueprint.response(status_code=201, schema=GetScheduledOrderSchema)
    def post(self, payload):
        # return schedules[0], 201
        # return schedules[0]
        payload["id"] = str(uuid.uuid4())
        payload["scheduled"] = datetime.now()
        payload["status"] = "pending"
        print("Payload : ", payload)
        validate_schedule(payload)
        schedules.append(payload)
        return payload


@blueprint.route("/kitchen/schedules/<schedule_id>")
class KitchenSchedule(MethodView):
    @blueprint.response(status_code=200, schema=GetScheduledOrderSchema)
    def get(self, schedule_id):
        # return schedules[0], 200
        # return schedules[0]
        for schedule in schedules:
            if schedule["id"] == schedule_id:
                validate_schedule(schedule)
                return jsonify(schedule)
        abort(404, description=f"Resource with ID {schedule_id} not found")

    @blueprint.arguments(ScheduleOrderSchema)
    @blueprint.response(status_code=200, schema=GetScheduledOrderSchema)
    def put(self, payload, schedule_id):
        # return schedules[0], 200
        # return schedules[0]
        for schedule in schedules:
            if schedule["id"] == schedule_id:
                schedule.update(payload)
                validate_schedule(schedule)
                return schedule
        abort(404, description=f"Resource with ID {schedule_id} not found")

    @blueprint.response(status_code=204)
    def delete(self, schedule_id):
        # return "", 204
        for index, schedule in enumerate(schedules):
            if schedule["id"] == schedule_id:
                schedules.pop(index)
                return
        abort(404, description=f"Resource with ID {schedule_id} not found")


@blueprint.response(status_code=200, schema=GetScheduledOrderSchema)
@blueprint.route("/kitchen/schedules/<schedule_id>/cancel", methods=["POST"])
def cancel_schedule(schedule_id):
    # return schedules[0], 200
    # return schedules[0]
    for schedule in schedules:
        if schedule["id"] == schedule_id:
            schedule["status"] = "cancelled"
            validate_schedule(schedule)
            return schedule
    abort(404, description=f"Resource with ID {schedule_id} not found")


@blueprint.response(status_code=200, schema=ScheduleStatusSchema)
@blueprint.route("/kitchen/schedules/<schedule_id>/status", methods=["GET"])
def get_schedule_status(schedule_id):
    # return schedules[0], 200
    # return schedules[0]
    for schedule in schedules:
        if schedule["id"] == schedule_id:
            validate_schedule(schedule)
            return {"status": schedule["status"]}
    abort(404, description=f"Resource with ID {schedule_id} not found")
