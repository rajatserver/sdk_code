from flask import Flask, jsonify
import requests
import urllib.parse

app = Flask(__name__)

# Base URLs
akeneo_base_url = "https://demo.akeneo.com/api/rest/v1"
plumbed_base_url = "https://your-plumbed-url.com"

# Akeneo credentials
akeneo_token = "your_akeneo_access_token"

# Plumbed credentials
username = "your_plumbed_username"
password = "your_plumbed_password"

# Plumbed connection details
organization_id = "your_organization_id"
connection_id = "your_connection_id"
source_object_name = "your_source_object_name"
transform_object_type = "your_transform_object_type"
unique_id = "your_unique_id"
propose_mapping = True

def plumbed_access_token():
    auth_payload = {
        "grant_type": "password",
        "username": username,
        "password": password,
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

def push_to_plumbed(product_data, access_token):
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

@app.route('/fetchakeneo_98492494-a027-4971-8a1d-c322aaa5a52bproducts', methods=['GET'])
def fetch_and_push_products():
    # Fetch products from Akeneo
    headers = {
        "Authorization": f"Bearer {akeneo_token}",
        "accept": "application/json"
    }
    response = requests.get(f"{akeneo_base_url}/products", headers=headers)

    if response.status_code == 200:
        product_data = response.json().get('_embedded', {}).get('items', [])
    else:
        return jsonify({"error": "Failed to fetch products from Akeneo"}), response.status_code

    # Authenticate with Plumbed
    try:
        access_token = plumbed_access_token()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Push data to Plumbed
    try:
        result = push_to_plumbed(product_data, access_token)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)