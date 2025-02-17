from flask import Flask, jsonify
import requests
import urllib.parse

app = Flask(__name__)

# Base URL for Akeneo
AKENEO_BASE_URL = "https://your-akeneo-instance.com/api/rest/v1"

# Akeneo credentials
AKENEO_CLIENT_ID = "your_akeneo_client_id"
AKENEO_SECRET = "your_akeneo_secret"
AKENEO_USERNAME = "your_akeneo_username"
AKENEO_PASSWORD = "your_akeneo_password"

# Plumbed credentials
PLUMBED_USERNAME = "your_plumbed_username"
PLUMBED_PASSWORD = "your_plumbed_password"
PLUMBED_API_URL = "https://your-plumbed-instance.com/api"

# Plumbed connection details
ORGANIZATION_ID = "your_organization_id"
CONNECTION_ID = "your_connection_id"
SOURCE_OBJECT_NAME = "your_source_object_name"
TRANSFORM_OBJECT_TYPE = "your_transform_object_type"
UNIQUE_ID = "your_unique_id"
PROPOSE_MAPPING = True

def get_akeneo_access_token():
    auth_url = f"{AKENEO_BASE_URL}/oauth/v1/token"
    auth_payload = {
        "grant_type": "password",
        "client_id": AKENEO_CLIENT_ID,
        "client_secret": AKENEO_SECRET,
        "username": AKENEO_USERNAME,
        "password": AKENEO_PASSWORD
    }
    response = requests.post(auth_url, data=auth_payload)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        raise Exception(f"Failed to authenticate with Akeneo: {response.text}")

def fetch_akeneo_products(access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    response = requests.get(f"{AKENEO_BASE_URL}/products", headers=headers)
    if response.status_code == 200:
        return response.json().get("_embedded", {}).get("items", [])
    else:
        raise Exception(f"Failed to fetch products from Akeneo: {response.text}")

def plumbed_access_token():
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
    response = requests.post(PLUMBED_API_URL, headers=headers, data=auth_payload)
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
        "organization_id": ORGANIZATION_ID,
        "connection_id": CONNECTION_ID,
        "source_object_name": SOURCE_OBJECT_NAME,
        "transform_object_type": TRANSFORM_OBJECT_TYPE,
        "unique_id": UNIQUE_ID,
        "propose_mapping": PROPOSE_MAPPING,
        "data": encoded_data
    }

    response = requests.post(PLUMBED_API_URL, headers=headers, json=payload)
    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"Failed to push data to Plumbed: {response.text}")

@app.route('/fetchakeneo_98492494-a027-4971-8a1d-c322aaa5a52bproducts', methods=['GET'])
def fetch_and_push_products():
    try:
        # Authenticate with Akeneo
        akeneo_token = get_akeneo_access_token()
        
        # Fetch products from Akeneo
        products = fetch_akeneo_products(akeneo_token)
        
        # Authenticate with Plumbed
        plumbed_token = plumbed_access_token()
        
        # Push products to Plumbed
        result = push_to_plumbed(plumbed_token, products)
        
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)