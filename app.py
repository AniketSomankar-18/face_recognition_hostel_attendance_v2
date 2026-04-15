import os
import base64
import fcntl
import atexit
import threading
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
                                 get_calendar_data, get_absent_students_today,
                                 get_hostel_structure_stats, get_historical_stats)
from modules.reports import generate_excel_report, generate_absent_pdf
from penalty_system import finalize_attendance, get_penalty_summary
from email_service import mail, init_mail
from supabase_storage import upload_encodings, download_encodings, get_encodings_url, upload_frame
from modules.cloud_sync import sync_local_dataset_to_cloud

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

# On startup, pull latest encodings from Supabase Storage if local copy is missing
if not os.path.exists(Config.ENCODINGS_FILE):
    print("[STARTUP] No local encodings found. Attempting download from Supabase Storage...")
    download_encodings(Config.ENCODINGS_FILE)
    if os.path.exists(Config.ENCODINGS_FILE):
        face_module._load_encodings()  # Reload into memory

# ─── Training State ───────────────────────────────────────────────────────────
training_lock = threading.Lock()
is_training = False
last_training_error = None

def background_train(app_context):
    global is_training, last_training_error
    with app_context:
        try:
            success, message, count = face_module.train_model()
            if success:
                # Persist encodings to Supabase Storage so they survive Render deploys
                up_success, up_msg = upload_encodings(Config.ENCODINGS_FILE)
                if not up_success:
                    print(f"[TRAIN] FAILED to push encodings to cloud: {up_msg}")
                    last_training_error = up_msg
            else:
                last_training_error = message
        except Exception as e:
            last_training_error = str(e)
        finally:
            is_training = False

# ─── Scheduler ────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler()
scheduler.add_job(
    lambda: finalize_attendance(app),
    'cron', hour=21, minute=30,
    id='auto_penalty'
)

