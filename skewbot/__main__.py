import os
import sys
import dotenv
from .bot import client, tree, test_guild

dotenv.load_dotenv()

token = os.getenv("TOKEN")


if len(sys.argv) > 1 and sys.argv[1] == "clear":
    tree.clear_commands(guild=None)

client.run(token)
