"""
Automatic Penalty System
Runs at 9:30 PM daily via APScheduler.

For each student not marked Present/Late today:
  - Marks them Absent
  - Increments absence_count
  - Applies penalty: 1st → ₹100, 2nd → ₹500, 3rd+ → ₹1000
  - Sends email notification
"""
from datetime import datetime, date
from models import db, Student, Attendance, Leave, Penalty
from email_service import send_penalty_email


def get_penalty_amount(absence_count: int) -> int:
    if absence_count == 1:
        return 100
    elif absence_count == 2:
        return 500
    else:
        return 1000


def finalize_attendance(app):
    """
    Main function called by APScheduler at 9:30 PM.
    Marks absent students, applies penalties, sends emails.
    """
    with app.app_context():
        today = date.today()
        results = {
            'marked_absent': 0,
            'penalties_applied': 0,
            'emails_sent': 0,
            'errors': []
        }

        active_students = Student.query.filter_by(is_active=True).all()
        
        # Batch lookup today's attendance
        attendance_records = {a.registration_number for a in Attendance.query.filter_by(date=today).all()}
        
        # Batch lookup active leaves
        leaves = {l.registration_number for l in Leave.query.filter(
            Leave.approved == True,
            Leave.from_date <= today,
            Leave.to_date >= today
        ).all()}

        for student in active_students:
            reg = student.registration_number
            if reg in attendance_records:
                continue

            if reg in leaves:
                # Mark Leave – no penalty
                db.session.add(Attendance(
                    registration_number=reg,
                    date=today,
                    status='Leave',
                    marked_at=datetime.now(),
                    marked_by='auto_system'
                ))
                continue

            # ── Mark Absent ──────────────────────────────────────────
            db.session.add(Attendance(
                registration_number=reg,
                date=today,
                status='Absent',
                marked_at=datetime.now(),
                marked_by='auto_system'
            ))
            results['marked_absent'] += 1

            # ── Apply Penalty ────────────────────────────────────────
            student.absence_count = (student.absence_count or 0) + 1
            amount = get_penalty_amount(student.absence_count)

            penalty = Penalty(
                registration_number=reg,
                date=today,
                penalty_amount=amount,
                absence_count=student.absence_count,
                reason=f'Absent – did not mark attendance by 9:30 PM'
            )
            db.session.add(penalty)
            results['penalties_applied'] += 1

            # ── Send Email ───────────────────────────────────────────
            try:
                success, msg = send_penalty_email(
                    app,
                    student.name,
                    student.email,
                    amount,
                    student.absence_count
                )
                if success:
                    penalty.email_sent = True
                    results['emails_sent'] += 1
                else:
                    results['errors'].append(msg)
            except Exception as e:
                results['errors'].append(f"Email error for {reg}: {e}")

        db.session.commit()

        print(f"[PENALTY SYSTEM] {today} | "
              f"Absent: {results['marked_absent']} | "
              f"Penalties: {results['penalties_applied']} | "
              f"Emails: {results['emails_sent']}")
        if results['errors']:
            for err in results['errors']:
                print(f"[PENALTY ERROR] {err}")

        return results


def get_penalty_summary(hostel_code='ALL'):
    """
    Get a summary of total penalties for all students, optimized for performance.
    """
    # Use a JOIN to fetch student names alongside penalties in one query
    query = db.session.query(
        Penalty.registration_number,
        Student.name,
        Student.room_number,
        db.func.sum(Penalty.penalty_amount).label('total_amount'),
        db.func.count(Penalty.id).label('violation_count')
    ).join(Student, Penalty.registration_number == Student.registration_number)
    
    if hostel_code != 'ALL':
        query = query.filter(Student.room_number.like(f"{hostel_code} %"))
        
    penalties = query.group_by(
        Penalty.registration_number, 
        Student.name,
        Student.room_number
    ).all()
    
    return [
        {
            'reg_num': p.registration_number,
            'name': p.name,
            'room': p.room_number,
            'amount': float(p.total_amount),
            'count': int(p.violation_count)
        }
        for p in penalties
    ]
