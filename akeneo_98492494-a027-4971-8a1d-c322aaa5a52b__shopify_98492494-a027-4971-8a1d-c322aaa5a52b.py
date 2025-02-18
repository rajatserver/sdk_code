import requests
from flask import Flask, jsonify

app = Flask(__name__)

# Configuration
plumbed_base_url = "https://this.plumbed.com"
shopify_base_url = "https://this.myshopify.com"
shopify_api_version = "2023-10"
shopify_access_token = "your_shopify_access_token"  # Replace with your Shopify access token

# Plumbed credentials
plumbed_username = "your_plumbed_username"
plumbed_password = "your_plumbed_password"
organization_id = "your_organization_id"
connection_id = "your_connection_id"
transform_object_type = "your_transform_object_type"
source_object_name = "your_source_object_name"
target_object_name = "your_target_object_name"

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

def pull_from_plumbed(access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "organization_id": organization_id,
        "connection_id": connection_id,
        "transform_object_type": transform_object_type,
        "source_object_name": source_object_name,
        "target_object_name": target_object_name,
        "page": 1,
        "limit": 20
    }

    response = requests.post(f"{plumbed_base_url}/transfer-target-json", headers=headers, json=payload)

    if response.status_code in [200, 201]:
        return response.json().get("data", [])
    else:
        raise Exception(f"Failed to pull data from Plumbed: {response.text}")

def push_to_shopify(data):
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": shopify_access_token
    }

    for item in data:
        response = requests.post(f"{shopify_base_url}/admin/api/{shopify_api_version}/products.json", headers=headers, json={"product": item})

        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to push data to Shopify: {response.text}")

@app.route('/fetch_shopify_products', methods=['GET'])
def fetch_shopify_products():
    try:
        # Authenticate with Plumbed
        plumbed_token = plumbed_access_token()

        # Pull data from Plumbed
        data = pull_from_plumbed(plumbed_token)

        # Push data to Shopify
        push_to_shopify(data)

        return jsonify({"message": "Data successfully transferred from Plumbed to Shopify"}), 200

    except requests.exceptions.ConnectionError as e:
        return jsonify({"error": "ENOTFOUND", "message": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)