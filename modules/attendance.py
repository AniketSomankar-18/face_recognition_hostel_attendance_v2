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


def mark_attendance(registration_number, confidence=1.0, marked_by='face_recognition'):
    """
    Mark attendance (IN or OUT) for a student with duplicate prevention.
    Returns: (success: bool, message: str, direction: str)
    """
    today = date.today()
    now = datetime.now()

    # 1. Validate Student
    student = Student.query.filter_by(registration_number=registration_number, is_active=True).first()
    if not student:
        return False, "Identity not found in database.", None

    # 2. Check for Cooldown (Anti-Duplicate Pulse)
    # Don't allow marking same user within 5 minutes to prevent camera stutter triggers
    last_record = Attendance.query.filter_by(
        registration_number=registration_number, 
        date=today
    ).order_by(Attendance.marked_at.desc()).first()

    if last_record:
        time_diff = (now - last_record.marked_at).total_seconds() / 60
        if time_diff < 5: # 5 minute cooldown
            return False, f"Cooldown active. Last pulses was {int(time_diff)}m ago.", last_record.direction

    # 3. Determine Direction (IN/OUT Toggle)
    # If no records today, it's an 'IN'. If last was 'IN', this is 'OUT'.
    direction = 'IN'
    if last_record and last_record.direction == 'IN':
        direction = 'OUT'

    # 4. Check for Leave
    leave = Leave.query.filter_by(registration_number=registration_number, approved=True).filter(
        Leave.from_date <= today, Leave.to_date >= today
    ).first()

    status = 'Present'
    if leave:
        status = 'Leave'
    else:
        # Determine Late status based on time window if needed
        window = get_attendance_status_for_time()
        if window == 'open_late': status = 'Late'

    # 5. Persist Log
    record = Attendance(
        registration_number=registration_number,
        date=today,
        status=status,
        direction=direction,
        confidence=confidence,
        marked_at=now,
        marked_by=marked_by
    )
    db.session.add(record)
    db.session.commit()

    return True, f"{direction} recorded for {student.name} ({confidence}%)", direction


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

    # Count unique students who marked today
    present = db.session.query(Attendance.registration_number).filter(
        Attendance.date == today, 
        Attendance.status.in_(['Present', 'Late'])
    ).distinct().count()
    
    late = db.session.query(Attendance.registration_number).filter(
        Attendance.date == today, 
        Attendance.status == 'Late'
    ).distinct().count()
    
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


def get_hostel_structure_stats(building_code='N'):
    """
    Returns statistics for a building's blocks and rooms.
    Format: N <block><floor><room> (e.g. N AG01)
    """
    today = date.today()
    blocks = ['A', 'B', 'C', 'D']
    if building_code == 'SH':
        floors = ['G', 'F', 'S', 'T']
        rooms = [f"{i:02d}" for i in range(1, 11)]
    else:
        floors = ['G', 'F']
        rooms = [f"{i:02d}" for i in range(1, 9)]

    stats = {
        'total_students': 0,
        'present_today': 0,
        'blocks': {}
    }

    # Optimization: Get all students and latest attendance for today once
    all_students = Student.query.filter(Student.room_number.like(f"{building_code} %")).all()
    # Get all attendance for today, ordered by time to pick the latest
    all_attendance = Attendance.query.filter_by(date=today).order_by(Attendance.marked_at.asc()).all()
    
    # Store latest status and direction per student
    attendance_map = {}
    for a in all_attendance:
        attendance_map[a.registration_number] = {
            'status': a.status,
            'direction': a.direction,
            'confidence': a.confidence
        }

    stats['total_students'] = len(all_students)
    stats['present_today'] = sum(1 for s in all_students if attendance_map.get(s.registration_number, {}).get('status') in ['Present', 'Late'])

    for block in blocks:
        block_students = [s for s in all_students if s.room_number.startswith(f"{building_code} {block}")]
        block_present = sum(1 for s in block_students if attendance_map.get(s.registration_number, {}).get('status') in ['Present', 'Late'])

        stats['blocks'][block] = {
            'total': len(block_students),
            'present': block_present,
            'floors': {}
        }

        for floor in floors:
            floor_students = [s for s in block_students if s.room_number.startswith(f"{building_code} {block}{floor}")]
            
            stats['blocks'][block]['floors'][floor] = {
                'rooms': {}
            }

            for room_num in rooms:
                room_id = f"{building_code} {block}{floor}{room_num}"
                room_students = [s for s in floor_students if s.room_number == room_id]
                
                if not room_students:
                    stats['blocks'][block]['floors'][floor]['rooms'][room_num] = {
                        'status': 'empty',
                        'count': 0,
                        'present': 0,
                        'students': []
                    }
                    continue

                room_present = sum(1 for s in room_students if attendance_map.get(s.registration_number, {}).get('status') in ['Present', 'Late'])
                room_absent = len(room_students) - room_present
                
                status = 'full'
                if room_absent > 0:
                    status = 'absent'
                # if room_present > 0 and any(attendance_map.get(s.registration_number) == 'Late' for s in room_students):
                #     status = 'warning'

                stats['blocks'][block]['floors'][floor]['rooms'][room_num] = {
                    'status': status,
                    'count': len(room_students),
                    'present': room_present,
                    'students': [{
                        'name': s.name,
                        'reg': s.registration_number,
                        'status': attendance_map.get(s.registration_number, {}).get('status', 'Unmarked'),
                        'direction': attendance_map.get(s.registration_number, {}).get('direction', 'N/A')
                    } for s in room_students]
                }

    return stats


def get_historical_stats(days=30):
    """Returns attendance percentage for the last X days."""
    from datetime import timedelta
    today = date.today()
    results = []

    total_students = Student.query.filter_by(is_active=True).count()
    if total_students == 0:
        return []

    for i in range(days - 1, -1, -1):
        target_date = today - timedelta(days=i)
        
        # Count present/late for this date
        present_count = Attendance.query.filter_by(date=target_date).filter(
            Attendance.status.in_(['Present', 'Late'])
        ).count()
        
        pct = round((present_count / total_students) * 100, 1)
        results.append({
            'date': target_date.strftime('%d %b'),
            'percentage': pct,
            'count': present_count
        })

    return results
