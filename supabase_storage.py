"""
Supabase Storage helper for persisting encodings.pkl across Render deploys.
Bucket: face-encodings (create this in your Supabase dashboard)
"""
import os
import io
from supabase import create_client

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_SECRET_KEY', '')  # Use secret key for storage ops
BUCKET = 'face-encodings'
ENCODINGS_OBJECT = 'encodings.pkl'


def _client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def upload_encodings(local_path: str) -> bool:
    """Upload encodings.pkl to Supabase Storage. Returns True on success."""
    try:
        client = _client()
        with open(local_path, 'rb') as f:
            data = f.read()
        # upsert=True overwrites existing file
        client.storage.from_(BUCKET).upload(
            path=ENCODINGS_OBJECT,
            file=data,
            file_options={"content-type": "application/octet-stream", "upsert": "true"}
        )
        print(f"[STORAGE] encodings.pkl uploaded to Supabase Storage ({len(data)/1024:.1f} KB)")
        return True
    except Exception as e:
        print(f"[STORAGE] Upload failed: {e}")
        return False


def download_encodings(local_path: str) -> bool:
    """Download encodings.pkl from Supabase Storage. Returns True on success."""
    try:
        client = _client()
        data = client.storage.from_(BUCKET).download(ENCODINGS_OBJECT)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, 'wb') as f:
            f.write(data)
        print(f"[STORAGE] encodings.pkl downloaded from Supabase Storage ({len(data)/1024:.1f} KB)")
        return True
    except Exception as e:
        print(f"[STORAGE] Download failed (may not exist yet): {e}")
        return False


def get_encodings_url() -> str:
    """Get a public/signed URL for the Pi to download encodings directly."""
    try:
        client = _client()
        # Signed URL valid for 1 hour
        res = client.storage.from_(BUCKET).create_signed_url(ENCODINGS_OBJECT, 3600)
        return res.get('signedURL', '')
    except Exception as e:
        print(f"[STORAGE] Failed to get signed URL: {e}")
        return ''
