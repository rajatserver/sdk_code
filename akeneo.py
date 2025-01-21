from akeneo_pim_client import Client, ClientBuilder

# Replace with your Akeneo API credentials
client_id = 'your_client_id'
secret = 'your_secret'
username = 'your_username'
password = 'your_password'
base_url = 'https://demo.akeneo.com'

# Create a client
client = ClientBuilder().build(base_url, client_id, secret, username, password)

# Fetch products from Akeneo API with pagination
page = 1
items_per_page = 10  # Adjust the number of items per page as needed
while True:
    products = client.product.all(page=page, limit=items_per_page)
    
    if not products:
        break  # Exit the loop if no more products are returned
    
    # Print the fetched products
    for product in products:
        print(product)
    
    page += 1  # Move to the next page