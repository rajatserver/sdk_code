import requests

# Replace with your Akeneo API credentials
client_id = 'your_client_id'
secret = 'your_secret'
username = 'your_username'
password = 'your_password'
base_url = 'https://demo.akeneo.com'

# Step 1: Get the access token
def get_access_token():
    url = f"{base_url}/api/oauth/v1/token"
    payload = {
        'grant_type': 'password',
        'client_id': client_id,
        'client_secret': secret,
        'username': username,
        'password': password
    }
    response = requests.post(url, data=payload)
    response_data = response.json()
    return response_data['access_token']

# Step 2: Pull data from the Akeneo API
def get_categories(access_token):
    url = f"{base_url}/api/rest/v1/categories"
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    response = requests.get(url, headers=headers)
    return response.json()

# Main execution
if __name__ == "__main__":
    token = get_access_token()
    categories = get_categories(token)
    print(categories)