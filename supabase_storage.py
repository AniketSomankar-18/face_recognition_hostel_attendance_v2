"""
Supabase Storage helper for persisting encodings.pkl and dataset frames
across Render deploys.
Buckets:
  face-encodings  — stores encodings.pkl
  face-dataset    — stores captured training frames per student
"""
import os
from supabase import create_client

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
# Try multiple common environment variable names for the Secret Key
SUPABASE_KEY = (
    os.environ.get('SUPABASE_SECRET_KEY') or 
    os.environ.get('SUPABASE_KEY') or 
    os.environ.get('SERVICE_ROLE_KEY') or 
    ''
)
ENCODINGS_BUCKET = 'face-encodings'
DATASET_BUCKET   = 'face-dataset'
ENCODINGS_OBJECT = 'encodings.pkl'


def _client():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print(f"[STORAGE] CRITICAL: Missing credentials! URL={bool(SUPABASE_URL)}, KEY={bool(SUPABASE_KEY)}")
    else:
        # Diagnostic: Log key format (obscured)
        key_preview = f"{SUPABASE_KEY[:6]}...{SUPABASE_KEY[-4:]}" if len(SUPABASE_KEY) > 10 else "INVALID"
        print(f"[STORAGE] Initializing client for {SUPABASE_URL} with key {key_preview}")
        
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ─── Encodings ────────────────────────────────────────────────────────────────

def upload_encodings(local_path: str) -> tuple[bool, str]:
    """Upload encodings.pkl to Supabase Storage. Returns (success, error_msg)"""
    try:
        client = _client()
        if not os.path.exists(local_path):
            return False, "Local encodings file not found"
        with open(local_path, 'rb') as f:
            data = f.read()
        client.storage.from_(ENCODINGS_BUCKET).upload(
            path=ENCODINGS_OBJECT,
            file=data,
            file_options={"content-type": "application/octet-stream", "upsert": "true"}
        )
        print(f"[STORAGE] encodings.pkl uploaded ({len(data)/1024:.1f} KB)")
        return True, "Success"
    except Exception as e:
        err = str(e)
        print(f"[STORAGE] Upload encodings failed: {err}")
        return False, err


def download_encodings(local_path: str) -> bool:
    """Download encodings.pkl from Supabase Storage."""
    try:
        client = _client()
        data = client.storage.from_(ENCODINGS_BUCKET).download(ENCODINGS_OBJECT)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, 'wb') as f:
            f.write(data)
        print(f"[STORAGE] encodings.pkl downloaded ({len(data)/1024:.1f} KB)")
        return True
    except Exception as e:
        print(f"[STORAGE] Download encodings failed (may not exist yet): {e}")
        return False


def delete_encodings() -> tuple[bool, str]:
    """Delete encodings.pkl from Supabase Storage so stale models can't be re-downloaded."""
    try:
        client = _client()
        client.storage.from_(ENCODINGS_BUCKET).remove([ENCODINGS_OBJECT])
        print(f"[STORAGE] encodings.pkl deleted from Supabase.")
        return True, "Deleted"
    except Exception as e:
        err = str(e)
        print(f"[STORAGE] Delete encodings failed: {err}")
        return False, err


    """Get a signed URL for the Pi to download encodings directly."""
    try:
        client = _client()
        res = client.storage.from_(ENCODINGS_BUCKET).create_signed_url(ENCODINGS_OBJECT, 3600)
        return res.get('signedURL', '')
    except Exception as e:
        print(f"[STORAGE] Failed to get signed URL: {e}")
        return ''


# ─── Dataset Frames ───────────────────────────────────────────────────────────

def upload_frame(reg_num: str, filename: str, image_bytes: bytes) -> tuple[bool, str]:
    """Upload a single captured frame to Supabase dataset bucket. Returns (success, error_msg)"""
    try:
        client = _client()
        object_path = f"{reg_num}/{filename}"
        client.storage.from_(DATASET_BUCKET).upload(
            path=object_path,
            file=image_bytes,
            file_options={"content-type": "image/jpeg", "upsert": "true"}
        )
        print(f"[STORAGE] Frame uploaded for {reg_num}: {object_path}")
        return True, "Success"
    except Exception as e:
        err = str(e)
        print(f"[STORAGE] upload_frame failed for {reg_num}: {err}")
        return False, err


def list_dataset_students() -> list:
    """List all student reg_num folders in the dataset bucket (paginated)."""
    try:
        client = _client()
        all_items = []
        offset = 0
        limit = 100
        
        while True:
            items = client.storage.from_(DATASET_BUCKET).list(path="", options={
                "limit": limit,
                "offset": offset
            })
            if not items:
                break
            all_items.extend(items)
            if len(items) < limit:
                break
            offset += limit
            
        return [item['name'] for item in all_items if item.get('id') is None]  # folders have no id
    except Exception as e:
        print(f"[STORAGE] list_dataset_students failed: {e}")
        return []


def list_student_frames(reg_num: str) -> list:
    """List all frame filenames for a student (paginated)."""
    try:
        client = _client()
        all_items = []
        offset = 0
        limit = 100
        
        while True:
            items = client.storage.from_(DATASET_BUCKET).list(reg_num, options={
                "limit": limit,
                "offset": offset
            })
            if not items:
                break
            all_items.extend(items)
            if len(items) < limit:
                break
            offset += limit
            
        return [item['name'] for item in all_items if item['name'].endswith(('.jpg', '.jpeg', '.png'))]
    except Exception as e:
        print(f"[STORAGE] list_student_frames failed ({reg_num}): {e}")
        return []


def download_frame(reg_num: str, filename: str) -> bytes:
    """Download a single frame from Supabase Storage."""
    try:
        client = _client()
        return client.storage.from_(DATASET_BUCKET).download(f"{reg_num}/{filename}")
    except Exception as e:
        print(f"[STORAGE] download_frame failed ({reg_num}/{filename}): {e}")
        return None


def delete_student_dataset(reg_num: str) -> tuple[bool, str]:
    """Delete all frames for a student from the dataset bucket."""
    try:
        client = _client()
        frames = list_student_frames(reg_num)
        if not frames:
            return True, "No frames found"
        paths = [f"{reg_num}/{fname}" for fname in frames]
        client.storage.from_(DATASET_BUCKET).remove(paths)
        print(f"[STORAGE] Deleted {len(paths)} frames for {reg_num}")
        return True, f"Deleted {len(paths)} frames"
    except Exception as e:
        err = str(e)
        print(f"[STORAGE] delete_student_dataset failed ({reg_num}): {err}")
        return False, err