# Use file lock to ensure only one gunicorn worker starts the scheduler
try:
    scheduler_lock_file = open("scheduler.lock", "wb")
    fcntl.flock(scheduler_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    scheduler.start()
    atexit.register(lambda: fcntl.flock(scheduler_lock_file, fcntl.LOCK_UN))
    print("[INFO] Scheduler started by master lock worker.")
except BlockingIOError:
    # Another worker already got the lock
    pass
except IOError:
    # Fallback for some systems where IOError is raised instead of BlockingIOError
    pass

# ─── Login ────────────────────────────────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.before_request
def enforce_auth():
    """Fail-safe: Redirect unauthenticated users to login for all restricted routes."""
    # List of endpoints allowed without login
    whitelist = ['login', 'static', 'get_camera_state', 'recognize_frame',
                 'pi_sync_encodings', 'pi_mark_present', 'pi_upload_encodings',
                 'pi_task_complete', 'get_encodings_url']
    if not current_user.is_authenticated and request.endpoint not in whitelist:
        if request.endpoint:
            return redirect(url_for('login'))


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
def get_code_from_name(name):
    mapping = {
        'nandagiri': 'N', 'sahyadri': 'SH', 'sahyandri': 'SH',
        'devgiri': 'D', 'krishna': 'K', 'godavari': 'G'
    }
    return mapping.get(name.lower(), name.upper())


@app.route('/dashboard')
@login_required
def dashboard():
    hostel_code = current_user.hostel_code
    summary = get_today_summary(hostel_code)
    
    # Building Metadata
    all_hostels = [
        {'id': 'N', 'name': 'Nandagiri', 'gender': 'Boys'},
        {'id': 'SH', 'name': 'Sahyadri', 'gender': 'Boys'},
        {'id': 'D', 'name': 'Devgiri', 'gender': 'Girls'},
        {'id': 'K', 'name': 'Krishna', 'gender': 'Girls'},
        {'id': 'G', 'name': 'Godavari', 'gender': 'Girls'}
    ]
    
    buildings = []
    for h in all_hostels:
        # Filter for wardens
        if not current_user.is_rector and h['id'] != hostel_code:
            continue
            
        stats = get_hostel_structure_stats(h['id'])
        buildings.append({
            'id': h['id'],
            'name': h['name'],
            'gender': h['gender'],
            'total': stats['total_students'],
            'present': stats['present_today'],
            'pct': round(stats['present_today'] / stats['total_students'] * 100, 1) if stats['total_students'] > 0 else 0
        })

    historical_stats = get_historical_stats(30, hostel_code)
    model_trained = os.path.exists('trainer.yml')
    
    return render_template('dashboard.html', 
                          summary=summary, 
                          buildings=buildings,
                          historical_stats=historical_stats,
                          model_trained=model_trained)


@app.route('/dashboard/building/<name>')
@login_required
def building_view(name):
    code = get_code_from_name(name)
    # RBAC: Check if warden is allowed to view this building
    if not current_user.is_rector and code != current_user.hostel_code:
        flash("You do not have permission to view other hostels.", "error")
        return redirect(url_for('dashboard'))
        
    res = get_hostel_structure_stats(code)
    return render_template('building_view.html', 
                           building_name=name.capitalize(), 
                           building_code=name.upper(),
                           stats=res)


@app.route('/dashboard/building/<building>/block/<block>')
@login_required
def block_view(building, block):
    code = get_code_from_name(building)
    stats = get_hostel_structure_stats(code)
    block_data = stats['blocks'].get(block.upper())
    if not block_data:
        flash(f"Block {block} not found.", "danger")
        return redirect(url_for('dashboard'))
        
    return render_template('block_view.html',
                           building_name=building.capitalize(),
                           building_code=code,
                           block_name=block.upper(),
                           block_data=block_data)


# ─── Students ─────────────────────────────────────────────────────────────────
@app.route('/students/search', methods=['POST'])
@login_required
def search_students_global():
    query = request.form.get('query', '').strip()
    return redirect(url_for('students', search=query))


@app.route('/students')
@login_required
def students():
    search = request.args.get('search', '').strip()
    selected_dept = request.args.get('dept', '').strip()

    # Base query for students
    query = Student.query.filter_by(is_active=True)
    if not current_user.is_rector:
        query = query.filter(Student.room_number.like(f"{current_user.hostel_code} %"))
    
    # 1. Fetch unique departments efficiently using distinct()
    dept_query = db.session.query(Student.department).filter(Student.is_active == True)
    if not current_user.is_rector:
        dept_query = dept_query.filter(Student.room_number.like(f"{current_user.hostel_code} %"))
    
    departments = [d[0] for d in dept_query.distinct().all() if d[0]]
    departments.sort()

    # 2. Apply directory filters
    if search:
        query = query.filter(db.or_(
            Student.name.ilike(f"%{search}%"),
            Student.registration_number.ilike(f"%{search}%"),
            Student.room_number.ilike(f"%{search}%")
        ))
    
    if selected_dept:
        query = query.filter(Student.department == selected_dept)
    
    students_list = query.order_by(Student.name).all()
    
    # 3. Context for modernized template
    student_data = []
    for s in students_list:
        student_data.append({
            'student': s,
            'img_count': s.face_samples_count
        })
        
    return render_template('students.html', 
                          student_data=student_data, 
                          departments=departments,
                          search=search,
                          selected_dept=selected_dept)


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
    
    # RBAC: Access check
    if not current_user.is_rector and not student.room_number.startswith(current_user.hostel_code):
        flash("Access Denied: You can only view students from your assigned hostel.", "error")
        return redirect(url_for('students'))
        
    recent_attendance = Attendance.query.filter_by(registration_number=reg_num).order_by(Attendance.date.desc()).limit(10).all()
    return render_template('student_detail.html', student=student, attendance=recent_attendance)


# ─── Face Capture ─────────────────────────────────────────────────────────────
@app.route('/capture/<reg_num>')
@login_required
def capture_face(reg_num):
    student = Student.query.filter_by(registration_number=reg_num).first_or_404()
    img_count = student.face_samples_count
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
            return jsonify({'success': False, 'message': 'Invalid image data'})

        save_dir = os.path.join(Config.DATASET_DIR, reg_num)
        os.makedirs(save_dir, exist_ok=True)
        # TRITICAL FIX: Use database count instead of os.listdir because Render wipes local files.
        existing = student.face_samples_count

        if existing >= Config.FACE_IMAGES_REQUIRED:
            # Force a re-upload of one frame to Supabase to verify sync
            # This helps users who have local files but empty cloud buckets
            first_frame = os.path.join(save_dir, "1.jpg")
            if os.path.exists(first_frame):
                with open(first_frame, 'rb') as f:
                    up_success, up_msg = upload_frame(reg_num, "1.jpg", f.read())
                    if not up_success:
                        return jsonify({'success': False, 'message': f'Cloud sync check failed: {up_msg}'})
            return jsonify({'success': True, 'message': 'Target reached! All photos are secured in the cloud.', 'count': existing, 'complete': True})

        # Save the full frame — face validation happens at training time
        img_path = os.path.join(save_dir, f"{existing + 1}.jpg")
        cv2.imwrite(img_path, frame)

        # Upload frame to Supabase Storage so Pi can download for training
        with open(img_path, 'rb') as f:
            up_success, up_msg = upload_frame(reg_num, f"{existing + 1}.jpg", f.read())
            if not up_success:
                return jsonify({'success': False, 'message': f'Cloud Storage Error: {up_msg}. Please check your Service Role Key and Bucket Permissions (Must have INSERT policy).'})

        new_count = existing + 1
        student.face_samples_count = new_count
        if new_count >= Config.FACE_IMAGES_REQUIRED:
            student.face_encoded = True
        db.session.commit()

        return jsonify({'success': True, 'message': f'Frame {new_count} saved',
                        'count': new_count, 'required': Config.FACE_IMAGES_REQUIRED,
                        'complete': new_count >= Config.FACE_IMAGES_REQUIRED})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/get_face_count/<reg_num>')
@login_required
def get_face_count(reg_num):
    student = Student.query.filter_by(registration_number=reg_num).first_or_404()
    return jsonify({'count': student.face_samples_count,
                    'required': Config.FACE_IMAGES_REQUIRED})


# ─── Raspberry Pi Edge Endpoints ──────────────────────────────────────────────
@app.route('/api/pi/sync_encodings', methods=['GET'])
def pi_sync_encodings():
    """
    Pi calls this on startup to get a signed download URL for encodings.pkl.
    No login required — Pi uses this to bootstrap its local recognition model.
    """
    url = get_encodings_url()
    if url:
        return jsonify({'success': True, 'url': url})
    # Fallback: try to serve local file directly
    if os.path.exists(Config.ENCODINGS_FILE):
        return send_file(Config.ENCODINGS_FILE,
                         mimetype='application/octet-stream',
                         as_attachment=True,
                         download_name='encodings.pkl')
    return jsonify({'success': False, 'message': 'No encodings available yet. Train the model first.'})


@app.route('/api/pi/mark_present', methods=['POST'])
def pi_mark_present():
    """
    Pi sends {"reg_num": "...", "confidence": 92.5} after local face recognition.
    Server just writes attendance to Supabase — no image processing needed.
    """
    data = request.get_json()
    reg_num = data.get('reg_num')
    confidence = data.get('confidence', 0.0)

    if not reg_num:
        return jsonify({'success': False, 'message': 'Missing reg_num'})

    try:
        success, message, direction = mark_attendance(reg_num, confidence, marked_by='raspberry_pi')
        return jsonify({'success': success, 'message': message, 'direction': direction})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/pi/upload_encodings', methods=['POST'])
def pi_upload_encodings():
    """
    Pi trains locally and uploads encodings.pkl here.
    Render saves it locally and pushes to Supabase Storage.
    """
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file provided'})
    f = request.files['file']
    try:
        os.makedirs(os.path.dirname(Config.ENCODINGS_FILE), exist_ok=True)
        f.save(Config.ENCODINGS_FILE)
        # Push to Supabase Storage for persistence
        upload_encodings(Config.ENCODINGS_FILE)
        # Reload into memory
        face_module._load_encodings()
        return jsonify({'success': True, 'message': 'Encodings updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/train', methods=['POST'])
@login_required
def train_model():
    # We now trigger the Pi to train remotely
    _save_camera_state_data(active=False, command='train')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Command sent to Raspberry Pi'})

    flash('Remote training command sent to Raspberry Pi.', 'info')
    return redirect(url_for('dashboard'))

@app.route('/api/training/status')
@login_required
def training_status():
    state = _get_camera_state_data()
    return jsonify({
        'is_training': state.get('command') == 'train',
        'error': None
    })


# ─── Attendance ───────────────────────────────────────────────────────────────
@app.route('/attendance')
@login_required
def attendance():
    summary = get_today_summary()
    
    # Bulk Join Query to prevent N+1 bottlenecks
    records_with_students = db.session.query(Attendance, Student).join(
        Student, Attendance.registration_number == Student.registration_number
    ).filter(Attendance.date == date.today()).all()

    records_detail = [
        {
            'student': student,
            'status': record.status,
            'marked_at': record.marked_at,
            'marked_by': record.marked_by
        }
        for record, student in records_with_students
    ]

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
    frame_count = 0
    results = [] # Persist results across skipped frames
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_count += 1
        # Process recognition every 5th frame for performance
        if frame_count % 5 == 0:
            results = face_module.recognize_face(frame)
            with app.app_context():
                for result in results:
                    reg_num = result['reg_num']
                    if reg_num:
                        now = time.time()
                        if now - recently_marked.get(reg_num, 0) > COOLDOWN:
                            mark_attendance(reg_num, 'face_recognition')
                            recently_marked[reg_num] = now
                            
        # Always draw the last known results on the current frame
        frame = face_module.draw_recognition_results(frame, results, student_map)
        
        cv2.putText(frame, datetime.now().strftime('%I:%M:%S %p'),
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
                    
        # Slightly lower quality for better streaming performance
        ret2, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
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
import json
import time

# ─── IoT Camera Edge State ────────────────────────────────────────────────────
CAMERA_STATE_FILE = os.path.join('scratch', 'camera_state.json')

def _get_camera_state_data():
    """ Internal helper to load state from disk. """
    try:
        if os.path.exists(CAMERA_STATE_FILE):
            with open(CAMERA_STATE_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {'active': False, 'command': 'idle', 'timestamp': time.time()}

def _save_camera_state_data(active, command):
    os.makedirs(os.path.dirname(CAMERA_STATE_FILE), exist_ok=True)
    with open(CAMERA_STATE_FILE, 'w') as f:
        json.dump({'active': active, 'command': command, 'timestamp': time.time()}, f)

@app.route('/api/camera/state', methods=['GET'])
def get_camera_state():
    return jsonify(_get_camera_state_data())

@app.route('/api/camera/toggle', methods=['POST'])
@login_required
def toggle_camera_state():
    data = request.get_json()
    active = data.get('active', False)
    command = 'recognize' if active else 'idle'
    _save_camera_state_data(active, command)
    return jsonify({'success': True, 'active': active, 'command': command})

@app.route('/api/pi/task_complete', methods=['POST'])
def pi_task_complete():
    """ Called by Pi to reset state to idle after training/stopping. """
    _save_camera_state_data(active=False, command='idle')
    return jsonify({'success': True})

@app.route('/api/attendance/recent', methods=['GET'])
@login_required
def get_recent_attendance():
    records = Attendance.query.filter_by(date=date.today()).order_by(Attendance.marked_at.desc()).limit(5).all()
    results = []
    for r in records:
        s = Student.query.filter_by(registration_number=r.registration_number).first()
        results.append({
            'reg_num': r.registration_number,
            'name': s.name if s else 'Unknown',
            'status': r.status,
            'room': s.room_number if s else 'N/A',
            'confidence': 100, # Display purpose
            'marked_at_str': r.marked_at.strftime('%I:%M:%S %p') if r.marked_at else '',
            'marked_at': r.marked_at.timestamp() if r.marked_at else 0
        })
    return jsonify({'success': True, 'results': results})


# ─── Leave Management ─────────────────────────────────────────────────────────
@app.route('/leave')
@login_required
def leave_management():
    # Bulk Join Query to prevent N+1 bottlenecks
    leaves_with_students = db.session.query(Leave, Student).outerjoin(
        Student, Leave.registration_number == Student.registration_number
    ).order_by(Leave.created_at.desc()).all()
    
    leave_data = [{'leave': l, 'student': s} for l, s in leaves_with_students]
    
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
@app.route('/reports/absent')
@login_required
def absent_list():
    # Filter absent list by hostel
    query = db.session.query(Attendance, Student).join(Student, Attendance.registration_number == Student.registration_number).filter(
        Attendance.date == date.today(),
        Attendance.status == 'Absent'
    )
    
    if not current_user.is_rector:
        query = query.filter(Student.room_number.like(f"{current_user.hostel_code} %"))
        
    absentees = query.all()
    absent_students = [a[1] for a in absentees]
    
    # Add summary for KPI cards
    summary = get_today_summary(current_user.hostel_code if not current_user.is_rector else None)
    
    return render_template('absent_list.html', 
                          absent_students=absent_students, 
                          summary=summary,
                          now=datetime.now())


# ─── Penalties ────────────────────────────────────────────────────────────────
@app.route('/penalties')
@login_required
def penalties_view():
    hostel_code = current_user.hostel_code
    
    # Detailed records for the log table
    query = db.session.query(Penalty, Student).join(
        Student, Penalty.registration_number == Student.registration_number
    )
    if not current_user.is_rector:
        query = query.filter(Student.room_number.like(f"{hostel_code} %"))
    
    results = query.order_by(Penalty.date.desc()).all()
    
    penalties_log = []
    total_penalty = 0
    unique_students = set()
    
    for p, s in results:
        total_penalty += p.penalty_amount
        unique_students.add(p.registration_number)
        penalties_log.append({
            'student_name': s.name,
            'registration_number': p.registration_number,
            'room_number': s.room_number,
            'date': p.date,
            'absence_count': p.absence_count,
            'penalty_amount': p.penalty_amount,
            'reason': p.reason
        })
    
    return render_template('penalties.html',
                           penalties=penalties_log,
                           total_penalty=total_penalty,
                           students_penalised=len(unique_students),
                           today=date.today().strftime('%d %b %Y'))


@app.route('/penalties/run_manual', methods=['POST'])
@login_required
def run_penalty_manual():
    """Manual trigger for penalty system via UI."""
    try:
        results = finalize_attendance(app)
        flash(f"✓ Penalty check complete! Marked {results['marked_absent']} absent, "
              f"applied {results['penalties_applied']} penalties, and sent {results['emails_sent']} emails.", "success")
    except Exception as e:
        flash(f"✗ Failed to run penalty check: {str(e)}", "danger")
    return redirect(url_for('penalties_view'))


@app.route('/attendance/mark_absent_all', methods=['POST'])
@login_required
def mark_absent_all_ui():
    """UI route to mark all unmarked students as absent."""
    count = mark_absents_for_today()
    if count > 0:
        flash(f"✓ Successfully marked {count} students as absent.", "success")
    else:
        flash("All students are already marked for today.", "info")
    return redirect(url_for('attendance'))


# ─── Reports ──────────────────────────────────────────────────────────────────
@app.route('/report/excel')
@login_required
def download_excel():
    today = date.today()
    month = int(request.args.get('month', today.month))
    year = int(request.args.get('year', today.year))
    try:
        import calendar
        # Filter is handled inside report generator if we pass it
        output = generate_excel_report(month, year, current_user.hostel_code)
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
        output = generate_absent_pdf(target_date, current_user.hostel_code)
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
            warden = User(username='warden', role='warden', hostel_code='N')
            warden.set_password('warden123')
            db.session.add(warden)
            print("[INFO] Default warden created.")
            
        if not User.query.filter_by(username='rector').first():
            rector = User(username='rector', role='rector', hostel_code=None)
            rector.set_password('rector123')
            db.session.add(rector)
            print("[INFO] Default rector created.")

        db.session.commit()

init_database()


@app.route('/admin/sync_cloud')
@login_required
def admin_sync_cloud():
    if current_user.role != 'rector':
        return "Unauthorized", 403
    
    result = sync_local_dataset_to_cloud()
    return jsonify(result)


@app.route('/admin/audit_dataset')
@login_required
def audit_dataset():
    """
    Audit Supabase Storage (face-dataset bucket) for anomalies that cause identity swaps:
    - Folders whose reg_num doesn't match any active student in the DB (orphans)
    - Students with >20 samples (possible cross-contamination)
    - Active students with zero samples (not enrolled)
    """
    if current_user.role != 'rector':
        return "Unauthorized", 403

    from supabase_storage import list_dataset_students, list_student_frames

    active_students = Student.query.filter_by(is_active=True).all()
    active_reg_nums = {s.registration_number for s in active_students}

    cloud_folders = list_dataset_students()
    if not cloud_folders:
        return jsonify({'error': 'Could not list Supabase dataset bucket. Check credentials or bucket name.'})

    orphan_folders = []
    suspicious = []
    ok = []
    not_enrolled = []

    for folder in sorted(cloud_folders):
        frames = list_student_frames(folder)
        count = len(frames)
        if folder not in active_reg_nums:
            orphan_folders.append({'folder': folder, 'images': count})
        elif count > 20:
            suspicious.append({'reg_num': folder, 'images': count,
                                'note': 'Exceeds 20-sample cap — trim to 20 clean photos'})
        else:
            ok.append({'reg_num': folder, 'images': count})

    cloud_set = set(cloud_folders)
    for s in active_students:
        if s.registration_number not in cloud_set:
            not_enrolled.append(s.registration_number)

    return jsonify({
        'total_cloud_folders': len(cloud_folders),
        'ok': len(ok),
        'orphan_folders': orphan_folders,
        'suspicious_folders': suspicious,
        'not_enrolled': not_enrolled,
        'action_required': bool(orphan_folders or suspicious)
    })


@app.route('/admin/purge_dataset', methods=['GET'])
@login_required
def purge_dataset():
    """
    Delete ALL frames from Supabase Storage for every enrolled student,
    reset their face_samples_count/face_encoded flags in the DB,
    and wipe encodings.pkl so the model is fully clean.
    Rector-only. Use before a fresh bulk enrollment session.
    """
    if current_user.role != 'rector':
        return "Unauthorized", 403

    from supabase_storage import list_dataset_students, delete_student_dataset

    cloud_folders = list_dataset_students()
    results = []
    failed = []

    for reg_num in cloud_folders:
        ok, msg = delete_student_dataset(reg_num)
        if ok:
            results.append(reg_num)
            # Reset DB flags so the student shows as un-enrolled
            s = Student.query.filter_by(registration_number=reg_num).first()
            if s:
                s.face_samples_count = 0
                s.face_encoded = False
        else:
            failed.append({'reg_num': reg_num, 'error': msg})

    db.session.commit()

    # Wipe encodings.pkl and in-memory index
    if os.path.exists(Config.ENCODINGS_FILE):
        os.remove(Config.ENCODINGS_FILE)
    face_module.index = face_module.index.__class__()

    return jsonify({
        'success': len(failed) == 0,
        'purged': results,
        'failed': failed,
        'message': f"Purged {len(results)} student(s). Model reset. Ready for fresh enrollment."
    })


@app.route('/admin/reset_encodings', methods=['GET', 'POST'])
@login_required
def reset_encodings():
    """
    Delete encodings.pkl and reset the in-memory index.
    Use after fixing the dataset, then trigger retrain from the dashboard.
    """
    if current_user.role != 'rector':
        return "Unauthorized", 403

    try:
        if os.path.exists(Config.ENCODINGS_FILE):
            os.remove(Config.ENCODINGS_FILE)
        face_module.index = face_module.index.__class__()
        return jsonify({'success': True, 'message': 'encodings.pkl deleted. Trigger retrain from dashboard.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


if __name__ == '__main__':
    init_database()
    print("[INFO] Starting SGGS Hostel Attendance System")
    print("[INFO] URL: http://127.0.0.1:5000")
    print("[INFO] Login: warden / warden123")
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)