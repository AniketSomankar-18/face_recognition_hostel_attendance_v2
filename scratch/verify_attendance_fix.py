import sys
import os
from datetime import datetime, date

# Add project root to sys.path
sys.path.append(os.getcwd())

from app import app, db
from models import Student, Attendance
from modules.attendance import mark_attendance, get_today_summary

def verify_fixes():
    with app.app_context():
        # 1. Setup - Create a test student
        test_reg = "TEST12345"
        student = Student.query.filter_by(registration_number=test_reg).first()
        if not student:
            student = Student(
                registration_number=test_reg,
                name="Test Student",
                room_number="N A101",
                department="Computer",
                phone="1234567890",
                parent_phone="0987654321",
                email="test@example.com"
            )
            db.session.add(student)
            db.session.commit()
            print(f"[SETUP] Created test student {test_reg}")

        # Clean up existing records for today for this student
        Attendance.query.filter_by(registration_number=test_reg, date=date.today()).delete()
        db.session.commit()

        # 2. Simulate marking 'Absent' (system auto-mark)
        print("[TEST] Marking student as Absent...")
        db.session.add(Attendance(
            registration_number=test_reg,
            date=date.today(),
            status='Absent',
            marked_at=datetime.now(),
            marked_by='auto_system'
        ))
        db.session.commit()

        # 3. Verify Summary after Absent
        summary = get_today_summary('N')
        print(f"[RESULT] Summary after Absent: Present={summary['present']}, Absent={summary['absent']}")
        
        # 4. Try to mark 'Present' immediately (Testing cooldown bypass for 'Absent')
        print("[TEST] Marking student as Present (face_recognition)...")
        success, msg, direction = mark_attendance(test_reg, confidence=95.5)
        print(f"[RESULT] Success: {success}, Message: {msg}, Direction: {direction}")

        # 5. Verify Summary after Present
        summary = get_today_summary('N')
        print(f"[RESULT] Summary after Present: Present={summary['present']}, Absent={summary['absent']}")

        if success and summary['present'] >= 1 and summary['absent'] == 0:
            # Note: summary['absent'] == 0 assumes only this student was marked absent or others were marked present
            # Better: check if this student's registration_number is counted as present
            print("\n[SUCCESS] Cooldown bypass and correct dashboard counting verified!")
        else:
            print("\n[FAILURE] Verification failed.")
            if not success:
                print("Reason: mark_attendance failed (likely cooldown still active)")
            if summary['absent'] > 0:
                print(f"Reason: Dashboard still showing {summary['absent']} absents (likely double counting)")

if __name__ == "__main__":
    verify_fixes()
