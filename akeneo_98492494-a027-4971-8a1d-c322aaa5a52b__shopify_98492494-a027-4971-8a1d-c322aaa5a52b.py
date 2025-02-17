import base64
import requests
import urllib.parse
from flask import Flask, jsonify

app = Flask(__name__)

# Akeneo API credentials
akeneo_client_id = 'your_akeneo_client_id'
akeneo_secret = 'your_akeneo_secret'
akeneo_username = 'your_akeneo_username'
akeneo_password = 'your_akeneo_password'

# Plumbed API credentials
plumbed_username = 'support@eplumbers.de'
plumbed_password = '$upporT24*7!!'

# Akeneo API URL
akeneo_api_url = 'https://api.akeneo.com/api-reference-index.html'

# Plumbed API URLs
plumbed_token_url = 'https://dod4opb42p8eg.cloudfront.net/token'
plumbed_push_url = 'https://dod4opb42p8eg.cloudfront.net/redoc#tag/Transfer/operation/process_transfer_source_data_transfer_source_json_post'

# Function to authenticate with Akeneo
def authenticate_akeneo():
    auth_string = f"{akeneo_client_id}:{akeneo_secret}"
    auth_bytes = auth_string.encode('ascii')
    base64_bytes = base64.b64encode(auth_bytes)
    base64_auth = base64_bytes.decode('ascii')

    headers = {
        'Authorization': f'Basic {base64_auth}',
        'Content-Type': 'application/json'
    }

    response = requests.post(akeneo_api_url, headers=headers, json={
        'username': akeneo_username,
        'password': akeneo_password
    })

    if response.status_code == 200:
        return response.json().get('access_token')
    else:
        raise Exception(f"Failed to authenticate with Akeneo: {response.text}")

# Function to authenticate with Plumbed
def authenticate_plumbed():
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

    response = requests.post(plumbed_token_url, headers=headers, data=auth_payload)

    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        raise Exception(f"Failed to authenticate with Plumbed: {response.text}")

# Function to fetch products from Akeneo
def fetch_akeneo_products():
    akeneo_token = authenticate_akeneo()
    headers = {
        'Authorization': f'Bearer {akeneo_token}',
        'Content-Type': 'application/json'
    }

    response = requests.get(f"{akeneo_api_url}/products", headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to fetch products from Akeneo: {response.text}")

# Function to push products to Plumbed
def push_to_plumbed(product_data):
    plumbed_token = authenticate_plumbed()
    headers = {
        "Authorization": f"Bearer {plumbed_token}",
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
        "organization_id": "your_organization_id",
        "connection_id": "your_connection_id",
        "source_object_name": "your_source_object_name",
        "transform_object_type": "your_transform_object_type",
        "unique_id": "your_unique_id",
        "propose_mapping": "your_propose_mapping",
        "data": encoded_data
    }

    response = requests.post(plumbed_push_url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"Failed to push data to Plumbed: {response.text}")

@app.route('/fetchakeneoproducts', methods=['GET'])
def fetch_akeneo_products_endpoint():
    try:
        products = fetch_akeneo_products()
        push_to_plumbed(products)
        return jsonify({"message": "Products fetched and pushed successfully."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)