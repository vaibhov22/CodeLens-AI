import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_FILE = "/app/history.json"

def save_query(username, query, answer):

    print("🔥 save_query called")
    print("Saving at:", HISTORY_FILE)

    record = {
        "user": username,
        "query": query,
        "answer": answer,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    try:
        with open(HISTORY_FILE, "r") as f:
            data = json.load(f)
    except:
        data = []

    data.append(record)

    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)