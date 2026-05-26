import requests
import json

# Test update check API
response = requests.get('http://127.0.0.1:5555/api/update/check')
print(f"Status Code: {response.status_code}")
print(f"\nResponse JSON:")
print(json.dumps(response.json(), indent=2, ensure_ascii=False))
