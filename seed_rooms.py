from app import app
from models import db, Student, User
from datetime import datetime

def seed():
    with app.app_context():
        # Clear existing students if you want a fresh start, or just add new ones
        # Student.query.delete()
        
        # Nandagiri (N)
        blocks = ['A', 'B', 'C', 'D']
        floors = ['G', 'F']
        
        sample_students = [
            # N AG01
            {'name': 'Arjun Mehta', 'reg': '2023CS001', 'room': 'N AG01', 'dept': 'CS'},
            {'name': 'Vikram Singh', 'reg': '2023CS002', 'room': 'N AG01', 'dept': 'CS'},
            {'name': 'Rohan Das', 'reg': '2023CS003', 'room': 'N AG02', 'dept': 'CS'},
            
            # N AF01
            {'name': 'Suresh Raina', 'reg': '2023CS004', 'room': 'N AF01', 'dept': 'IT'},
            {'name': 'Ishant Sharma', 'reg': '2023CS005', 'room': 'N AF01', 'dept': 'IT'},
            
            # S AG01 (Sahyandri)
            {'name': 'Aditya Roy', 'reg': '2023ME001', 'room': 'S AG01', 'dept': 'Mechanical'},
            {'name': 'Manish Paul', 'reg': '2023ME002', 'room': 'S AG01', 'dept': 'Mechanical'},
        ]
        
        for s in sample_students:
            existing = Student.query.filter_by(registration_number=s['reg']).first()
            if not existing:
                student = Student(
                    registration_number=s['reg'],
                    name=s['name'],
                    room_number=s['room'],
                    department=s['dept'],
                    phone='9876543210',
                    parent_phone='9876543200',
                    email=f"{s['name'].lower().replace(' ', '.') }@example.com"
                )
                db.session.add(student)
        
        db.session.commit()
        print("Database seeded with new room format!")

if __name__ == '__main__':
    seed()
