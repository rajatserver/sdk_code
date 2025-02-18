from flask import Flask, jsonify
import requests
import urllib.parse

app = Flask(__name__)

# Configuration
akeneo_base_url = "https://demo.akeneo.com"
akeneo_token_url = f"{akeneo_base_url}/api/oauth/v1/token"
akeneo_client_id = "your_akeneo_client_id"
akeneo_client_secret = "your_akeneo_client_secret"
akeneo_username = "your_akeneo_username"
akeneo_password = "your_akeneo_password"

plumbed_base_url = "https://your_plumbed_base_url"
plumbed_username = "your_plumbed_username"
plumbed_password = "your_plumbed_password"
organization_id = "your_organization_id"
connection_id = "your_connection_id"
source_object_name = "your_source_object_name"
transform_object_type = "your_transform_object_type"
unique_id = "your_unique_id"
propose_mapping = True

def get_akeneo_access_token():
    auth_payload = {
        "grant_type": "password",
        "username": akeneo_username,
        "password": akeneo_password,
        "client_id": akeneo_client_id,
        "client_secret": akeneo_client_secret
    }
    headers = {
        "accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    response = requests.post(akeneo_token_url, headers=headers, data=auth_payload)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        raise Exception(f"Failed to authenticate with Akeneo: {response.text}")

def fetch_akeneo_products(access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "application/json"
    }
    response = requests.get(f"{akeneo_base_url}/api/rest/v1/products", headers=headers)
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

def push_to_plumbed(access_token, product_data):
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
        # Authenticate with Akeneo
        akeneo_access_token = get_akeneo_access_token()
        
        # Fetch products from Akeneo
        products = fetch_akeneo_products(akeneo_access_token)
        
        # Authenticate with Plumbed
        plumbed_token = plumbed_access_token()
        
        # Push products to Plumbed
        result = push_to_plumbed(plumbed_token, products)
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)