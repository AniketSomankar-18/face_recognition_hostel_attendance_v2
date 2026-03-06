import os
import base64
from datetime import datetime, date

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, send_file, Response)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from apscheduler.schedulers.background import BackgroundScheduler

from config import Config
from models import db, User, Student, Attendance, Leave, Penalty
from modules.face_recognition_module import FaceRecognitionModule
from modules.attendance import (mark_attendance, get_today_summary,
                                 mark_absents_for_today, get_student_attendance_history,
                                 get_calendar_data, get_absent_students_today)
from modules.reports import generate_excel_report, generate_absent_pdf
from penalty_system import finalize_attendance, get_penalty_summary
from email_service import mail, init_mail

# ─── App Setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config.from_object(Config)
Config.init_app(app)

# Flask-Mail config (edit these or use environment variables)
app.config.setdefault('MAIL_SERVER', 'smtp.gmail.com')
app.config.setdefault('MAIL_PORT', 587)
app.config.setdefault('MAIL_USE_TLS', True)
app.config.setdefault('MAIL_USERNAME', os.environ.get('MAIL_USERNAME', ''))
app.config.setdefault('MAIL_PASSWORD', os.environ.get('MAIL_PASSWORD', ''))
app.config.setdefault('MAIL_DEFAULT_SENDER', os.environ.get('MAIL_USERNAME', 'noreply@sggs.ac.in'))

