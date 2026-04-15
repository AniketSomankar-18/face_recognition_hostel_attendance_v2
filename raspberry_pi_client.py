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
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

SERVER_URL          = os.environ.get('SERVER_URL', 'https://sggs-hostel.onrender.com')
ENCODINGS_FILE      = 'encodings.pkl'
COOLDOWN            = 10       # seconds between marking same student again
RECOGNITION_TOLERANCE = 0.55

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
    print("[DATASET] Syncing training frames from Supabase Storage...")
    client = _supabase()

    # 1. List all student folders in the bucket (with pagination for 1000+ students)
    all_student_folders = []
    offset = 0
    limit = 100
    
    try:
        while True:
            # Bug fix: list() requires path as first positional argument (even if empty)
            batch = client.storage.from_(DATASET_BUCKET).list(path="", options={
                "limit": limit,
                "offset": offset,
                "sortBy": {"column": "name", "order": "asc"}
            })
            if not batch:
                break
            all_student_folders.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
            
        # Filter for folders only (folders in Supabase storage list usually don't have extensions)
        student_reg_nums = [
            item['name'] for item in all_student_folders 
            if '.' not in item['name'] and item['name'] != '.emptyKeep'
        ]
        
        if not student_reg_nums:
            # Fallback: retry listing
            simple_list = client.storage.from_(DATASET_BUCKET).list()
            student_reg_nums = [item['name'] for item in simple_list if '.' not in item['name']]
            if student_reg_nums:
                print("[DATASET] Paginated list returned 0, falling back to simple list.")

        print(f"[DATASET] Found {len(student_reg_nums)} student identities in cloud storage.")
        if student_reg_nums:
            print(f"[DATASET] Remote folders found: {', '.join(student_reg_nums[:10])}{' ...' if len(student_reg_nums) > 10 else ''}")
        else:
            # Critical Debug: What is Supabase actually returning?
            print(f"[DEBUG] Raw response from root list: {all_student_folders}")

    except Exception as e:
        print(f"[DATASET] Failed to list buckets/students: {e}")
        return 0

    total_downloaded = 0
    for reg_num in student_reg_nums:
        student_dir = os.path.join(local_dir, reg_num)
        os.makedirs(student_dir, exist_ok=True)

        try:
            # List frames for this specific student (increased limit to 500)
            frames = client.storage.from_(DATASET_BUCKET).list(reg_num, options={"limit": 500})
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
                total_downloaded += 1
            except Exception as e:
                print(f"[DATASET] Failed to download {reg_num}/{fname}: {e}")

    print(f"[DATASET] Downloaded {total_downloaded} new frames.")
    return total_downloaded


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

        student_samples_found = 0
        for img_file in image_files:
            img_path = os.path.join(student_path, img_file)
            try:
                image = face_recognition.load_image_file(img_path)
                encs = face_recognition.face_encodings(image)
                if encs:
                    encodings.append(encs[0])
                    names.append(reg_num)
                    student_samples_found += 1
            except Exception:
                continue

        if student_samples_found > 0:
            print(f"  ✓ {reg_num} — {student_samples_found} samples")
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

