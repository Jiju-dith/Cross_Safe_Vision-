import os
import requests

base = os.getenv("ESP32_BASE_URL", "http://10.192.39.28:82").rstrip("/")
print("Checking ESP32 controller:", base)
try:
    response = requests.get(f"{base}/status", timeout=3)
    print("HTTP:", response.status_code)
    print("Body:", response.text)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("light_on"), bool):
        raise ValueError("Expected JSON containing boolean 'light_on'")
    print("Controller reachable. Reported light:", "ON" if data["light_on"] else "OFF")
except Exception as exc:
    print("Controller check failed:", exc)
    print("Check ESP32 IP, Wi-Fi, port 82, and local network access.")
