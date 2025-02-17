import requests
import urllib.parse

# Step 1: Generate Plumbed Access Token
def get_plumbed_access_token(api_url, username, password):
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

    response = requests.post(api_url, headers=headers, data=auth_payload)

    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        raise Exception(f"Failed to authenticate with Plumbed: {response.text}")

# Step 2: Authenticate and Pull Data from Akeneo
def pull_data_from_akeneo(api_url, akeneo_token):
    headers = {
        "Authorization": f"Bearer {akeneo_token}",
        "accept": "application/json"
    }

    response = requests.get(api_url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to pull data from Akeneo: {response.text}")

# Step 3: Push Data to Plumbed
def push_to_plumbed(api_url, access_token, product_data, organization_id, connection_id, source_object_name, transform_object_type, unique_id, propose_mapping):
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

    response = requests.post(api_url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"Failed to push data to Plumbed: {response.text}")

# Step 4: Pull Data from Plumbed
def pull_from_plumbed(api_url, access_token, organization_id, connection_id, transform_object_type):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = {
        "organization_id": organization_id,
        "connection_id": connection_id,
        "transform_object_type": transform_object_type,
    }

    response = requests.post(api_url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"Failed to pull data from Plumbed: {response.text}")

# Step 5: Authenticate and Push Data to Shopify
def push_data_to_shopify(api_url, shopify_token, product_data):
    headers = {
        "X-Shopify-Access-Token": shopify_token,
        "accept": "application/json",
        "Content-Type": "application/json"
    }

    response = requests.post(api_url, headers=headers, json=product_data)

    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"Failed to push data to Shopify: {response.text}")

# Example usage
# Note: Replace the placeholders with actual values
plumbed_api_url = "https://plumbed.example.com/auth"
akeneo_api_url = "https://akeneo.example.com/api/products"
shopify_api_url = "https://shopify.example.com/admin/api/2023-01/products.json"

username = "your_username"
password = "your_password"
akeneo_token = "your_akeneo_token"
shopify_token = "your_shopify_token"

organization_id = "your_organization_id"
connection_id = "your_connection_id"
source_object_name = "your_source_object_name"
transform_object_type = "your_transform_object_type"
unique_id = "your_unique_id"
propose_mapping = True

# Get Plumbed Access Token
plumbed_access_token = get_plumbed_access_token(plumbed_api_url, username, password)

# Pull Data from Akeneo
akeneo_data = pull_data_from_akeneo(akeneo_api_url, akeneo_token)

# Push Data to Plumbed
push_to_plumbed(plumbed_api_url, plumbed_access_token, akeneo_data, organization_id, connection_id, source_object_name, transform_object_type, unique_id, propose_mapping)

# Pull Data from Plumbed
plumbed_data = pull_from_plumbed(plumbed_api_url, plumbed_access_token, organization_id, connection_id, transform_object_type)

# Push Data to Shopify
push_data_to_shopify(shopify_api_url, shopify_token, plumbed_data)