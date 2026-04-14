from datetime import datetime, date, time, timedelta
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
        # If last record was 'Absent', we ignore the cooldown and allow marking 'Present'
        if last_record.status == 'Absent':
            pass 
        else:
            time_diff = (now - last_record.marked_at).total_seconds() / 60
            if time_diff < 5: # 5 minute cooldown
                return False, f"Cooldown active. Last pulses was {int(time_diff)}m ago.", last_record.direction

    # 3. Determine Direction (IN/OUT Toggle)
    # If no records today, it's an 'IN'. If last was 'IN', this is 'OUT'.
    direction = 'IN'
    if last_record and last_record.status != 'Absent' and last_record.direction == 'IN':
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
    """Batch mark students as absent or on leave."""
    today = date.today()
    active_students = Student.query.filter_by(is_active=True).all()
    
    # Get all students who already have a record today
    already_marked = {r.registration_number for r in db.session.query(Attendance.registration_number).filter_by(date=today).all()}
    
    # Get all students who are on approved leave today
    leaves = Leave.query.filter(
        Leave.approved == True,
        Leave.from_date <= today,
        Leave.to_date >= today
    ).all()
    on_leave = {l.registration_number for l in leaves}
    
    marked_count = 0
    now = datetime.now()
    
    for student in active_students:
        reg = student.registration_number
        if reg in already_marked:
            continue
            
        status = 'Leave' if reg in on_leave else 'Absent'
        
        db.session.add(Attendance(
            registration_number=reg,
            date=today,
            status=status,
            marked_at=now,
            marked_by='auto_system'
        ))
        marked_count += 1
        
    db.session.commit()
    return marked_count


def get_today_summary(hostel_code='ALL'):
    """Aggregate statistics for today (Optimized + Hostel Filter)."""
    today = date.today()
    
    # 1. Base query for total students
    student_query = Student.query.filter_by(is_active=True)
    if hostel_code != 'ALL':
        student_query = student_query.filter(Student.room_number.like(f"{hostel_code} %"))
    
    total_students = student_query.count()

    # 2. Optimized Database query: Only fetch the necessary columns, bypass ORM instantiation overhead
    attendance_query = db.session.query(
        Attendance.registration_number, 
        Attendance.status
    ).join(
        Student, Attendance.registration_number == Student.registration_number
    ).filter(
        Attendance.date == today,
        Student.is_active == True
    ).order_by(Attendance.marked_at.asc())
    
    if hostel_code != 'ALL':
        attendance_query = attendance_query.filter(Student.room_number.like(f"{hostel_code} %"))
        
    records = attendance_query.all()
    
    # Map to latest status (overwrites earlier records for same reg_num due to asc order)
    latest_statuses = {reg_num: status for reg_num, status in records}

    # Count statuses
    counts = {'Present': 0, 'Late': 0, 'Absent': 0, 'Leave': 0}
    for status in latest_statuses.values():
        if status in counts:
            counts[status] += 1

    present = counts['Present']
    late = counts['Late']
    absent = counts['Absent']
    leave = counts['Leave']
    unmarked = total_students - (present + late + absent + leave)

    pct = round(((present + late) / total_students * 100), 1) if total_students > 0 else 0

    return {
        'total': total_students,
        'present': present,
        'late': late,
        'absent': absent,
        'leave': leave,
        'unmarked': max(0, unmarked),
        'percentage': pct,
        'date': today.strftime("%d %B %Y"),
        'day': today.strftime("%A")
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
    """Returns list of absent students for today with parent contact (Optimized)."""
    today = date.today()

    # Use a JOIN to fetch Attendance and related Student data in one query
    results = db.session.query(Attendance, Student).join(
        Student, Attendance.registration_number == Student.registration_number
    ).filter(
        Attendance.date == today,
        Attendance.status == 'Absent'
    ).all()

    absent_list = []
    for record, student in results:
        absent_list.append({
            'registration_number': student.registration_number,
            'name': student.name,
            'room_number': student.room_number,
            'department': student.department,
            'parent_phone': student.parent_phone,
            'marked_at': record.marked_at.strftime('%I:%M %p') if record.marked_at else 'N/A'
        })

    return absent_list


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
    elif building_code in ['N', 'D', 'K', 'G']:
        floors = ['G', 'F']
        rooms = [f"{i:02d}" for i in range(1, 9)]
    else:
        floors = ['G']
        rooms = [f"{i:02d}" for i in range(1, 5)]

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


def get_historical_stats(days=30, hostel_code='ALL'):
    """Fetch attendance percentages for the last N days (Optimized + Hostel Filter)."""
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # 1. Total active students by hostel
    student_query = Student.query.filter_by(is_active=True)
    if hostel_code != 'ALL':
        student_query = student_query.filter(Student.room_number.like(f"{hostel_code} %"))
    total_count = student_query.count()
    if total_count == 0:
        return []

    # 2. Daily aggregate of Present/Late records
    # Join with Student to filter by hostel
    query = db.session.query(
        Attendance.date,
        db.func.count(Attendance.id)
    ).join(Student, Attendance.registration_number == Student.registration_number).filter(
        Attendance.date.between(start_date, end_date),
        Attendance.status.in_(['Present', 'Late'])
    )
    
    if hostel_code != 'ALL':
        query = query.filter(Student.room_number.like(f"{hostel_code} %"))
        
    daily_stats = query.group_by(Attendance.date).order_by(Attendance.date.asc()).all()

    # Map results to percentage
    history = []
    for d, count in daily_stats:
        history.append({
            'date': d.strftime("%d %b"),
            'percentage': round((count / total_count * 100), 1)
        })

    return history
