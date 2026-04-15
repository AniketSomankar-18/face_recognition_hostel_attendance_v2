"""
Raspberry Pi Edge Client — Local Face Recognition
Architecture: Pi does all face comparison locally, only sends reg_num to server.
This avoids sending raw images over the network and removes load from Render.
"""
import cv2
import requests
import pickle
import time
import os
import numpy as np

# ─── Config ───────────────────────────────────────────────────────────────────
SERVER_URL = os.environ.get('SERVER_URL', 'https://sggs-hostel.onrender.com')
ENCODINGS_FILE = 'encodings.pkl'
COOLDOWN = 10        # seconds between marking same student again
POLL_INTERVAL = 3.0  # seconds between camera state polls
RECOGNITION_TOLERANCE = 0.5

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    print("[ERROR] face_recognition not installed. Run: pip install face_recognition")
    FACE_RECOGNITION_AVAILABLE = False


# ─── Encodings Sync ───────────────────────────────────────────────────────────
def sync_encodings():
    """Download latest encodings.pkl from server on startup."""
    print("[SYNC] Fetching latest encodings from server...")
    try:
        resp = requests.get(f"{SERVER_URL}/api/pi/sync_encodings", timeout=15)
        if resp.status_code == 200:
            content_type = resp.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                data = resp.json()
                if data.get('success') and data.get('url'):
                    # Download from signed Supabase URL
                    dl = requests.get(data['url'], timeout=30)
                    with open(ENCODINGS_FILE, 'wb') as f:
                        f.write(dl.content)
                    print(f"[SYNC] encodings.pkl downloaded ({len(dl.content)/1024:.1f} KB)")
                    return True
                else:
                    print(f"[SYNC] Server says: {data.get('message')}")
                    return False
            else:
                # Server sent the file directly
                with open(ENCODINGS_FILE, 'wb') as f:
                    f.write(resp.content)
                print(f"[SYNC] encodings.pkl downloaded ({len(resp.content)/1024:.1f} KB)")
                return True
    except Exception as e:
        print(f"[SYNC] Failed: {e}")
    return False


def load_encodings():
    """Load encodings.pkl into memory. Returns (encodings_list, names_list)."""
    if not os.path.exists(ENCODINGS_FILE):
        print("[MODEL] No encodings file found.")
        return [], []
    try:
        with open(ENCODINGS_FILE, 'rb') as f:
            data = pickle.load(f)
        encodings = data.get('encodings', [])
        names = data.get('names', [])
        print(f"[MODEL] Loaded {len(names)} identities into memory.")
        return encodings, names
    except Exception as e:
        print(f"[MODEL] Failed to load encodings: {e}")
        return [], []


# ─── Recognition ──────────────────────────────────────────────────────────────
def recognize_frame(frame, known_encodings, known_names):
    """
    Run face recognition on a single frame.
    Returns list of (reg_num, confidence) tuples for matched faces.
    """
    if not FACE_RECOGNITION_AVAILABLE or not known_encodings:
        return []

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    small = cv2.resize(rgb, (0, 0), fx=0.5, fy=0.5)

    locations = face_recognition.face_locations(small, model='hog')
    if not locations:
        return []

    encodings = face_recognition.face_encodings(small, locations)
    results = []

    for encoding in encodings:
        distances = np.linalg.norm(np.array(known_encodings) - encoding, axis=1)
        best_idx = np.argmin(distances)
        best_dist = distances[best_idx]

        if best_dist < RECOGNITION_TOLERANCE:
            confidence = round((1 - best_dist) * 100, 2)
            results.append((known_names[best_idx], confidence))

    return results


# ─── Mark Present ─────────────────────────────────────────────────────────────
def mark_present(reg_num, confidence):
    """Send reg_num to server to mark attendance. No image sent."""
    try:
        resp = requests.post(
            f"{SERVER_URL}/api/pi/mark_present",
            json={'reg_num': reg_num, 'confidence': confidence},
            timeout=8
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[NETWORK] mark_present failed: {e}")
    return {'success': False}


# ─── Main Loop ────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("   HOSTEL ATTENDANCE — EDGE RECOGNITION NODE")
    print("=" * 60)

    if not FACE_RECOGNITION_AVAILABLE:
        return

    # 1. Sync encodings on startup
    if not os.path.exists(ENCODINGS_FILE):
        sync_encodings()
    else:
        print("[MODEL] Using cached encodings.pkl (delete to force re-sync)")

    known_encodings, known_names = load_encodings()
    if not known_encodings:
        print("[ERROR] No encodings loaded. Enroll students and train the model first.")
        return

    # 2. Open camera
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[HARDWARE] Camera not found.")
        return

    print(f"\n[READY] Recognizing faces for {len(known_names)} enrolled students.\n")

    recently_marked = {}  # reg_num -> last marked timestamp
    frame_count = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[CAMERA] Frame read failed. Retrying...")
                time.sleep(1)
                continue

            frame_count += 1
            # Process every 5th frame to reduce CPU load
            if frame_count % 5 != 0:
                time.sleep(0.05)
                continue

            matches = recognize_frame(frame, known_encodings, known_names)

            for reg_num, confidence in matches:
                now = time.time()
                last = recently_marked.get(reg_num, 0)

                if now - last < COOLDOWN:
                    continue  # Still in cooldown

                result = mark_present(reg_num, confidence)
                recently_marked[reg_num] = now

                if result.get('success'):
                    direction = result.get('direction', 'IN')
                    print(f"[MARKED] {reg_num} — {direction} ({confidence}%)")
                else:
                    print(f"[SKIP] {reg_num}: {result.get('message', 'failed')}")

    except KeyboardInterrupt:
        print("\n[STOP] Shutting down.")
    finally:
        cap.release()


if __name__ == '__main__':
    main()
