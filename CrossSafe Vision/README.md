# CrossSafe Vision — integrated light-control demo

## How it works
- `yolo_camera.py` reads `http://ESP32_IP:81/stream`.
- When YOLO detects a person whose bottom-centre is inside the yellow crossing zone, it requests `GET /light?state=on` on port 82. It requests OFF when the zone clears.
- `app.py` polls `/status` on port 82 and reports controller connectivity and the GPIO state to the dashboard.
- `/api/events` only logs events; it does not send another light command that could override the detector.
- The dashboard shows the ESP32-reported GPIO state, not proof that the LEDs physically emit light.

## Files
`esp32_cam_light_controller.ino` (firmware), `app.py` (Flask backend), `templates/index.html` (dashboard), `yolo_camera.py` (YOLO + LED logic), `yolo11n.pt` (model), `check_esp32.py` (controller diagnostic), `requirements.txt`.

## 1. Upload the ESP32 sketch
1. Open `esp32_cam_light_controller.ino` in Arduino IDE.
2. Replace `YOUR_WIFI_NAME` and `YOUR_WIFI_PASSWORD` with your 2.4 GHz Wi-Fi credentials; keep them private.
3. This sketch expects the CameraWebServer helper files providing `board_config.h`, `startCameraServer()`, and `setupLedFlash()`. Configure the usual AI Thinker camera model for ESP32-CAM OV2640.
4. Upload and open Serial Monitor at 115200 baud. Note the IP address.
5. From the laptop, open `http://ESP32_IP:82/status`; expected JSON resembles `{"status":"online","connected":true,"light_on":false}`.
6. Test `/light?state=on`, `/status`, then `/light?state=off` using the same IP.

## 2. Install Python dependencies (Python 3.10/3.11 recommended)
From Command Prompt in this folder:
```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

## 3. Set addresses
Replace the example IP with the address shown in Serial Monitor. Run these commands in each terminal used below. Laptop and ESP32 must share a network that permits local-device communication; some phone hotspots isolate clients.
```bat
set ESP32_BASE_URL=http://10.192.39.28:82
set ESP32_IP=10.192.39.28
set CAMERA_URL=http://10.192.39.28:81/stream
set CROSSSAFE_BACKEND_URL=http://127.0.0.1:5001
```
PowerShell equivalent example: `$env:ESP32_BASE_URL="http://10.192.39.28:82"` and similarly set `ESP32_IP`, `CAMERA_URL`, `CROSSSAFE_BACKEND_URL`.

## 4. Start backend/dashboard
Terminal 1:
```bat
python app.py
```
Open `http://127.0.0.1:5001`; if it initially shows demo data, click **Switch to live data**.

## 5. Start detection and light control
Terminal 2: activate the environment, set the same addresses, then run:
```bat
python yolo_camera.py
```
Walk into the yellow zone to test ON, then leave it to test OFF. Press Q in the detector window to stop; the script requests OFF on shutdown.

## Troubleshooting “controller disconnected”
1. Open `http://ESP32_IP:82/status` directly on the laptop.
2. If it fails, check the Serial Monitor IP, Wi-Fi and local-device connectivity.
3. If direct status works, restart `app.py` from this folder with `ESP32_BASE_URL` set to `http://ESP32_IP:82`.
4. Open `http://127.0.0.1:5001/api/status` and inspect `controller.error`.
5. Ensure `templates/index.html` exists and switch the dashboard to live data.

## Electrical note
GPIO13 is a logic output, not a lamp power supply. Use a series resistor for one small LED; for multiple LEDs/a lamp use a suitable transistor/MOSFET driver and separate regulated supply, with common ground as required. Never connect mains voltage. GPIO13 is also associated with the SD interface, so do not use an SD card while using it for the LED.

This is a student showcase prototype, not a road-ready traffic safety system.
