import requests
from requests.auth import HTTPBasicAuth

# Replace with your Akeneo API credentials
client_id = 'your_client_id'
secret = 'your_secret'
username = 'your_username'
password = 'your_password'
base_url = 'https://test_akeneo_sdk.com'

# Get the access token
token_url = f"{base_url}/api/oauth/v1/token"
data = {
    'grant_type': 'password',
    'client_id': client_id,
    'client_secret': secret,
    'username': username,
    'password': password
}

response = requests.post(token_url, data=data)
access_token = response.json().get('access_token')

# Fetch products from Akeneo API
products_url = f"{base_url}/api/rest/v1/products"
headers = {
    'Authorization': f'Bearer {access_token}'
}

products_response = requests.get(products_url, headers=headers)

# Print the fetched products
if products_response.status_code == 200:
    products = products_response.json()
    for product in products['_embedded']['items']:
        print(product)
else:
    print("Failed to fetch products:", products_response.status_code, products_response.text)