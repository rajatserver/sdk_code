import requests

# Replace with your Akeneo API credentials
client_id = 'your_client_id'
secret = 'your_secret'
username = 'your_username'
password = 'your_password'
base_url = 'https://demo.akeneo.com'

# Step 1: Get the access token
token_url = f'{base_url}/api/oauth/v1/token'
data = {
    'grant_type': 'password',
    'client_id': client_id,
    'client_secret': secret,
    'username': username,
    'password': password,
}

response = requests.post(token_url, data=data)
response_data = response.json()
access_token = response_data['access_token']

# Step 2: Use the access token to pull data from the Akeneo API
headers = {
    'Authorization': f'Bearer {access_token}',
    'Content-Type': 'application/json',
}

# Example: Pull categories data
categories_url = f'{base_url}/api/rest/v1/categories'
categories_response = requests.get(categories_url, headers=headers)

if categories_response.status_code == 200:
    categories_data = categories_response.json()
    print(categories_data)
else:
    print(f'Error: {categories_response.status_code} - {categories_response.text}')