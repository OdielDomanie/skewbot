import os
import dotenv
from .bot import client

dotenv.load_dotenv()

token = os.getenv("TOKEN")


client.run(token)
