from akeneo_pim_client import Client, Credentials

# Set up your Akeneo API credentials
credentials = Credentials(
    client_id='your_client_id',
    secret='your_secret',
    username='your_username',
    password='your_password',
    base_url='https://demo.akeneo.com'
)

# Create a client instance
client = Client(credentials)

# Fetch categories from Akeneo API
categories = client.category.all()

# Print the fetched categories
for category in categories:
    print(category)