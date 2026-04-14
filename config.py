import os
from datetime import timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hostel-attendance-secret-key-2024'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
                              'sqlite:///' + os.path.join(BASE_DIR, 'database', 'hostel.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # Dataset and model paths
    DATASET_DIR = os.path.join(BASE_DIR, 'dataset')
    MODEL_DIR = os.path.join(BASE_DIR, 'models')
    ENCODINGS_FILE = os.path.join(BASE_DIR, 'models', 'encodings.pkl')

    # Attendance window (24-hour format)
    ATTENDANCE_START_HOUR = 8    # 8:30 PM => for testing use 0
    ATTENDANCE_START_MIN = 30
    LATE_HOUR = 9                # 9:00 PM
    LATE_MIN = 0
    ATTENDANCE_END_HOUR = 9      # 9:30 PM
    ATTENDANCE_END_MIN = 30

    # For testing: keep window open 24 hours
    TESTING_MODE = True          # Set False for production

    # Face recognition
    RECOGNITION_TOLERANCE = 0.5
    FACE_IMAGES_REQUIRED = 20

    # Reports
    REPORTS_DIR = os.path.join(BASE_DIR, 'static', 'reports')

    # Ensure required directories exist
    @staticmethod
    def init_app(app):
        os.makedirs(Config.DATASET_DIR, exist_ok=True)
        os.makedirs(Config.MODEL_DIR, exist_ok=True)
        os.makedirs(Config.REPORTS_DIR, exist_ok=True)
        os.makedirs(os.path.join(BASE_DIR, 'database'), exist_ok=True)
