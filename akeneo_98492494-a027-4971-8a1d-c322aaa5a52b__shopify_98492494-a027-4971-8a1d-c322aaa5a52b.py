from flask import Flask, jsonify
import requests
import base64
import urllib.parse

app = Flask(__name__)

# Akeneo and Plumbed configuration
AKENEO_BASE_URL = "https://your-akeneo-instance.com"
AKENEO_CLIENT_ID = "your_akeneo_client_id"
AKENEO_SECRET = "your_akeneo_secret"
AKENEO_USERNAME = "your_akeneo_username"
AKENEO_PASSWORD = "your_akeneo_password"

PLUMBED_USERNAME = "support@eplumbers.de"
PLUMBED_PASSWORD = "$upporT24*7!!"
PLUMBED_API_URL = "https://dod4opb42p8eg.cloudfront.net"
PLUMBED_ORGANIZATION_ID = "your_organization_id"
PLUMBED_CONNECTION_ID = "your_connection_id"
PLUMBED_SOURCE_OBJECT_NAME = "your_source_object_name"
PLUMBED_TRANSFORM_OBJECT_TYPE = "your_transform_object_type"
PLUMBED_UNIQUE_ID = "your_unique_id"
PLUMBED_PROPOSE_MAPPING = True

def get_akeneo_access_token():
    auth_string = f"{AKENEO_CLIENT_ID}:{AKENEO_SECRET}"
    auth_bytes = auth_string.encode('utf-8')
    auth_base64 = base64.b64encode(auth_bytes).decode('utf-8')

    headers = {
        "Authorization": f"Basic {auth_base64}",
        "Content-Type": "application/json"
    }

    data = {
        "grant_type": "password",
        "username": AKENEO_USERNAME,
        "password": AKENEO_PASSWORD
    }

    response = requests.post(f"{AKENEO_BASE_URL}/api/oauth/v1/token", headers=headers, json=data)

    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        raise Exception(f"Failed to authenticate with Akeneo: {response.text}")

def fetch_akeneo_products(access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    response = requests.get(f"{AKENEO_BASE_URL}/api/rest/v1/products", headers=headers)

    if response.status_code == 200:
        return response.json().get("_embedded", {}).get("items", [])
    else:
        raise Exception(f"Failed to fetch products from Akeneo: {response.text}")

def get_plumbed_access_token():
    auth_payload = {
        "grant_type": "password",
        "username": PLUMBED_USERNAME,
        "password": PLUMBED_PASSWORD,
        "scope": "",
        "client_id": "",
        "client_secret": ""
    }

    headers = {
        "accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    response = requests.post(f"{PLUMBED_API_URL}/token", headers=headers, data=auth_payload)

    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        raise Exception(f"Failed to authenticate with Plumbed: {response.text}")

def push_to_plumbed(access_token, product_data):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "application/json",
        "Content-Type": "application/json"
    }

    # Encode URLs in product data
    encoded_data = []
    for item in product_data:
        encoded_item = {
            key: (urllib.parse.quote_plus(value) if isinstance(value, str) and value.startswith("http") else value)
            for key, value in item.items()
        }
        encoded_data.append(encoded_item)

    payload = {
        "organization_id": PLUMBED_ORGANIZATION_ID,
        "connection_id": PLUMBED_CONNECTION_ID,
        "source_object_name": PLUMBED_SOURCE_OBJECT_NAME,
        "transform_object_type": PLUMBED_TRANSFORM_OBJECT_TYPE,
        "unique_id": PLUMBED_UNIQUE_ID,
        "propose_mapping": PLUMBED_PROPOSE_MAPPING,
        "data": encoded_data
    }

    response = requests.post(f"{PLUMBED_API_URL}/transfer_source_json", headers=headers, json=payload)

    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"Failed to push data to Plumbed: {response.text}")

@app.route('/fetchakeneoproducts', methods=['GET'])
def fetch_akeneo_products_endpoint():
    try:
        akeneo_access_token = get_akeneo_access_token()
        products = fetch_akeneo_products(akeneo_access_token)
        plumbed_access_token = get_plumbed_access_token()
        result = push_to_plumbed(plumbed_access_token, products)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)