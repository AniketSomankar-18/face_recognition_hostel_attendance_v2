"""
Raspberry Pi Edge Client
Two modes:
  python raspberry_pi_client.py train     — download frames, train, upload encodings
  python raspberry_pi_client.py           — live attendance recognition loop
"""
import cv2
import requests
import pickle
import time
import os
import sys
import numpy as np

SERVER_URL          = os.environ.get('SERVER_URL', 'https://sggs-hostel.onrender.com')
ENCODINGS_FILE      = 'encodings.pkl'
COOLDOWN            = 10       # seconds between marking same student again
RECOGNITION_TOLERANCE = 0.5

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_SECRET_KEY', '')
DATASET_BUCKET   = 'face-dataset'
ENCODINGS_BUCKET = 'face-encodings'

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    print("[ERROR] face_recognition not installed. Run: pip install face_recognition dlib")
    FACE_RECOGNITION_AVAILABLE = False


# ─── Supabase Storage (Pi-side) ───────────────────────────────────────────────

def _supabase():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def download_dataset_from_supabase(local_dir: str):
    """Download all student frames from Supabase Storage to local disk."""
    print("[DATASET] Downloading training frames from Supabase Storage...")
    client = _supabase()

    try:
        students = client.storage.from_(DATASET_BUCKET).list()
    except Exception as e:
        print(f"[DATASET] Failed to list students: {e}")
        return 0

    total = 0
    for item in students:
        reg_num = item['name']
        student_dir = os.path.join(local_dir, reg_num)
        os.makedirs(student_dir, exist_ok=True)

        try:
            frames = client.storage.from_(DATASET_BUCKET).list(reg_num)
        except Exception as e:
            print(f"[DATASET] Failed to list frames for {reg_num}: {e}")
            continue

        for frame in frames:
            fname = frame['name']
            if not fname.lower().endswith(('.jpg', '.jpeg', '.png')):
                continue
            local_path = os.path.join(student_dir, fname)
            if os.path.exists(local_path):
                continue  # already downloaded
            try:
                data = client.storage.from_(DATASET_BUCKET).download(f"{reg_num}/{fname}")
                with open(local_path, 'wb') as f:
                    f.write(data)
                total += 1
            except Exception as e:
                print(f"[DATASET] Failed to download {reg_num}/{fname}: {e}")

    print(f"[DATASET] Downloaded {total} new frames.")
    return total


def upload_encodings_to_supabase(local_path: str):
    """Upload trained encodings.pkl to Supabase Storage."""
    print("[UPLOAD] Uploading encodings.pkl to Supabase Storage...")
    try:
        client = _supabase()
        with open(local_path, 'rb') as f:
            data = f.read()
        client.storage.from_(ENCODINGS_BUCKET).upload(
            path='encodings.pkl',
            file=data,
            file_options={"content-type": "application/octet-stream", "upsert": "true"}
        )
        print(f"[UPLOAD] encodings.pkl uploaded ({len(data)/1024:.1f} KB)")
        return True
    except Exception as e:
        print(f"[UPLOAD] Supabase upload failed: {e}")
        return False


def push_encodings_to_server(local_path: str):
    """Also push encodings.pkl to Render so it reloads into memory immediately."""
    print("[UPLOAD] Pushing encodings.pkl to Render server...")
    try:
        with open(local_path, 'rb') as f:
            resp = requests.post(
                f"{SERVER_URL}/api/pi/upload_encodings",
                files={'file': ('encodings.pkl', f, 'application/octet-stream')},
                timeout=30
            )
        result = resp.json()
        if result.get('success'):
            print("[UPLOAD] Render server updated successfully.")
        else:
            print(f"[UPLOAD] Render rejected: {result.get('message')}")
        return result.get('success', False)
    except Exception as e:
        print(f"[UPLOAD] Push to Render failed: {e}")
        return False


# ─── Training ─────────────────────────────────────────────────────────────────

def train_local(dataset_dir: str, encodings_file: str):
    """Download frames → train face encodings → upload to Supabase + Render."""
    if not FACE_RECOGNITION_AVAILABLE:
        print("[TRAIN] face_recognition not available. Cannot train.")
        return False

    # 1. Download dataset from Supabase Storage
    download_dataset_from_supabase(dataset_dir)

    student_folders = [d for d in os.listdir(dataset_dir)
                       if os.path.isdir(os.path.join(dataset_dir, d))]

    if not student_folders:
        print("[TRAIN] No student folders found in dataset. Enroll students first.")
        return False

    print(f"[TRAIN] Training on {len(student_folders)} students...")
    encodings = []
    names = []

    for reg_num in student_folders:
        student_path = os.path.join(dataset_dir, reg_num)
        image_files = [f for f in os.listdir(student_path)
                       if f.lower().endswith(('.jpg', '.jpeg', '.png'))][:20]

        samples = []
        for img_file in image_files:
            img_path = os.path.join(student_path, img_file)
            try:
                image = face_recognition.load_image_file(img_path)
                encs = face_recognition.face_encodings(image)
                if encs:
                    samples.append(encs[0])
            except Exception as e:
                continue

        if samples:
            avg_encoding = np.mean(samples, axis=0)
            encodings.append(avg_encoding)
            names.append(reg_num)
            print(f"  ✓ {reg_num} — {len(samples)} samples")
        else:
            print(f"  ✗ {reg_num} — no faces detected, skipping")

    if not encodings:
        print("[TRAIN] No valid faces found. Training failed.")
        return False

    # 2. Save encodings locally
    os.makedirs(os.path.dirname(encodings_file), exist_ok=True)
    with open(encodings_file, 'wb') as f:
        pickle.dump({'encodings': encodings, 'names': names}, f)
    print(f"[TRAIN] Trained {len(names)} identities. Saved to {encodings_file}")

    # 3. Upload to Supabase Storage
    upload_encodings_to_supabase(encodings_file)

    # 4. Push to Render server so it reloads immediately
    push_encodings_to_server(encodings_file)

    return True


