from akeneo_pim_client import Client, ClientBuilder

# Replace with your Akeneo API credentials
client_id = 'your_client_id'
secret = 'your_secret'
username = 'your_username'
password = 'your_password'
base_url = 'https://demo.akeneo.com'

# Create a client
client = ClientBuilder().build(base_url, client_id, secret, username, password)

# Fetch categories from Akeneo API
categories = client.category.all()

# Print the fetched categories
for category in categories:
    print(category)