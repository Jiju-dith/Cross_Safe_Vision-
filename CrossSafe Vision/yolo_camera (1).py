import cv2
import time
import os
import requests
from datetime import datetime, timezone
from ultralytics import YOLO

# ============================================================
# CROSSSAFE VISION - ESP32-CAM + YOLO + FLASK DASHBOARD + LED
# ============================================================

# ESP32-CAM addresses
# Update via environment variables if the ESP32 address changes.
ESP32_BASE_URL = os.getenv(
    "ESP32_BASE_URL", "http://172.20.10.3:82").rstrip("/")
ESP32_IP = os.getenv("ESP32_IP", ESP32_BASE_URL.split(
    "://", 1)[-1].split(":", 1)[0])
CAMERA_URL = os.getenv("CAMERA_URL", f"http://{ESP32_IP}:81/stream")
LED_CONTROL_URL = f"{ESP32_BASE_URL}/light"
BACKEND_URL = os.getenv("CROSSSAFE_BACKEND_URL",
                        "http://127.0.0.1:5001").rstrip("/")

MODEL_PATH = "yolo11n.pt"

# Crossing zone as a proportion of the video frame
ZONE_X1_RATIO = 0.25
ZONE_Y1_RATIO = 0.02
ZONE_X2_RATIO = 0.75
ZONE_Y2_RATIO = 0.98

CONFIDENCE_THRESHOLD = 0.35
EVENT_COOLDOWN = 5
PERSON_ABSENT_SECONDS = 2
HEARTBEAT_INTERVAL = 2

RECONNECT_DELAY = 2
OPEN_TIMEOUT_MS = 5000
READ_TIMEOUT_MS = 5000

WINDOW_NAME = "CrossSafe Vision - Pedestrian Detection"

session = requests.Session()
led_state = None


# ============================================================
# ESP32-CAM LED CONTROL
# ============================================================

def set_led(pedestrian_detected):
    """Turn the external LED on/off, only sending commands when state changes."""
    global led_state

    desired_state = "on" if pedestrian_detected else "off"

    if led_state == desired_state:
        return

    try:
        response = session.get(
            LED_CONTROL_URL,
            params={"state": desired_state},
            timeout=1.5,
        )
        response.raise_for_status()
        led_state = desired_state
        print(f"External LED {desired_state.upper()}")
    except requests.RequestException as error:
        print(f"Could not control ESP32-CAM LED: {error}")


# ============================================================
# CAMERA CONNECTION
# ============================================================

def open_camera():
    """Open the ESP32-CAM stream with timeouts where supported."""
    print(f"Connecting to ESP32-CAM: {CAMERA_URL}")

    try:
        camera = cv2.VideoCapture(
            CAMERA_URL,
            cv2.CAP_FFMPEG,
            [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                OPEN_TIMEOUT_MS,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                READ_TIMEOUT_MS,
            ],
        )
    except (TypeError, cv2.error):
        # Fallback for OpenCV versions without timeout parameters.
        camera = cv2.VideoCapture(CAMERA_URL, cv2.CAP_FFMPEG)

    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if camera.isOpened():
        print("ESP32-CAM connection opened.")
        return camera

    print("Could not open ESP32-CAM stream.")
    camera.release()
    return None


def reconnect_camera(camera):
    """Release a failed stream and try to reconnect."""
    if camera is not None:
        camera.release()

    # Fail safe: switch the LED off while the camera stream is unavailable.
    set_led(False)

    print(f"Reconnecting in {RECONNECT_DELAY} seconds...")
    time.sleep(RECONNECT_DELAY)
    return open_camera()


# ============================================================
# BACKEND COMMUNICATION
# ============================================================

def send_heartbeat(connected):
    """Report camera connection status to the dashboard."""
    try:
        response = session.post(
            f"{BACKEND_URL}/api/camera-heartbeat",
            json={"connected": connected},
            timeout=2,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"Heartbeat could not be sent: {error}")


def send_detection_event(track_id, confidence, people_in_zone):
    """Send a pedestrian detection event to the Flask backend."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "pedestrian_detected",
        "source": "esp32-cam",
        "track_id": track_id,
        "confidence": round(float(confidence), 3),
        "person_count": people_in_zone,
    }

    try:
        response = session.post(
            f"{BACKEND_URL}/api/events",
            json=event,
            timeout=3,
        )
        response.raise_for_status()
        print("Pedestrian event sent to dashboard.")
    except requests.RequestException as error:
        print(f"Could not send event to dashboard: {error}")


# ============================================================
# CROSSING ZONE
# ============================================================

def get_crossing_zone(frame_width, frame_height):
    """Calculate the crossing zone from the current frame size."""
    x1 = int(frame_width * ZONE_X1_RATIO)
    y1 = int(frame_height * ZONE_Y1_RATIO)
    x2 = int(frame_width * ZONE_X2_RATIO)
    y2 = int(frame_height * ZONE_Y2_RATIO)
    return x1, y1, x2, y2


def point_inside_zone(x, y, zone):
    """Check whether a pedestrian's bottom-center is in the zone."""
    x1, y1, x2, y2 = zone
    return x1 <= x <= x2 and y1 <= y <= y2


# ============================================================
# MAIN PROGRAM
# ============================================================

