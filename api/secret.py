import os

API_NAMES = ["edamam", "usda"]

API = {
    "edamam": {
        "homepage": "https://developer.edamam.com/",
        "url": "https://api.edamam.com/api/food-database/v2/parser?",
        "auth": {
            "app_id": os.environ.get("EDAMAM_APP_ID", ""),
            "app_key": os.environ.get("EDAMAM_APP_KEY", ""),
        },
        "query_str": {
            "ingr": "",
            "nutrition-type": "logging",
        }
    },
    "usda": {
        "homepage": "https://fdc.nal.usda.gov/api-guide.html",
        "url": "https://api.nal.usda.gov/fdc/v1/foods/search?",
        "auth": {
            "api_key": os.environ.get("USDA_API_KEY", ""),
        }
    }
}


def get_response_from_edamam(response):
    response_dict = response.json()
    result = response_dict['parsed']
    if len(result) == 0:
        result = response_dict['hints']
    result = result[0]
    food_info = result['food']

    food_label = response_dict["text"]
    food_nutrients = food_info['nutrients']

    calories = food_nutrients.get('ENERC_KCAL', 0)
    protein = food_nutrients.get('PROCNT', 0)
    fat = food_nutrients.get('FAT', 0)
    carbs = food_nutrients.get('CHOCDF', 0)
    fiber = food_nutrients.get('FIBTG', 0)

    return {
        "name": food_label,
        "nutrients": {
            "calories": calories,
            "protein": protein,
            "fat": fat,
            "carbs": carbs,
            "fiber": fiber
        }
    }


def get_response(api_name, response):
    assert api_name in API_NAMES, "API not supported"
    try:
        if api_name == 'edamam':
            return get_response_from_edamam(response)
    except Exception:
        return None
