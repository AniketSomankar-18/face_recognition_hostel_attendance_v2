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

        for student in active_students:
            # Already has an attendance record today?
            existing = Attendance.query.filter_by(
                registration_number=student.registration_number,
                date=today
            ).first()
            if existing:
                continue   # already marked (Present / Late / Leave / Absent)

            # On approved leave?
            on_leave = Leave.query.filter_by(
                registration_number=student.registration_number,
                approved=True
            ).filter(
                Leave.from_date <= today,
                Leave.to_date >= today
            ).first()

            if on_leave:
                # Mark Leave – no penalty
                record = Attendance(
                    registration_number=student.registration_number,
                    date=today,
                    status='Leave',
                    marked_at=datetime.now(),
                    marked_by='auto_system'
                )
                db.session.add(record)
                continue

            # ── Mark Absent ──────────────────────────────────────────
            record = Attendance(
                registration_number=student.registration_number,
                date=today,
                status='Absent',
                marked_at=datetime.now(),
                marked_by='auto_system'
            )
            db.session.add(record)
            results['marked_absent'] += 1

            # ── Apply Penalty ────────────────────────────────────────
            student.absence_count = (student.absence_count or 0) + 1
            amount = get_penalty_amount(student.absence_count)

            penalty = Penalty(
                registration_number=student.registration_number,
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
                results['errors'].append(f"Email error for {student.registration_number}: {e}")

        db.session.commit()

        print(f"[PENALTY SYSTEM] {today} | "
              f"Absent: {results['marked_absent']} | "
              f"Penalties: {results['penalties_applied']} | "
              f"Emails: {results['emails_sent']}")
        if results['errors']:
            for err in results['errors']:
                print(f"[PENALTY ERROR] {err}")

        return results


def get_penalty_summary():
    """Return aggregate penalty data for the penalties view."""
    penalties = Penalty.query.order_by(Penalty.date.desc()).all()

    result = []
    for p in penalties:
        student = Student.query.filter_by(
            registration_number=p.registration_number
        ).first()
        result.append({
            'id': p.id,
            'registration_number': p.registration_number,
            'student_name': student.name if student else 'N/A',
            'room_number': student.room_number if student else '—',
            'date': p.date,
            'penalty_amount': p.penalty_amount,
            'absence_count': p.absence_count,
            'reason': p.reason,
            'email_sent': p.email_sent
        })

    total = sum(p['penalty_amount'] for p in result)
    students_penalised = len(set(p['registration_number'] for p in result))

    return result, total, students_penalised
