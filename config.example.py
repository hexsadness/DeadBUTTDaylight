"""Example values users may copy into dbd_haptics.py while calibrating."""

MONITOR_NUMBER = 2
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
INTIFACE_ADDRESS = "ws://127.0.0.1:12345"

HEARTBEAT_STRENGTH = 0.20
INJURY_STRENGTH = 0.80
INJURY_PULSE_DURATION = 0.40

# These defaults were calibrated at 1920x1080 and may need adjustment.
REGIONS_1920X1080 = {
    "health": {"x": 50, "y": 380, "width": 300, "height": 420},
    "heartbeat": {"x": 605, "y": 400, "width": 695, "height": 600},
    "action_bar": {"x": 800, "y": 815, "width": 340, "height": 180},
}
