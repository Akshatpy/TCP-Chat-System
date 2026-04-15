import traceback
import os
from pymongo import MongoClient

try:
    c = MongoClient(os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017"), serverSelectionTimeoutMS=3000)
    print("Pinging db...")
    print(c.admin.command('ping'))
    print("Success!")
except Exception as e:
    print(f"Error: {e}")
    traceback.print_exc()
