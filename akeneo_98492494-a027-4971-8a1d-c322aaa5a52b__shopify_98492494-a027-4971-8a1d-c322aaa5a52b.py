from flask import Flask, jsonify
import requests
import urllib.parse

app = Flask(__name__)

# Base URLs
akeneo_base_url = "https://your-akeneo-instance.com/api"
plumbed_base_url = "https://your-plumbed-instance.com"

# Akeneo credentials
akeneo_client_id = "your_akeneo_client_id"
akeneo_secret = "your_akeneo_secret"
akeneo_username = "your_akeneo_username"
akeneo_password = "your_akeneo_password"

# Plumbed credentials
plumbed_username = "your_plumbed_username"
plumbed_password = "your_plumbed_password"

# Plumbed connection details
organization_id = "your_organization_id"
connection_id = "your_connection_id"
source_object_name = "your_source_object_name"
transform_object_type = "your_transform_object_type"
unique_id = "your_unique_id"
propose_mapping = True

def authenticate_akeneo():
    auth_url = f"{akeneo_base_url}/oauth/v1/token"
    auth_payload = {
        "grant_type": "password",
        "client_id": akeneo_client_id,
        "client_secret": akeneo_secret,
        "username": akeneo_username,
        "password": akeneo_password
    }
    response = requests.post(auth_url, data=auth_payload)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        raise Exception(f"Failed to authenticate with Akeneo: {response.text}")

def fetch_akeneo_products():
    access_token = authenticate_akeneo()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    response = requests.get(f"{akeneo_base_url}/rest/v1/products", headers=headers)
    if response.status_code == 200:
        return response.json().get('_embedded', {}).get('items', [])
    else:
        raise Exception(f"Failed to fetch products from Akeneo: {response.text}")

def plumbed_access_token():
    auth_payload = {
        "grant_type": "password",
        "username": plumbed_username,
        "password": plumbed_password,
        "scope": "",
        "client_id": "",
        "client_secret": ""
    }
    headers = {
        "accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    response = requests.post(f"{plumbed_base_url}/token", headers=headers, data=auth_payload)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        raise Exception(f"Failed to authenticate with Plumbed: {response.text}")

def push_to_plumbed(product_data):
    access_token = plumbed_access_token()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "application/json",
        "Content-Type": "application/json"
    }
    encoded_data = []
    for item in product_data:
        encoded_item = {
            key: (urllib.parse.quote_plus(value) if isinstance(value, str) and value.startswith("http") else value)
            for key, value in item.items()
        }
        encoded_data.append(encoded_item)

    payload = {
        "organization_id": organization_id,
        "connection_id": connection_id,
        "source_object_name": source_object_name,
        "transform_object_type": transform_object_type,
        "unique_id": unique_id,
        "propose_mapping": propose_mapping,
        "data": encoded_data
    }

    response = requests.post(f"{plumbed_base_url}/transfer-source-json", headers=headers, json=payload)
    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"Failed to push data to Plumbed: {response.text}")

@app.route('/fetch_akeneo_products', methods=['GET'])
def fetch_and_push_products():
    try:
        products = fetch_akeneo_products()
        result = push_to_plumbed(products)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)