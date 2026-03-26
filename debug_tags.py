import requests
import json

# Без ключа или с ключом
headers = {}
# Если есть ключ, раскомментируй:
# headers = {"Authorization": "Bearer твой_ключ"}

response = requests.get(
    "https://civitai.com/api/v1/images",
    params={"limit": 5, "nsfw": "X"},
    headers=headers
)

data = response.json()
for item in data["items"][:3]:
    print(f"\nID: {item['id']}")
    print(f"NSFW Level: {item.get('nsfwLevel')}")
    print(f"Tags: {item.get('tags', [])}")
    print("-" * 50)