# ─── Encodings Sync (for recognition mode) ───────────────────────────────────

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
                    dl = requests.get(data['url'], timeout=30)
                    with open(ENCODINGS_FILE, 'wb') as f:
                        f.write(dl.content)
                    print(f"[SYNC] Downloaded ({len(dl.content)/1024:.1f} KB)")
                    return True
                else:
                    print(f"[SYNC] {data.get('message')}")
            else:
                with open(ENCODINGS_FILE, 'wb') as f:
                    f.write(resp.content)
                print(f"[SYNC] Downloaded ({len(resp.content)/1024:.1f} KB)")
                return True
    except Exception as e:
        print(f"[SYNC] Failed: {e}")
    return False


def load_encodings():
    if not os.path.exists(ENCODINGS_FILE):
        return [], []
    try:
        with open(ENCODINGS_FILE, 'rb') as f:
            data = pickle.load(f)
        enc = data.get('encodings', [])
        names = data.get('names', [])
        print(f"[MODEL] Loaded {len(names)} identities.")
        return enc, names
    except Exception as e:
        print(f"[MODEL] Load failed: {e}")
        return [], []


# ─── Recognition ──────────────────────────────────────────────────────────────

def recognize_frame(frame, known_encodings, known_names):
    if not FACE_RECOGNITION_AVAILABLE or not known_encodings:
        return []
    rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    small = cv2.resize(rgb, (0, 0), fx=0.5, fy=0.5)
    locations = face_recognition.face_locations(small, model='hog')
    if not locations:
        return []
    encodings = face_recognition.face_encodings(small, locations)
    results = []
    for encoding in encodings:
        distances = np.linalg.norm(np.array(known_encodings) - encoding, axis=1)
        best_idx  = np.argmin(distances)
        best_dist = distances[best_idx]
        if best_dist < RECOGNITION_TOLERANCE:
            results.append((known_names[best_idx], round((1 - best_dist) * 100, 2)))
    return results


def mark_present(reg_num, confidence):
    try:
        resp = requests.post(f"{SERVER_URL}/api/pi/mark_present",
                             json={'reg_num': reg_num, 'confidence': confidence},
                             timeout=8)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[NETWORK] mark_present failed: {e}")
    return {'success': False}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("   HOSTEL ATTENDANCE — EDGE RECOGNITION NODE")
    print("=" * 60)

    if not FACE_RECOGNITION_AVAILABLE:
        return

    # Sync encodings on startup (force re-sync if --sync flag passed)
    force_sync = '--sync' in sys.argv
    if force_sync or not os.path.exists(ENCODINGS_FILE):
        sync_encodings()

    known_encodings, known_names = load_encodings()
    if not known_encodings:
        print("[ERROR] No encodings. Run: python raspberry_pi_client.py train")
        return

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[HARDWARE] Camera not found.")
        return

    print(f"\n[READY] Recognizing {len(known_names)} enrolled students.\n")
    recently_marked = {}
    frame_count = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(1)
                continue

            frame_count += 1
            if frame_count % 5 != 0:
                time.sleep(0.05)
                continue

            for reg_num, confidence in recognize_frame(frame, known_encodings, known_names):
                now = time.time()
                if now - recently_marked.get(reg_num, 0) < COOLDOWN:
                    continue
                result = mark_present(reg_num, confidence)
                recently_marked[reg_num] = now
                if result.get('success'):
                    print(f"[MARKED] {reg_num} — {result.get('direction','IN')} ({confidence}%)")
                else:
                    print(f"[SKIP]   {reg_num}: {result.get('message','failed')}")

    except KeyboardInterrupt:
        print("\n[STOP] Shutting down.")
    finally:
        cap.release()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'train':
        print("=" * 60)
        print("   TRAINING MODE")
        print("=" * 60)
        dataset_dir    = os.path.join(os.path.dirname(__file__), 'dataset')
        encodings_file = os.path.join(os.path.dirname(__file__), 'models', 'encodings.pkl')
        os.makedirs(dataset_dir, exist_ok=True)
        os.makedirs(os.path.dirname(encodings_file), exist_ok=True)
        success = train_local(dataset_dir, encodings_file)
        print("\n[DONE]" if success else "\n[FAILED]")
    else:
        main()
