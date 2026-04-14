from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='warden') # rector | warden
    hostel_code = db.Column(db.String(10), nullable=True) # N | SH | D | K | G | None for Rector
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_rector(self):
        """Strict role-based check for Rector permissions."""
        return self.role == 'rector'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    registration_number = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    room_number = db.Column(db.String(20), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(15), nullable=False)
    parent_phone = db.Column(db.String(15), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    face_encoded = db.Column(db.Boolean, default=False)
    face_samples_count = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    absence_count = db.Column(db.Integer, default=0)   # cumulative absence count
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    attendance_records = db.relationship(
        'Attendance', backref='student', lazy=True,
        foreign_keys='Attendance.registration_number',
        primaryjoin='Student.registration_number == Attendance.registration_number'
    )
    leave_records = db.relationship(
        'Leave', backref='student', lazy=True,
        foreign_keys='Leave.registration_number',
        primaryjoin='Student.registration_number == Leave.registration_number'
    )
    penalties = db.relationship(
        'Penalty', backref='student', lazy=True,
        foreign_keys='Penalty.registration_number',
        primaryjoin='Student.registration_number == Penalty.registration_number'
    )


class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    registration_number = db.Column(
        db.String(50), db.ForeignKey('students.registration_number'), nullable=False
    )
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    status = db.Column(db.String(20), nullable=False)   # Present | Late | Absent | Leave
    direction = db.Column(db.String(10), nullable=False, default='IN') # IN | OUT
    confidence = db.Column(db.Float, default=0.0)
    marked_at = db.Column(db.DateTime, default=datetime.utcnow)
    marked_by = db.Column(db.String(50), default='system')

    __table_args__ = (
        db.UniqueConstraint('registration_number', 'date', 'direction', name='unique_attendance'),
    )


class Leave(db.Model):
    __tablename__ = 'leaves'
    id = db.Column(db.Integer, primary_key=True)
    registration_number = db.Column(
        db.String(50), db.ForeignKey('students.registration_number'), nullable=False
    )
    from_date = db.Column(db.Date, nullable=False)
    to_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    leave_type = db.Column(db.String(50), nullable=False)
    approved_by = db.Column(db.String(80))
    approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Penalty(db.Model):
    __tablename__ = 'penalties'
    id = db.Column(db.Integer, primary_key=True)
    registration_number = db.Column(
        db.String(50), db.ForeignKey('students.registration_number'), nullable=False
    )
    date = db.Column(db.Date, nullable=False)
    penalty_amount = db.Column(db.Integer, nullable=False)   # ₹100, ₹500, ₹1000
    absence_count = db.Column(db.Integer, nullable=False)    # which absence triggered this
    reason = db.Column(db.String(200), default='Absent – did not mark attendance')
    email_sent = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
