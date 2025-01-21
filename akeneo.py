from akeneo_pim_client import Client, ClientBuilder

# Replace with your Akeneo API credentials
client_id = 'your_client_id'
secret = 'your_secret'
username = 'your_username'
password = 'your_password'
base_url = 'https://demo.akeneo.com'

# Create a client
client = ClientBuilder().build(base_url, client_id, secret, username, password)

# Fetch products from Akeneo API
products = client.product.all()

# Print the fetched products
for product in products:
    print(product)