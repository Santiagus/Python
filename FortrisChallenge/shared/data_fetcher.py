from requests import Session
from requests.exceptions import ConnectionError, Timeout, TooManyRedirects
import copy
import json
import os
import logging
from datetime import datetime


class CustomApiException(Exception):
    def __init__(self, json_data, message="API Error"):
        self.json_data = json_data
        self.message = message
        super().__init__(self.message)

class DataFetcher():
    def __init__(self, config):
        self.config = config
        self._set_api_key()
        self.session = Session()
        self.session.headers.update(self.config.get("headers"))
        logging.info(f"Initialized")


    def _set_api_key(self):
        json_string = json.dumps(self.config)
        new_json_string = json_string.replace("${API_KEY}", os.environ.get(self.config["api_key_env_var_name"], ""))
        self.config = json.loads(new_json_string)

    def access_nested_fields(self, json_data, path, default_value = None):
        field_value = json_data
        try:
            for key in path.split("."):
                field_value = field_value[key]
        except (KeyError, TypeError):
            if default_value:
                field_value = default_value
        return field_value

    def apply_filter(self, json_data, filter_config):
        filtered_item = {}
        for field_config in filter_config["fields"]:
            field_name = field_config["name"]
            field_source = field_config["source"]
            default_value = field_config["default"]
            logging.debug(f"name {field_name} - source {field_source} - default {default_value}")
            # Access to nested field value
            field_value = self.access_nested_fields(json_data, field_source, default_value)
            logging.debug(f"Extracted Value : {field_value}")
            # Apply transformation if specified
            transform_function = field_config.get("transform")
            logging.debug(f"Tranform : {transform_function}")
            if transform_function and field_value is not None:
                field_value = eval(transform_function)(field_value)
                logging.debug(f"Tranform result: {field_value}")

            filtered_item[field_name] = field_value

        return filtered_item

    async def get_data(self):
        try:
            logging.info(f"Requesting data from {self.config.get('url')}")

            # Load request parameters
            json_params = copy.deepcopy(self.config.get("parameters"))
            page = json_params.get("page", None)
            page_size = json_params.get("page_size", None)

            filtered_items = []
            while True:
                response = self.session.get(self.config.get("url"), params=json_params)
                if response.status_code == 200:
                    json_response = json.loads(response.text)
                    items = self.access_nested_fields(json_response, self.config["data_path"])
                    logging.debug(f"Filtering {len(items)} items")
                    filtered_items.extend([self.apply_filter(item, self.config) for item in items])
                    if page is None or len(items) < page_size:
                        logging.info(f"Total Filtered : {len(filtered_items)} items")
                        return filtered_items
                    else:
                       json_params["page"] += 1
                else:
                    raise CustomApiException(response.json(), f"API Error ({response.status_code}) : {response.text}")
        except (Exception,ConnectionError, Timeout, TooManyRedirects) as e:
            raise e