def recognize_frame(frame, known_encodings, known_names, frame_count=0):
    if not FACE_RECOGNITION_AVAILABLE or not known_encodings:
        return []
    
    rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    small = cv2.resize(rgb, (0, 0), fx=0.5, fy=0.5)
    locations = face_recognition.face_locations(small, model='hog')
    
    unique_names = sorted(list(set(known_names)))
    # Initialize distances for diagnostic radar with high values (infinity)
    best_distances_per_person = {name: 1.0 for name in unique_names}

    if not locations:
        if frame_count % 10 == 0:
            print(f"[RADAR] No faces detected...")
        return []

    encodings = face_recognition.face_encodings(small, locations)
    results = []
    
    K = 5  # Number of neighbors to consider for voting
    
    for encoding in encodings:
        distances = np.linalg.norm(np.array(known_encodings) - encoding, axis=1)
        
        # Track best distance per person for diagnostics
        for name in unique_names:
            person_distances = distances[np.array(known_names) == name]
            if len(person_distances) > 0:
                min_dist = np.min(person_distances)
                if min_dist < best_distances_per_person[name]:
                    best_distances_per_person[name] = min_dist

        # KNN Voting Logic
        # 1. Get indices of top K matches
        top_k_indices = np.argsort(distances)[:K]
        top_k_names = [known_names[idx] for idx in top_k_indices]
        top_k_distances = [distances[idx] for idx in top_k_indices]
        
        # 2. Count votes per identity
        votes = {}
        for name in top_k_names:
            votes[name] = votes.get(name, 0) + 1
        
        # 3. Find winner
        winner = max(votes, key=votes.get)
        vote_count = votes[winner]
        
        # 4. Filter matches by distance and majority
        # Average distance of the winner's samples in the top K
        winner_distances = [dist for name, dist in zip(top_k_names, top_k_distances) if name == winner]
        avg_dist = sum(winner_distances) / len(winner_distances)
        confidence = round((1 - avg_dist) * 100, 2)
        
        # Success criteria:
        # - Average distance below threshold
        # - At least 3 out of 5 votes (or majority if K < 5)
        required_votes = min(3, len(known_encodings))
        
        if avg_dist < RECOGNITION_TOLERANCE and vote_count >= required_votes:
            results.append((winner, confidence))
            print(f"[VOTE] {winner} wins ({vote_count}/{K} votes, Dist: {avg_dist:.2f})")
        else:
            if frame_count % 5 == 0:
                print(f"[DEBUG] Uncertain: {winner} ({vote_count}/{K} votes, Dist: {avg_dist:.2f})")

    # Diagnostic: Print the 'Radar' distance for every student identity
    if frame_count % 10 == 0:
        diag_str = " | ".join([f"{name}: {dist:.2f}" for name, dist in best_distances_per_person.items()])
        print(f"[RADAR] {diag_str}")

    return results


def report_task_complete():
    try:
        requests.post(f"{SERVER_URL}/api/pi/task_complete", timeout=5)
    except Exception:
        pass

def mark_present(reg_num, confidence):
    """Notify server to mark attendance for a student."""
    try:
        resp = requests.post(
            f"{SERVER_URL}/api/pi/mark_present",
            json={
                "reg_num": reg_num,
                "confidence": confidence,
                "source": "pi"
            },
            timeout=5
        )
        return resp.json()
    except Exception as e:
        return {"success": False, "message": str(e)}

# ─── Tasks ────────────────────────────────────────────────────────────────────

def run_training_task():
    print("\n" + "=" * 60)
    print("   REMOTE TRAINING TASK STARTED")
    print("=" * 60)
    dataset_dir    = os.path.join(os.path.dirname(__file__), 'dataset')
    encodings_file = os.path.join(os.path.dirname(__file__), 'models', 'encodings.pkl')
    os.makedirs(dataset_dir, exist_ok=True)
    os.makedirs(os.path.dirname(encodings_file), exist_ok=True)
    
    success = train_local(dataset_dir, encodings_file)
    if success:
        print("[TRAIN] Remote training successful.")
        report_task_complete()
    else:
        print("[TRAIN] Remote training failed.")

