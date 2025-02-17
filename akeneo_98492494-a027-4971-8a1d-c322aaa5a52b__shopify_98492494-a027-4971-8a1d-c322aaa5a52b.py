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

# Step 2: Authenticate Source API and Pull Data
def get_source_access_token(api_url, client_id, client_secret):
    # Implement source API authentication logic here
    pass

def pull_data_from_source(api_url, access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "application/json"
    }
    response = requests.get(api_url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to pull data from source: {response.text}")

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

# Step 5: Authenticate Target and Push Data to Target
def get_target_access_token(api_url, client_id, client_secret):
    # Implement target API authentication logic here
    pass

def push_to_target(api_url, access_token, product_data):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "application/json",
        "Content-Type": "application/json"
    }
    response = requests.post(api_url, headers=headers, json=product_data)

    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"Failed to push data to target: {response.text}")