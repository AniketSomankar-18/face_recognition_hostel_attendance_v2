# 🎓 Face Recognition Hostel Attendance System

An AI-powered hostel night attendance system using **face recognition** with a modern dark-themed web dashboard.

---

## 📋 Features

- ✅ **Face Recognition Attendance** using `dlib` / `face_recognition`
- 📸 **Webcam Face Capture** (20 images per student via browser)
- 🕐 **Attendance Rules**: Present (8:30–9:00 PM), Late (9:00–9:30 PM), Absent (auto)
- 📅 **Leave Management** with approval workflow
- 📊 **Excel Reports** with color-coded attendance grid
- 📄 **PDF Absent Report** with parent contact info
- 📆 **Attendance Calendar** per student (green/red/yellow/blue)
- 🔒 **Secure Login** with Flask-Login + password hashing
- ⏰ **Auto Absent** via APScheduler at 9:30 PM
- 🌙 **Modern Dark Theme UI**

---

## 🗂️ Project Structure

```
face_recognition_hostel_attendance/
├── app.py                      # Main Flask application
├── config.py                   # Configuration settings
├── models.py                   # SQLAlchemy DB models
├── requirements.txt
├── README.md
├── modules/
│   ├── face_recognition_module.py   # Face encoding & recognition
│   ├── attendance.py                # Attendance logic
│   └── reports.py                   # Excel & PDF reports
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── students.html
│   ├── register.html
│   ├── capture_face.html
│   ├── attendance.html
│   ├── leave_management.html
│   ├── history.html
│   └── absent_list.html
├── static/
│   ├── css/style.css
│   └── js/camera.js
├── dataset/                    # Face images (auto-created)
├── models/                     # Trained encodings (auto-created)
└── database/                   # SQLite DB (auto-created)
```

---

## ⚙️ Installation

### Step 1: System Requirements

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake libopenblas-dev liblapack-dev \
    libx11-dev libgtk-3-dev python3-dev python3-pip libboost-python-dev
```

**Windows:** Install [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) and [CMake](https://cmake.org/download/).

### Step 2: Create Virtual Environment
```bash
python -m venv venv

# Linux/Mac
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

> ⚠️ `dlib` compilation can take 5–10 minutes. Be patient.

### Step 4: Run the Application
```bash
python app.py
```

Open: **http://127.0.0.1:5000**

---

## 🔑 Default Login

| Field    | Value      |
|----------|------------|
| Username | `warden`   |
| Password | `warden123`|

---

## 🔄 Workflow

### 1. Register Students
- Go to **Students → Register Student**
- Fill in all student details
- After registration, you're redirected to **Face Capture**

### 2. Capture Face Images
- The browser opens your webcam automatically
- Click **"Start Auto Capture"**
- The system captures **20 face images** and saves them to `dataset/<reg_num>/`
- Ensure good lighting and clear face visibility

### 3. Train the Model
- Go to **Dashboard → Train Model**
- The system encodes all student faces and saves to `models/encodings.pkl`
- Training takes ~30 seconds for 10 students

### 4. Mark Attendance
- Go to **Mark Attendance**
- Click **"Start"** to activate webcam
- The system automatically recognizes faces and marks attendance
- You can also **manually mark** using the sidebar form

### 5. View Reports
- **Dashboard**: Today's summary with progress bars
- **Absent List**: Download Excel / PDF reports
- **Student View**: Calendar-based attendance history

---

## ⏰ Attendance Window

| Time       | Status  |
|------------|---------|
| Before 8:30 PM | Closed  |
| 8:30 – 9:00 PM | ✅ Present |
| 9:00 – 9:30 PM | 🕐 Late |
| After 9:30 PM  | ❌ Absent (auto) |
| On leave       | 🔵 Leave |

> **Testing Mode**: Window is open 24 hours for development.
> Set `TESTING_MODE = False` in `config.py` for production.

---

## 📊 Reports

### Excel Report
- Color-coded: P=Green, L=Yellow, A=Red, Lv=Blue
- Monthly view with attendance percentage
- Download from **Dashboard → Excel** or **Absent List → Download Excel**

### PDF Report
- Lists absent students with room numbers and parent contacts
- Download from **Dashboard → PDF** or **Absent List → Download PDF**

---

## 🗃️ Database

SQLite database is stored at `database/hostel.db`.

Tables:
- `users` – Warden login accounts
- `students` – Student profiles
- `attendance` – Daily attendance records
- `leaves` – Leave management

---

## 🔧 Configuration (`config.py`)

```python
TESTING_MODE = True         # False for production (enforces time window)
RECOGNITION_TOLERANCE = 0.5 # Lower = stricter matching
FACE_IMAGES_REQUIRED = 20   # Images per student for training
```

---

## 🚨 Troubleshooting

| Problem | Solution |
|---------|----------|
| `dlib` install fails | Install cmake & build tools, use Python 3.8–3.10 |
| Camera not working | Allow browser camera permissions |
| "No face detected" | Better lighting, face closer to camera |
| Low recognition accuracy | Re-capture faces, re-train model |
| Port 5000 in use | `python app.py` uses port 5000; kill other process or change port |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3, Flask, SQLAlchemy |
| Database | SQLite |
| AI/ML | face_recognition, dlib, OpenCV |
| Frontend | HTML5, CSS3, JavaScript, Jinja2 |
| Reports | Pandas, openpyxl, ReportLab |
| Scheduler | APScheduler |
| Auth | Flask-Login, Werkzeug |

---

## 📜 License

This project is developed for educational purposes as a college project.

---

*Built with ❤️ for hostel management*
