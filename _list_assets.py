import json
import urllib.request
import urllib.error

token = "b2130f801ae8b87a339979e2965b400f8c6e6c5f"
repo = "miamura23/zapretik"

# Получаем список релизов
req = urllib.request.Request(f"https://gitverse.ru/api/v2/repos/{repo}/releases")
req.add_header("Authorization", f"token {token}")
req.add_header("User-Agent", "zapretik")

try:
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
        for rel in data:
            if rel.get("tag_name") == "v4.0.4":
                print(f"Release ID: {rel['id']}")
                print(f"Tag: {rel['tag_name']}")
                # Получаем ассеты
                assets_url = f"https://gitverse.ru/api/v2/repos/{repo}/releases/{rel['id']}/assets"
                req2 = urllib.request.Request(assets_url)
                req2.add_header("Authorization", f"token {token}")
                req2.add_header("User-Agent", "zapretik")
                with urllib.request.urlopen(req2, timeout=30) as r2:
                    assets = json.loads(r2.read().decode())
                    for asset in assets:
                        print(f"  Asset: {asset['name']} (ID: {asset['id']})")
                break
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code}")
    print(e.read().decode()[:500])
except Exception as e:
    print(f"Error: {e}")
