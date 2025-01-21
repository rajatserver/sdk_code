import requests

# Replace with your Akeneo API credentials
client_id = 'your_client_id'
secret = 'your_secret'
username = 'your_username'
password = 'your_password'
base_url = 'https://demo.akeneo.com'

# Authenticate and get access token
auth_url = f"{base_url}/api/oauth/v1/token"
auth_data = {
    'grant_type': 'password',
    'client_id': client_id,
    'client_secret': secret,
    'username': username,
    'password': password
}

response = requests.post(auth_url, data=auth_data)
response_data = response.json()
access_token = response_data['access_token']

# Fetch products from Akeneo API with pagination
page = 1
items_per_page = 10  # Adjust the number of items per page as needed

while True:
    products_url = f"{base_url}/api/rest/v1/products?page={page}&limit={items_per_page}"
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    
    products_response = requests.get(products_url, headers=headers)
    products = products_response.json()['_embedded']['items']
    
    if not products:
        break  # Exit the loop if no more products are returned
    
    # Print the fetched products
    for product in products:
        print(product)
    
    page += 1  # Move to the next page