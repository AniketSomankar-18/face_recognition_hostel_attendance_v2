import os
import glob

template_dir = '/home/koanoir/Desktop/Projects/02_showcase/face_recognition_hostel_attendance_v2/templates'

for filepath in glob.glob(os.path.join(template_dir, '*.html')):
    with open(filepath, 'r') as f:
        content = f.read()
    
    if 'material-symbols-outlined' in content:
        new_content = content.replace('material-symbols-outlined', 'material-symbols-rounded')
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"Fixed icons in {os.path.basename(filepath)}")
