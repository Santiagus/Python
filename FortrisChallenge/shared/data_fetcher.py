from requests import Session
from requests.exceptions import ConnectionError, Timeout, TooManyRedirects
import json
import os
import logging
from datetime import datetime
import importlib

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
        new_json_string = json_string.replace("${API_KEY}", os.environ.get("API_KEY", ""))        
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

            # Access to nested field value
            field_value = self.access_nested_fields(json_data, field_source, default_value)

            # Apply transformation if specified
            transform_function = field_config.get("transform")
            if transform_function:
                field_value = eval(transform_function)(field_value)

            filtered_item[field_name] = field_value

        return filtered_item

    async def get_data(self):
        try:
            logging.info(f"Requesting data from {self.config.get('url')}")

            response = self.session.get(self.config.get("url"), params=self.config.get("parameters"))

            if response.status_code == 200:
                json_response = json.loads(response.text)
                # if data.get("status").get("error_code"):      
                #     raise Exception(f'Error ({data.get("status").get("error_code")}) : {data.get("status").get("error_message")}')
                logging.debug(f"Filtering data...")
                # filtered_items = [self.apply_filter(item, self.config) for item in data["data"]]
                items = self.access_nested_fields(json_response, self.config["data_path"])
                filtered_items = [self.apply_filter(item, self.config) for item in items]

                return filtered_items
            else:  
                raise CustomApiException(response.json(), f"API Error {response.status_code}")
        except (Exception,ConnectionError, Timeout, TooManyRedirects) as e:
            raise e