def main():
    print("\n===================================")
    print("       CROSSSAFE VISION")
    print("===================================")

    print("\nLoading YOLO model...")

    try:
        model = YOLO(MODEL_PATH)
    except Exception as error:
        print(f"Could not load YOLO model: {error}")
        print("Check that yolo11n.pt exists and Ultralytics is installed.")
        return

    print("YOLO model loaded.")

    camera = open_camera()

    if camera is None:
        print("Camera connection failed. Check the camera IP and Wi-Fi.")
        set_led(False)
        return

    last_heartbeat = 0
    last_event_time = 0
    last_person_in_zone_time = 0

    # Prevent repeated dashboard events while the same crossing is occupied.
    event_armed = True

    frame_failures = 0
    max_frame_failures = 3

    print("\nWalk through the yellow crossing zone to test detection.")
    print("The LED turns ON while a person is in the crossing zone.")
    print("Press Q in the video window to stop.\n")

    try:
        while True:
            success, frame = camera.read()

            # Handle a lost or invalid frame.
            if not success or frame is None:
                frame_failures += 1
                print(
                    f"Camera frame failed "
                    f"({frame_failures}/{max_frame_failures})."
                )

                if frame_failures >= max_frame_failures:
                    send_heartbeat(False)
                    set_led(False)
                    camera = reconnect_camera(camera)

                    if camera is None:
                        print("Reconnect failed. Retrying...")
                        time.sleep(RECONNECT_DELAY)
                        camera = open_camera()

                    if camera is None:
                        continue

                    frame_failures = 0
                else:
                    time.sleep(0.2)

                continue

            frame_failures = 0

            height, width = frame.shape[:2]
            zone = get_crossing_zone(width, height)

            # Run YOLO pedestrian detection and tracking.
            try:
                results = model.track(
                    frame,
                    persist=True,
                    classes=[0],  # COCO class 0 = person
                    conf=CONFIDENCE_THRESHOLD,
                    verbose=False,
                    tracker="bytetrack.yaml",
                    imgsz=320,
                )
            except Exception as error:
                print(f"YOLO detection error: {error}")
                set_led(False)
                time.sleep(0.2)
                continue

            people_in_zone = 0
            best_confidence = 0.0
            best_track_id = None
            current_time = time.time()

            # Process detected people.
            for result in results:
                if result.boxes is None:
                    continue

                boxes = result.boxes

                for index, box in enumerate(boxes):
                    if box.xyxy is None or len(box.xyxy) == 0:
                        continue

                    x1, y1, x2, y2 = map(
                        int, box.xyxy[0].cpu().tolist()
                    )
                    confidence = float(box.conf[0].item())

                    # Bottom-center point of the person.
                    center_x = int((x1 + x2) / 2)
                    # bottom_y = y2
                    center_y = int((y1 + y2*3) / 4)

                    inside_zone = point_inside_zone(
                        center_x, center_y, zone
                    )

                    # Read tracking ID if available.
                    track_id = None
                    if boxes.id is not None:
                        try:
                            track_id = int(boxes.id[index].item())
                        except (IndexError, ValueError, TypeError):
                            track_id = None

                    # Draw the person bounding box.
                    box_color = (0, 255, 0) if inside_zone else (255, 180, 0)
                    cv2.rectangle(
                        frame, (x1, y1), (x2, y2), box_color, 2
                    )

                    label = f"Person {confidence:.2f}"
                    if track_id is not None:
                        label = f"ID {track_id} | {confidence:.2f}"

                    cv2.putText(
                        frame,
                        label,
                        (x1, max(20, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        box_color,
                        2,
                    )

                    # Count people whose bottom-center is in the zone.
                    if inside_zone:
                        people_in_zone += 1
                        last_person_in_zone_time = current_time

                        if confidence > best_confidence:
                            best_confidence = confidence
                            best_track_id = track_id

            # LED control: ON if at least one pedestrian is in the zone.
            # OFF when the crossing zone is clear.
            set_led(people_in_zone > 0)

            # Create a dashboard event when someone enters the zone.
            if people_in_zone > 0:
                if (
                    event_armed
                    and current_time - last_event_time >= EVENT_COOLDOWN
                ):
                    print(
                        f"PEDESTRIAN DETECTED | "
                        f"People in zone: {people_in_zone}"
                    )

                    send_detection_event(
                        best_track_id,
                        best_confidence,
                        people_in_zone,
                    )

                    last_event_time = current_time
                    event_armed = False

            # Rearm after the zone has been clear for a while.
            elif (
                current_time - last_person_in_zone_time
                >= PERSON_ABSENT_SECONDS
            ):
                event_armed = True

            # Draw the crossing zone and status.
            zx1, zy1, zx2, zy2 = zone
            cv2.rectangle(
                frame, (zx1, zy1), (zx2, zy2), (0, 255, 255), 2
            )

            cv2.putText(
                frame,
                "CROSSING ZONE",
                (zx1, max(20, zy1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 255),
                2,
            )

            status = f"People in zone: {people_in_zone}"
            cv2.putText(
                frame,
                status,
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 255),
                2,
            )

            cv2.imshow(WINDOW_NAME, frame)

            # Send camera heartbeat periodically.
            if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                send_heartbeat(True)
                last_heartbeat = current_time

            # Press Q to exit.
            if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                break

    except KeyboardInterrupt:
        print("\nProgram stopped by keyboard.")

    finally:
        # Turn the LED off when the program stops.
        set_led(False)

        if camera is not None:
            camera.release()

        cv2.destroyAllWindows()
        send_heartbeat(False)
        session.close()

        print("YOLO camera stopped.")


if __name__ == "__main__":
    main()
