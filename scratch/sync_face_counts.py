import os
from app import app, db
from models import Student
from config import Config

def sync():
    with app.app_context():
        students = Student.query.all()
        print(f"Syncing face counts for {len(students)} students...")
        
        for student in students:
            path = os.path.join(Config.DATASET_DIR, student.registration_number)
            if os.path.exists(path):
                imgs = [f for f in os.listdir(path) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
                student.face_samples_count = len(imgs)
                if len(imgs) >= Config.FACE_IMAGES_REQUIRED:
                    student.face_encoded = True
            else:
                student.face_samples_count = 0
                
        db.session.commit()
        print("Sync complete.")

if __name__ == "__main__":
    sync()
