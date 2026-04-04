from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client['electravoter_db']
vdb = db['votes']

print("\n==== 🗳️ SECURE VOTE LEDGER (BLOCKCHAIN) ====\n")
votes = list(vdb.find().sort("timestamp", 1))

if not votes:
    print("No votes recorded yet. Go cast a vote in the app first!")
else:
    for idx, vote in enumerate(votes):
        print(f"Vote #{idx+1} | Voter: {vote.get('user_name', 'Unknown')}")
        print(f"  └─ User Hash:      {vote.get('user_hash', 'N/A')}")
        print(f"  └─ Previous Hash:  {vote.get('previous_hash', 'N/A')}")
        print(f"  └─ VOTE HASH:      {vote.get('vote_hash', 'N/A')}")
        print("-" * 50)
print("\n")
