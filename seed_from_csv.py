import csv
import sys
import os
import re
from app import app, db
from models import Student

# Mapping from degree code in registration number to full department name
DEPT_MAP = {
    'BCS': 'Computer Science',
    'BIT': 'IT',
    'BME': 'Mechanical',
    'BEC': 'Electronics',
    'BCE': 'Civil',
    'BTT': 'Textile',
    'BCH': 'Chemical',
    'BIN': 'Instrumentation',
    'BPR': 'Production',
    'BEL': 'Electrical',
    'MAI': 'AI-DS'
}

def infer_dept(reg):
    # Regex to find the degree part: 4 digits + 3 uppercase letters
    match = re.search(r'\d{4}([A-Z]{3})', reg)
    if match:
        code = match.group(1)
        return DEPT_MAP.get(code, "Engineering")
    return "Engineering"

def parse_n_room(room_csv):
    # NAG01 -> N AG01
    # NAF01 -> N AF01
    # NBG01 -> N BG01
    if not room_csv or len(room_csv) < 5:
        return "N A G01" # fallback
    
    building = room_csv[0] # N
    block = room_csv[1]    # A, B, C, D
    floor = room_csv[2]    # G, F
    room = room_csv[3:]    # 01, 02...
    return f"{building} {block}{floor}{room}"

def parse_sh_room(room_csv):
    # SHGA01 -> SH AG01
    # SHFA01 -> SH AF01
    # SHSA01 -> SH AS01 (Second floor) -> Wait, I want floor before room number?
    # Internal format is building code + space + block + floor + room
    # f"{building_code} {block}{floor}{room_num}"
    
    if not room_csv or len(room_csv) < 6:
        return "SH AG01"
    
    # SH (2 chars) + Floor (1 char) + Block (1 char) + Room (2 chars)
    # SH G A 01 -> SH AG01
    # SH F A 01 -> SH AF01
    floor = room_csv[2] # G, F, S, T
    block = room_csv[3] # A, B, C, D
    room = room_csv[4:] # 01, 02...
    return f"SH {block}{floor}{room}"

def seed_database():
    with app.app_context():
        print("[INFO] Clearing existing students...")
        Student.query.delete()
        db.session.commit()

        # Seed Nandgiri
        n_count = 0
        n_file = 'boys_n_hostel.csv'
        if os.path.exists(n_file):
            print(f"[INFO] Seeding {n_file}...")
            with open(n_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('Name of the Student')
                    reg = row.get('Registration No.')
                    room_id = parse_n_room(row.get('Room No.'))
                    mobile = row.get('Mobile No.', '9876543210')
                    
                    if not name or not reg: continue
                    
                    s = Student(
                        registration_number=reg.strip(),
                        name=name.strip(),
                        room_number=room_id,
                        department=infer_dept(reg),
                        phone=mobile.strip() if mobile else '9876543210',
                        parent_phone='9876543210',
                        email=f"{reg.lower()}@sggs.ac.in"
                    )
                    db.session.add(s)
                    n_count += 1
            db.session.commit()
            print(f"[SUCCESS] {n_count} Nandgiri students seeded.")

        # Seed Sahyandri
        sh_count = 0
        sh_file = 'boys_sh_hostel.csv'
        if os.path.exists(sh_file):
            print(f"[INFO] Seeding {sh_file}...")
            with open(sh_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('Name of the Student')
                    reg = row.get('Registration No.')
                    room_id = parse_sh_room(row.get('Room No.'))
                    mobile = row.get('Mobile No.', '9876543210')
                    
                    if not name or not reg: continue
                    
                    s = Student(
                        registration_number=reg.strip(),
                        name=name.strip(),
                        room_number=room_id,
                        department=infer_dept(reg),
                        phone=mobile.strip() if mobile else '9876543210',
                        parent_phone='9876543210',
                        email=f"{reg.lower()}@sggs.ac.in"
                    )
                    db.session.add(s)
                    sh_count += 1
            db.session.commit()
            print(f"[SUCCESS] {sh_count} Sahyandri students seeded.")

if __name__ == '__main__':
    seed_database()
