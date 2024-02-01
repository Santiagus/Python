import json

def apply_filter(item, filter_config):
    filtered_item = {}
    for field_config in filter_config["fields"]:
        field_name = field_config["name"]
        field_source = field_config["source"]
        default_value = field_config["default"]

        # Access the nested fields using the provided source path
        field_value = item
        try:
            for key in field_source.split("."):
                field_value = field_value[key]
        except (KeyError, TypeError):
            field_value = default_value

        # Apply transformation if specified
        transform_function = field_config.get("transform")
        if transform_function:
            field_value = eval(transform_function)(field_value)

        filtered_item[field_name] = field_value

    return filtered_item

# Load filter configuration from the file
with open("filter_config.json", "r") as config_file:
    filter_config = json.load(config_file)

# Example usage
# data = {"data": [...]}
with open("coinmarket_output.json", "r") as data_file:
    data = json.load(data_file)

filtered_items = [apply_filter(item, filter_config) for item in data["data"]]
print(json.dumps(filtered_items, indent=2))

# Save filtered data to a file
output_file_path = "coinmarket_genericfilter_output.json"
with open(output_file_path, "w") as output_file:
    json.dump(filtered_items, output_file, indent=2)