db.init_app(app)
init_mail(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'

face_module = FaceRecognitionModule(Config)

# ─── Scheduler ────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler()
scheduler.add_job(
    lambda: finalize_attendance(app),
    'cron', hour=21, minute=30,
    id='auto_penalty'
)
scheduler.start()

# ─── Login ────────────────────────────────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ─── Dashboard ────────────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    summary = get_today_summary()
    model_trained = face_module.is_model_trained()
    dataset_count = face_module.get_student_count_in_dataset()
    return render_template('dashboard.html',
                           summary=summary,
                           model_trained=model_trained,
                           dataset_count=dataset_count)


# ─── Students ─────────────────────────────────────────────────────────────────
@app.route('/students')
@login_required
def students():
    search = request.args.get('search', '')
    dept = request.args.get('dept', '')
    query = Student.query.filter_by(is_active=True)
    if search:
        query = query.filter(
            (Student.name.ilike(f'%{search}%')) |
            (Student.registration_number.ilike(f'%{search}%')) |
            (Student.room_number.ilike(f'%{search}%'))
        )
    if dept:
        query = query.filter(Student.department == dept)
    students_list = query.order_by(Student.room_number).all()
    departments = [d[0] for d in db.session.query(Student.department).distinct().all()]
    student_data = [{'student': s, 'img_count': face_module.get_face_image_count(s.registration_number)}
                    for s in students_list]
    return render_template('students.html', student_data=student_data,
                           departments=departments, search=search, selected_dept=dept)


@app.route('/students/register', methods=['GET', 'POST'])
@login_required
def register_student():
    if request.method == 'POST':
        reg_num = request.form.get('registration_number', '').strip().upper()
        name = request.form.get('name', '').strip()
        room = request.form.get('room_number', '').strip()
        dept = request.form.get('department', '').strip()
        phone = request.form.get('phone', '').strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        email = request.form.get('email', '').strip()
        if not all([reg_num, name, room, dept, phone, parent_phone, email]):
            flash('All fields are required.', 'danger')
            return render_template('register.html', form_data=request.form)
        if Student.query.filter_by(registration_number=reg_num).first():
            flash(f'Student {reg_num} already exists.', 'danger')
            return render_template('register.html', form_data=request.form)
        student = Student(registration_number=reg_num, name=name, room_number=room,
                          department=dept, phone=phone, parent_phone=parent_phone, email=email)
        db.session.add(student)
        db.session.commit()
        flash(f'Student {name} registered successfully!', 'success')
        return redirect(url_for('capture_face', reg_num=reg_num))
    return render_template('register.html', form_data={})


@app.route('/students/<reg_num>/edit', methods=['GET', 'POST'])
@login_required
def edit_student(reg_num):
    student = Student.query.filter_by(registration_number=reg_num).first_or_404()
    if request.method == 'POST':
        student.name = request.form.get('name', student.name).strip()
        student.room_number = request.form.get('room_number', student.room_number).strip()
        student.department = request.form.get('department', student.department).strip()
        student.phone = request.form.get('phone', student.phone).strip()
        student.parent_phone = request.form.get('parent_phone', student.parent_phone).strip()
        student.email = request.form.get('email', student.email).strip()
        db.session.commit()
        flash(f'Student {student.name} updated.', 'success')
        return redirect(url_for('students'))
    return render_template('register.html', student=student, edit_mode=True, form_data=student.__dict__)


@app.route('/students/<reg_num>/delete', methods=['POST'])
@login_required
def delete_student(reg_num):
    student = Student.query.filter_by(registration_number=reg_num).first_or_404()
    student.is_active = False
    db.session.commit()
    flash(f'Student {student.name} removed.', 'info')
    return redirect(url_for('students'))


@app.route('/students/<reg_num>/view')
@login_required
def view_student(reg_num):
    student = Student.query.filter_by(registration_number=reg_num).first_or_404()
    today = date.today()
    month = int(request.args.get('month', today.month))
    year = int(request.args.get('year', today.year))
    cal_data = get_calendar_data(reg_num, month, year)
    attendance_records = get_student_attendance_history(reg_num)
    img_count = face_module.get_face_image_count(reg_num)
    present = sum(1 for r in attendance_records if r.status == 'Present')
    late = sum(1 for r in attendance_records if r.status == 'Late')
    absent = sum(1 for r in attendance_records if r.status == 'Absent')
    on_leave = sum(1 for r in attendance_records if r.status == 'Leave')
    total = len(attendance_records)
    pct = round((present + late) / total * 100, 1) if total > 0 else 0
    return render_template('history.html', student=student, cal_data=cal_data,
                           attendance_records=attendance_records[:30],
                           stats={'present': present, 'late': late, 'absent': absent,
                                  'leave': on_leave, 'total': total, 'percentage': pct},
                           img_count=img_count, month=month, year=year)


# ─── Face Capture ─────────────────────────────────────────────────────────────
@app.route('/capture/<reg_num>')
@login_required
def capture_face(reg_num):
    student = Student.query.filter_by(registration_number=reg_num).first_or_404()
    img_count = face_module.get_face_image_count(reg_num)
    return render_template('capture_face.html', student=student,
                           img_count=img_count, required=Config.FACE_IMAGES_REQUIRED)


@app.route('/api/capture_frame', methods=['POST'])
@login_required
def capture_frame():
    data = request.get_json()
    reg_num = data.get('reg_num')
    image_data = data.get('image')
    if not reg_num or not image_data:
        return jsonify({'success': False, 'message': 'Missing data'})
    student = Student.query.filter_by(registration_number=reg_num).first()
    if not student:
        return jsonify({'success': False, 'message': 'Student not found'})
    try:
        import cv2
        import numpy as np
        header, encoded = image_data.split(',', 1)
        img_bytes = base64.b64decode(encoded)
        np_arr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is None:
            return jsonify({'success': False, 'message': 'Invalid image'})
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5, minSize=(80, 80))
        if len(faces) == 0:
            return jsonify({'success': False, 'message': 'No face detected', 'count': 0})
        save_dir = os.path.join(Config.DATASET_DIR, reg_num)
        os.makedirs(save_dir, exist_ok=True)
        existing = len([f for f in os.listdir(save_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
        if existing >= Config.FACE_IMAGES_REQUIRED:
            return jsonify({'success': False, 'message': 'Enough images captured', 'count': existing})
        x, y, w, h = faces[0]
        face_img = frame[y:y+h, x:x+w]
        cv2.imwrite(os.path.join(save_dir, f"{existing + 1}.jpg"), face_img)
        new_count = existing + 1
        if new_count >= Config.FACE_IMAGES_REQUIRED:
            student.face_encoded = True
            db.session.commit()
        return jsonify({'success': True, 'message': f'Image {new_count} captured',
                        'count': new_count, 'required': Config.FACE_IMAGES_REQUIRED,
                        'complete': new_count >= Config.FACE_IMAGES_REQUIRED})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/get_face_count/<reg_num>')
@login_required
def get_face_count(reg_num):
    return jsonify({'count': face_module.get_face_image_count(reg_num),
                    'required': Config.FACE_IMAGES_REQUIRED})


# ─── Train Model ──────────────────────────────────────────────────────────────
@app.route('/train', methods=['POST'])
@login_required
def train_model():
    # FIX: properly detect and use face_recognition library
    try:
        import face_recognition as fr_check   # noqa – just checking it's available
    except ImportError:
        flash('face_recognition library is not installed. Run: pip install face-recognition', 'danger')
        return redirect(url_for('dashboard'))

    success, message, count = face_module.train_model()
    if success:
        flash(f'✓ Model trained successfully! Encoded {count} students.', 'success')
    else:
        flash(f'✗ Training failed: {message}', 'danger')
    return redirect(url_for('dashboard'))


# ─── Attendance ───────────────────────────────────────────────────────────────
@app.route('/attendance')
@login_required
def attendance():
    summary = get_today_summary()
    today_records = Attendance.query.filter_by(date=date.today()).all()
    records_detail = []
    for record in today_records:
        student = Student.query.filter_by(registration_number=record.registration_number).first()
        if student:
            records_detail.append({'student': student, 'status': record.status,
                                    'marked_at': record.marked_at, 'marked_by': record.marked_by})
    model_trained = face_module.is_model_trained()
    return render_template('attendance.html', summary=summary,
                           records=records_detail, model_trained=model_trained)


@app.route('/attendance/video_feed')
@login_required
def video_feed():
    return Response(generate_video_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


def generate_video_frames():
    import cv2
    import time
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n\r\n'
        return
    with app.app_context():
        students = Student.query.filter_by(is_active=True).all()
        student_map = {s.registration_number: s.name for s in students}
    recently_marked = {}
    COOLDOWN = 10
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        results = face_module.recognize_face(frame)
        with app.app_context():
            for result in results:
                reg_num = result['reg_num']
                if reg_num:
                    now = time.time()
                    if now - recently_marked.get(reg_num, 0) > COOLDOWN:
                        mark_attendance(reg_num, 'face_recognition')
                        recently_marked[reg_num] = now
        frame = face_module.draw_recognition_results(frame, results, student_map)
        cv2.putText(frame, datetime.now().strftime('%I:%M:%S %p'),
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
        ret2, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret2:
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
    cap.release()


@app.route('/api/mark_manual', methods=['POST'])
@login_required
def mark_manual():
    reg_num = request.form.get('reg_num')
    status = request.form.get('status', 'Present')
    today = date.today()
    student = Student.query.filter_by(registration_number=reg_num).first()
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('attendance'))
    existing = Attendance.query.filter_by(registration_number=reg_num, date=today).first()
    if existing:
        existing.status = status
        existing.marked_by = current_user.username
        existing.marked_at = datetime.now()
    else:
        db.session.add(Attendance(registration_number=reg_num, date=today,
                                  status=status, marked_at=datetime.now(),
                                  marked_by=current_user.username))
    db.session.commit()
    flash(f'Attendance marked for {student.name}: {status}', 'success')
    return redirect(url_for('attendance'))


@app.route('/api/recognize_frame', methods=['POST'])
@login_required
def recognize_frame():
    data = request.get_json()
    image_data = data.get('image')
    if not image_data:
        return jsonify({'success': False, 'message': 'No image'})
    try:
        import cv2, numpy as np
        header, encoded = image_data.split(',', 1)
        frame = cv2.imdecode(np.frombuffer(base64.b64decode(encoded), np.uint8), cv2.IMREAD_COLOR)
        results = face_module.recognize_face(frame)
        recognition_results = []
        for result in results:
            reg_num = result['reg_num']
            if reg_num:
                student = Student.query.filter_by(registration_number=reg_num, is_active=True).first()
                if student:
                    success, msg, status = mark_attendance(reg_num, 'face_recognition')
                    recognition_results.append({'reg_num': reg_num, 'name': student.name,
                                                'room': student.room_number, 'status': status or 'Unknown',
                                                'message': msg, 'success': success,
                                                'confidence': result['confidence']})
            else:
                recognition_results.append({'reg_num': None, 'name': 'Unknown',
                                             'message': 'Unknown person', 'success': False, 'confidence': 0})
        return jsonify({'success': True, 'results': recognition_results, 'faces_count': len(results)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ─── Leave Management ─────────────────────────────────────────────────────────
@app.route('/leave')
@login_required
def leave_management():
    leaves = Leave.query.order_by(Leave.created_at.desc()).all()
    leave_data = [{'leave': l, 'student': Student.query.filter_by(registration_number=l.registration_number).first()}
                  for l in leaves]
    students = Student.query.filter_by(is_active=True).order_by(Student.name).all()
    return render_template('leave_management.html', leave_data=leave_data, students=students)


@app.route('/leave/add', methods=['POST'])
@login_required
def add_leave():
    reg_num = request.form.get('registration_number', '').strip().upper()
    from_date_str = request.form.get('from_date')
    to_date_str = request.form.get('to_date')
    reason = request.form.get('reason', '').strip()
    leave_type = request.form.get('leave_type', 'Personal')
    approve = request.form.get('approve') == 'on'
    if not all([reg_num, from_date_str, to_date_str, reason]):
        flash('All fields are required.', 'danger')
        return redirect(url_for('leave_management'))
    student = Student.query.filter_by(registration_number=reg_num).first()
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('leave_management'))
    from_dt = datetime.strptime(from_date_str, '%Y-%m-%d').date()
    to_dt = datetime.strptime(to_date_str, '%Y-%m-%d').date()
    leave = Leave(registration_number=reg_num, from_date=from_dt, to_date=to_dt,
                  reason=reason, leave_type=leave_type, approved=approve,
                  approved_by=current_user.username if approve else None)
    db.session.add(leave)
    db.session.commit()
    flash(f"Leave {'approved' if approve else 'added'} for {student.name}.", 'success')
    return redirect(url_for('leave_management'))


@app.route('/leave/<int:leave_id>/approve', methods=['POST'])
@login_required
def approve_leave(leave_id):
    leave = Leave.query.get_or_404(leave_id)
    leave.approved = True
    leave.approved_by = current_user.username
    db.session.commit()
    flash('Leave approved.', 'success')
    return redirect(url_for('leave_management'))


@app.route('/leave/<int:leave_id>/delete', methods=['POST'])
@login_required
def delete_leave(leave_id):
    leave = Leave.query.get_or_404(leave_id)
    db.session.delete(leave)
    db.session.commit()
    flash('Leave deleted.', 'info')
    return redirect(url_for('leave_management'))


# ─── Absent List  (FIX: pass `now`) ──────────────────────────────────────────
@app.route('/absent_list')
@login_required
def absent_list():
    today = datetime.now().date()          # ← FIX: always defined
    absent_students = get_absent_students_today()
    summary = get_today_summary()
    return render_template('absent_list.html',
                           absent_students=absent_students,
                           summary=summary,
                           now=today)                   # ← FIX: passed to template


# ─── Penalties ────────────────────────────────────────────────────────────────
@app.route('/penalties')
@login_required
def penalties_view():
    penalties, total_penalty, students_penalised = get_penalty_summary()
    return render_template('penalties.html',
                           penalties=penalties,
                           total_penalty=total_penalty,
                           students_penalised=students_penalised,
                           today=date.today().strftime('%d %b %Y'))


@app.route('/api/run_penalty_now', methods=['POST'])
@login_required
def run_penalty_now():
    """Manual trigger for testing penalty system."""
    try:
        results = finalize_attendance(app)
        return jsonify({'success': True,
                        'marked_absent': results['marked_absent'],
                        'penalties_applied': results['penalties_applied'],
                        'emails_sent': results['emails_sent']})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/mark_absent_all', methods=['POST'])
@login_required
def api_mark_absent_all():
    count = mark_absents_for_today()
    return jsonify({'success': True, 'message': f'Marked {count} students as absent.'})


# ─── Reports ──────────────────────────────────────────────────────────────────
@app.route('/report/excel')
@login_required
def download_excel():
    today = date.today()
    month = int(request.args.get('month', today.month))
    year = int(request.args.get('year', today.year))
    try:
        import calendar
        output = generate_excel_report(month, year)
        filename = f'attendance_{calendar.month_name[month]}_{year}.xlsx'
        return send_file(output,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f'Error generating Excel: {e}', 'danger')
        return redirect(url_for('dashboard'))


@app.route('/report/pdf')
@login_required
def download_pdf():
    target_date_str = request.args.get('date')
    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date() if target_date_str else date.today()
    except ValueError:
        target_date = date.today()
    try:
        output = generate_absent_pdf(target_date)
        filename = f'absent_report_{target_date.strftime("%d_%m_%Y")}.pdf'
        return send_file(output, mimetype='application/pdf',
                         as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f'Error generating PDF: {e}', 'danger')
        return redirect(url_for('absent_list'))


# ─── API ──────────────────────────────────────────────────────────────────────
@app.route('/api/summary')
@login_required
def api_summary():
    return jsonify(get_today_summary())


@app.route('/api/students/search')
@login_required
def search_students():
    q = request.args.get('q', '')
    students = Student.query.filter_by(is_active=True).filter(
        (Student.name.ilike(f'%{q}%')) | (Student.registration_number.ilike(f'%{q}%'))
    ).limit(10).all()
    return jsonify([{'reg_num': s.registration_number, 'name': s.name,
                     'room': s.room_number, 'dept': s.department} for s in students])


# ─── Database Init ────────────────────────────────────────────────────────────
def init_database():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='warden').first():
            warden = User(username='warden', role='warden')
            warden.set_password('warden123')
            db.session.add(warden)
            db.session.commit()
            print("[INFO] Default warden created.")
        if Student.query.count() == 0:
            samples = [
                Student(registration_number='2023CS001', name='Rahul Kumar',
                        room_number='A-101', department='Computer Science',
                        phone='9876543210', parent_phone='9876543200', email='rahul@example.com'),
                Student(registration_number='2023CS002', name='Priya Sharma',
                        room_number='A-102', department='Computer Science',
                        phone='9876543211', parent_phone='9876543201', email='priya@example.com'),
                Student(registration_number='2023EC001', name='Arjun Patel',
                        room_number='B-201', department='Electronics',
                        phone='9876543212', parent_phone='9876543202', email='arjun@example.com'),
                Student(registration_number='2023ME001', name='Sneha Reddy',
                        room_number='B-202', department='Mechanical',
                        phone='9876543213', parent_phone='9876543203', email='sneha@example.com'),
                Student(registration_number='2023CE001', name='Vikram Singh',
                        room_number='C-301', department='Civil',
                        phone='9876543214', parent_phone='9876543204', email='vikram@example.com'),
            ]
            for s in samples:
                db.session.add(s)
            db.session.commit()
            print("[INFO] Sample students added.")


if __name__ == '__main__':
    init_database()
    print("[INFO] Starting SGGS Hostel Attendance System")
    print("[INFO] URL: http://127.0.0.1:5000")
    print("[INFO] Login: warden / warden123")
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
