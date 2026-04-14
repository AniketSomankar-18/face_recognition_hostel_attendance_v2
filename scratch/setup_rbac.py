import os
from sqlalchemy import text, create_engine
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

db_url = os.environ.get('DATABASE_URL')
if not db_url:
    print("DATABASE_URL not found in .env")
    exit(1)

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(db_url)

def setup_rbac():
    print(f"Connecting to database...")
    with engine.connect() as conn:
        try:
            # 1. Add hostel_code column if it doesn't exist
            print("Checking schema for hostel_code...")
            try:
                conn.execute(text("ALTER TABLE users ADD COLUMN hostel_code VARCHAR(10) DEFAULT 'ALL'"))
                conn.commit()
                print("✓ Added hostel_code column.")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print("! Column hostel_code already exists.")
                else:
                    raise e

            # 2. Update existing 'warden' user to be Rector (Sawarkar)
            print("Updating default user to Rector...")
            pass_hash = generate_password_hash("rector123")
            conn.execute(text("""
                UPDATE users 
                SET role = 'rector', hostel_code = 'ALL', username = 'rector', password_hash = :pw 
                WHERE username = 'warden' OR role = 'rector'
            """), {"pw": pass_hash})
            
            # Ensure at least one rector exists if 'warden' didn't exist
            res = conn.execute(text("SELECT id FROM users WHERE role = 'rector'"))
            if not res.fetchone():
                conn.execute(text("""
                    INSERT INTO users (username, password_hash, role, hostel_code, created_at)
                    VALUES ('rector', :pw, 'rector', 'ALL', NOW())
                """), {"pw": pass_hash})

            # 3. Create Wardens for each hostel
            wardens = [
                ('warden_sh', 'sh123', 'warden', 'SH', 'Dr. Atul Shinde'),
                ('warden_n', 'n123', 'warden', 'N', 'Dr. Alok Mishra'),
                ('warden_d', 'd123', 'warden', 'D', 'Dr. Purnima Talele'),
                ('warden_k', 'k123', 'warden', 'K', 'Dr. Pranita Balve'),
                ('warden_g', 'g123', 'warden', 'G', 'Dr. Purnima Talele')
            ]

            for user, pw, role, code, name in wardens:
                print(f"Checking warden: {user} ({code})...")
                res = conn.execute(text("SELECT id FROM users WHERE username = :u"), {"u": user})
                if not res.fetchone():
                    ph = generate_password_hash(pw)
                    conn.execute(text("""
                        INSERT INTO users (username, password_hash, role, hostel_code, created_at)
                        VALUES (:u, :ph, :r, :c, NOW())
                    """), {"u": user, "ph": ph, "r": role, "c": code})
                    print(f"✓ Created user: {user}")
                else:
                    print(f"! User {user} already exists.")

            conn.commit()
            print("\n✓ SUCCESS: RBAC initialization complete.")
            print("Rector: rector / rector123")
            print("Wardens (example): warden_n / n123")

        except Exception as e:
            print(f"✗ FAILED: {str(e)}")
            conn.rollback()

if __name__ == "__main__":
    setup_rbac()