def run_recognition_task():
    print("\n" + "=" * 60)
    print("   LIVE ATTENDANCE TASK STARTED")
    print("=" * 60)
    
    if not os.path.exists(ENCODINGS_FILE):
        sync_encodings()

    known_encodings, known_names = load_encodings()
    if not known_encodings:
        print("[ERROR] No encodings found. Cancelling recognition.")
        report_task_complete()
        return

    print("[HARDWARE] Warming up camera...")
    time.sleep(3)  # Increased delay for OS to release hardware
    
    cap = None
    for attempt in range(5):
        for idx in [0, 1]:  # Try different camera indices
            print(f"[HARDWARE] Opening camera (Index: {idx}, Attempt: {attempt+1})...")
            cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    break
            cap.release()
            cap = None
        if cap: break
        time.sleep(2)

    if not cap or not cap.isOpened():
        print("[HARDWARE] CRITICAL: Camera not found or busy after 5 attempts.")
        report_task_complete()
        return

    print(f"\n[READY] Recognizing {len(known_names)} students.\n")
    recently_marked = {}
    frame_count = 0
    # Recognition buffer: require BUFFER_REQUIRED consecutive hits of the same identity
    # before marking. Prevents a single misidentified frame from triggering attendance.
    BUFFER_REQUIRED = 4   # ~2 seconds at 1 recognition per 0.5s (every 5th frame @ ~10fps)
    recognition_buffer = {}  # reg_num -> consecutive_hit_count

    try:
        while True:
            # Poll server state periodically to see if we should stop
            if frame_count % 30 == 0:
                try:
                    resp = requests.get(f"{SERVER_URL}/api/camera/state", timeout=3)
                    state = resp.json()
                    if not state.get('active'):
                        print("[STOP] Received stop command from server.")
                        break
                except Exception:
                    pass

            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            frame_count += 1
            if frame_count % 5 != 0:
                continue

            # Pass frame_count for diagnostic logging throttle
            detected_this_frame = set()
            for reg_num, confidence in recognize_frame(frame, known_encodings, known_names, frame_count):
                detected_this_frame.add(reg_num)
                recognition_buffer[reg_num] = recognition_buffer.get(reg_num, 0) + 1

                if recognition_buffer[reg_num] >= BUFFER_REQUIRED:
                    now = time.time()
                    if now - recently_marked.get(reg_num, 0) < COOLDOWN:
                        continue
                    result = mark_present(reg_num, confidence)
                    recently_marked[reg_num] = now
                    recognition_buffer[reg_num] = 0  # reset after marking
                    if result.get('success'):
                        print(f"[MARKED] {reg_num} — {result.get('direction','IN')} ({confidence}%) [buffer confirmed]")
                    else:
                        print(f"[SKIP]   {reg_num}: {result.get('message','failed')}")
                else:
                    print(f"[BUFFER] {reg_num}: {recognition_buffer[reg_num]}/{BUFFER_REQUIRED} hits")

            # Decay buffer for identities NOT seen this frame
            for reg_num in list(recognition_buffer.keys()):
                if reg_num not in detected_this_frame:
                    recognition_buffer[reg_num] = max(0, recognition_buffer[reg_num] - 1)
                    if recognition_buffer[reg_num] == 0:
                        del recognition_buffer[reg_num]
            
            # Tiny sleep to reduce CPU load
            time.sleep(0.01)

    except Exception as e:
        print(f"[ERROR] Recognition loop crashed: {e}")
    finally:
        cap.release()
        print("[STOP] Camera released.")
        report_task_complete()


# ─── Main ─────────────────────────────────────────────────────────────────────

def check_hardware():
    """Verify camera hardware is available on startup."""
    print("[HARDWARE] Checking camera...")
    cap = cv2.VideoCapture(0)
    if cap.isOpened():
        ret, _ = cap.read()
        cap.release()
        if ret:
            print("[HARDWARE] Camera OK")
            return True
    print("[HARDWARE] CRITICAL: Camera not found or busy!")
    return False


# ─── Supervisor (Main Loop) ───────────────────────────────────────────────────

def supervisor():
    print("=" * 60)
    print("   HOSTEL ATTENDANCE — PI COMMAND SUPERVISOR")
    print("=" * 60)
    print(f"[INFO] Server: {SERVER_URL}")
    
    if not check_hardware():
        print("[WARNING] Proceeding anyway, but recognition might fail.")
    
    print("\n[READY] Listening for commands from dashboard...")
    print("[HINT]  Go to 'Attendance' page and click 'Start Recognition'")

    last_log_time = 0
    while True:
        try:
            # Subtle heartbeat log every 1 minute
            if time.time() - last_log_time > 60:
                print(f"[STATUS] {datetime.now().strftime('%H:%M:%S')} - Waiting for command...")
                last_log_time = time.time()

            resp = requests.get(f"{SERVER_URL}/api/camera/state", timeout=5)
            if resp.status_code == 200:
                state = resp.json()
                active = state.get('active', False)
                command = state.get('command', 'idle')

                if command == 'train':
                    run_training_task()
                elif active or command == 'recognize':
                    run_recognition_task()
                
            time.sleep(3)
        except KeyboardInterrupt:
            print("\n[EXIT] Supervisor stopped by user.")
            break
        except Exception as e:
            print(f"[ERROR] Supervisor poll failed: {e}")
            time.sleep(5)

if __name__ == '__main__':
    from datetime import datetime
    
    # Traditional manual mode still supported via CLI args
    if len(sys.argv) > 1:
        if sys.argv[1] == 'train':
            run_training_task()
        elif sys.argv[1] == 'recognize':
            run_recognition_task()
        else:
            print("Usage: python raspberry_pi_client.py [train|recognize]")
    else:
        # Default: Start as Supervisor
        supervisor()
