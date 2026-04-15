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
SUPABASE_KEY = os.environ.get('SUPABASE_SECRET_KEY', '')
ENCODINGS_BUCKET = 'face-encodings'
DATASET_BUCKET   = 'face-dataset'
ENCODINGS_OBJECT = 'encodings.pkl'


def _client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ─── Encodings ────────────────────────────────────────────────────────────────

def upload_encodings(local_path: str) -> bool:
    """Upload encodings.pkl to Supabase Storage."""
    try:
        client = _client()
        with open(local_path, 'rb') as f:
            data = f.read()
        client.storage.from_(ENCODINGS_BUCKET).upload(
            path=ENCODINGS_OBJECT,
            file=data,
            file_options={"content-type": "application/octet-stream", "upsert": "true"}
        )
        print(f"[STORAGE] encodings.pkl uploaded ({len(data)/1024:.1f} KB)")
        return True
    except Exception as e:
        print(f"[STORAGE] Upload encodings failed: {e}")
        return False


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


def get_encodings_url() -> str:
    """Get a signed URL for the Pi to download encodings directly."""
    try:
        client = _client()
        res = client.storage.from_(ENCODINGS_BUCKET).create_signed_url(ENCODINGS_OBJECT, 3600)
        return res.get('signedURL', '')
    except Exception as e:
        print(f"[STORAGE] Failed to get signed URL: {e}")
        return ''


# ─── Dataset Frames ───────────────────────────────────────────────────────────

def upload_frame(reg_num: str, filename: str, image_bytes: bytes) -> bool:
    """Upload a single captured frame to Supabase Storage dataset bucket."""
    try:
        client = _client()
        object_path = f"{reg_num}/{filename}"
        client.storage.from_(DATASET_BUCKET).upload(
            path=object_path,
            file=image_bytes,
            file_options={"content-type": "image/jpeg", "upsert": "true"}
        )
        return True
    except Exception as e:
        print(f"[STORAGE] Frame upload failed ({reg_num}/{filename}): {e}")
        return False


def list_dataset_students() -> list:
    """List all student reg_num folders in the dataset bucket."""
    try:
        client = _client()
        items = client.storage.from_(DATASET_BUCKET).list()
        return [item['name'] for item in items if item.get('id') is None]  # folders have no id
    except Exception as e:
        print(f"[STORAGE] list_dataset_students failed: {e}")
        return []


def list_student_frames(reg_num: str) -> list:
    """List all frame filenames for a student."""
    try:
        client = _client()
        items = client.storage.from_(DATASET_BUCKET).list(reg_num)
        return [item['name'] for item in items if item['name'].endswith(('.jpg', '.jpeg', '.png'))]
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
