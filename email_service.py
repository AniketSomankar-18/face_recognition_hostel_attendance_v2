"""
Email Notification Service
Sends penalty notices to students via Flask-Mail.
"""
from flask_mail import Mail, Message

mail = Mail()


def init_mail(app):
    """Call this in app factory after setting mail config."""
    mail.init_app(app)


def send_penalty_email(app, student_name, student_email, penalty_amount, absence_count):
    """
    Send absence penalty notice to a student.

    Args:
        app: Flask app (needed for app context in scheduler thread)
        student_name: str
        student_email: str
        penalty_amount: int  (100 / 500 / 1000)
        absence_count: int

    Returns:
        (success: bool, message: str)
    """
    with app.app_context():
        try:
            subject = "Hostel Attendance Penalty Notice – SGGS"

            ordinal = {1: '1st', 2: '2nd'}.get(absence_count, f'{absence_count}th')

            body = f"""Dear {student_name},

This is to inform you that you did not mark your hostel attendance today (before 9:30 PM).

Absence Record  : {ordinal} absence
Penalty Applied : ₹{penalty_amount}

Please contact the hostel office if you believe this is an error.

Note: Penalties are applied as follows:
  1st absence  → ₹100
  2nd absence  → ₹500
  3rd+ absence → ₹1000

Regards,
SGGS Hostel Administration
Shri Guru Gobind Singhji Institute of Engineering and Technology
"""

            msg = Message(
                subject=subject,
                recipients=[student_email],
                body=body
            )
            mail.send(msg)
            return True, f"Email sent to {student_email}"

        except Exception as e:
            return False, f"Email failed for {student_email}: {str(e)}"
