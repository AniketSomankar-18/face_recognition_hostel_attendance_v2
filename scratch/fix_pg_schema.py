import os
from sqlalchemy import text, create_engine
from dotenv import load_dotenv

load_dotenv()

db_url = os.environ.get('DATABASE_URL')
if not db_url:
    print("DATABASE_URL not found in .env")
    exit(1)

# Fix for some SQLAlchemy versions needing postgresql:// instead of postgres://
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(db_url)

def fix_schema():
    print(f"Connecting to database...")
    with engine.connect() as conn:
        try:
            print("Adding face_samples_count column...")
            conn.execute(text("ALTER TABLE students ADD COLUMN face_samples_count INTEGER DEFAULT 0"))
            conn.commit()
            print("✓ Success: Added face_samples_count to students table.")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("! Column face_samples_count already exists.")
            else:
                print(f"✗ Failed: {str(e)}")

if __name__ == "__main__":
    fix_schema()
