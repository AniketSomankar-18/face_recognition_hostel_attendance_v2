from datetime import datetime, date, time
from models import db, Attendance, Student, Leave
from config import Config


def get_attendance_status_for_time(check_time=None):
    """
    Returns what status to assign based on current time.
    Status: 'open_present', 'open_late', 'closed_early', 'closed_end'
    """
    if Config.TESTING_MODE:
        # In testing mode, always open - mark present before 9:00 PM equivalent, late after
        now = check_time or datetime.now()
        hour = now.hour
        minute = now.minute

        # Use evening window logic
        start = time(Config.ATTENDANCE_START_HOUR, Config.ATTENDANCE_START_MIN)  # 8:30 PM -> for test: 20:30
        late = time(Config.LATE_HOUR, Config.LATE_MIN)
        end = time(Config.ATTENDANCE_END_HOUR, Config.ATTENDANCE_END_MIN)

        current = time(hour, minute)

        # Determine window
        if current < start:
            return 'open_present'   # Testing: allow present anytime before 9:00 PM equivalent
        elif start <= current < late:
            return 'open_present'
        elif late <= current <= end:
            return 'open_late'
        else:
            return 'open_present'   # Testing: keep open
    else:
        now = check_time or datetime.now()
        current = time(now.hour, now.minute)
        start = time(20, 30)   # 8:30 PM
        late = time(21, 0)     # 9:00 PM
        end = time(21, 30)     # 9:30 PM

        if current < start:
            return 'closed_early'
        elif start <= current < late:
            return 'open_present'
        elif late <= current <= end:
            return 'open_late'
        else:
            return 'closed_end'


def mark_attendance(registration_number, marked_by='face_recognition'):
    """
    Mark attendance for a student.
    Returns: (success: bool, message: str, status: str)
    """
    today = date.today()

    # Check if student exists
    student = Student.query.filter_by(
        registration_number=registration_number, is_active=True
    ).first()
    if not student:
        return False, "Student not found.", None

    # Check if already marked
    existing = Attendance.query.filter_by(
        registration_number=registration_number,
        date=today
    ).first()
    if existing:
        return False, f"Attendance already marked: {existing.status}", existing.status

    # Check if on leave
    leave = Leave.query.filter_by(
        registration_number=registration_number,
        approved=True
    ).filter(
        Leave.from_date <= today,
        Leave.to_date >= today
    ).first()

    if leave:
        record = Attendance(
            registration_number=registration_number,
            date=today,
            status='Leave',
            marked_at=datetime.now(),
            marked_by=marked_by
        )
        db.session.add(record)
        db.session.commit()
        return True, f"{student.name} is on approved leave.", 'Leave'

    # Determine status based on time
    window = get_attendance_status_for_time()

    if window == 'closed_early':
        return False, "Attendance window not yet open (opens at 8:30 PM).", None
    elif window == 'closed_end':
        return False, "Attendance window closed (closed at 9:30 PM).", None
    elif window == 'open_present':
        status = 'Present'
    elif window == 'open_late':
        status = 'Late'
    else:
        status = 'Present'

    record = Attendance(
        registration_number=registration_number,
        date=today,
        status=status,
        marked_at=datetime.now(),
        marked_by=marked_by
    )
    db.session.add(record)
    db.session.commit()

    return True, f"Attendance marked: {student.name} - {status}", status


def mark_absents_for_today():
    """
    Mark all students who haven't marked attendance today as Absent.
    Should be called after 9:30 PM.
    """
    today = date.today()
    active_students = Student.query.filter_by(is_active=True).all()
    marked_count = 0

    for student in active_students:
        existing = Attendance.query.filter_by(
            registration_number=student.registration_number,
            date=today
        ).first()

        if existing:
            continue  # Already marked

        # Check if on leave
        leave = Leave.query.filter_by(
            registration_number=student.registration_number,
            approved=True
        ).filter(
            Leave.from_date <= today,
            Leave.to_date >= today
        ).first()

        if leave:
            status = 'Leave'
        else:
            status = 'Absent'

        record = Attendance(
            registration_number=student.registration_number,
            date=today,
            status=status,
            marked_at=datetime.now(),
            marked_by='auto_system'
        )
        db.session.add(record)
        marked_count += 1

    db.session.commit()
    return marked_count


def get_today_summary():
    """Returns attendance summary for today."""
    today = date.today()
    total = Student.query.filter_by(is_active=True).count()

    present = Attendance.query.filter_by(date=today, status='Present').count()
    late = Attendance.query.filter_by(date=today, status='Late').count()
    absent = Attendance.query.filter_by(date=today, status='Absent').count()
    on_leave = Attendance.query.filter_by(date=today, status='Leave').count()

    marked = present + late + absent + on_leave
    unmarked = total - marked
    percentage = round((present + late) / total * 100, 1) if total > 0 else 0

    return {
        'total': total,
        'present': present,
        'late': late,
        'absent': absent,
        'leave': on_leave,
        'unmarked': unmarked,
        'percentage': percentage,
        'date': today.strftime('%d %B %Y'),
        'day': today.strftime('%A')
    }


def get_student_attendance_history(registration_number, month=None, year=None):
    """Returns attendance records for a student, optionally filtered by month/year."""
    query = Attendance.query.filter_by(registration_number=registration_number)

    if month and year:
        from sqlalchemy import extract
        query = query.filter(
            extract('month', Attendance.date) == month,
            extract('year', Attendance.date) == year
        )

    records = query.order_by(Attendance.date.desc()).all()
    return records


def get_calendar_data(registration_number, month, year):
    """Returns calendar data for a student's attendance."""
    import calendar
    from sqlalchemy import extract

    records = Attendance.query.filter_by(
        registration_number=registration_number
    ).filter(
        db.extract('month', Attendance.date) == month,
        db.extract('year', Attendance.date) == year
    ).all()

    attendance_map = {r.date.day: r.status for r in records}

    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]

    return {
        'calendar': cal,
        'attendance_map': attendance_map,
        'month_name': month_name,
        'month': month,
        'year': year
    }


def get_absent_students_today():
    """Returns list of absent students for today with parent contact."""
    today = date.today()

    absent_records = Attendance.query.filter_by(
        date=today, status='Absent'
    ).all()

    result = []
    for record in absent_records:
        student = Student.query.filter_by(
            registration_number=record.registration_number
        ).first()
        if student:
            result.append({
                'registration_number': student.registration_number,
                'name': student.name,
                'room_number': student.room_number,
                'department': student.department,
                'parent_phone': student.parent_phone,
                'marked_at': record.marked_at.strftime('%I:%M %p') if record.marked_at else 'N/A'
            })

    return result
