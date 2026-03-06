import os
import pickle
import cv2
import numpy as np
from datetime import datetime

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    print("[WARNING] face_recognition not installed. Using mock mode.")


class FaceRecognitionModule:
    def __init__(self, config):
        self.config = config
        self.dataset_dir = config.DATASET_DIR
        self.encodings_file = config.ENCODINGS_FILE
        self.tolerance = config.RECOGNITION_TOLERANCE
        self.known_encodings = []
        self.known_names = []
        self._load_encodings()

    def _load_encodings(self):
        """Load pre-trained encodings from file."""
        if os.path.exists(self.encodings_file):
            try:
                with open(self.encodings_file, 'rb') as f:
                    data = pickle.load(f)
                    self.known_encodings = data.get('encodings', [])
                    self.known_names = data.get('names', [])
                print(f"[INFO] Loaded {len(self.known_names)} face encodings.")
            except Exception as e:
                print(f"[ERROR] Failed to load encodings: {e}")
                self.known_encodings = []
                self.known_names = []
        else:
            print("[INFO] No encodings file found. Please train the model first.")

    def train_model(self):
        """
        Scan dataset directory, encode all faces, and save to encodings file.
        Returns: (success: bool, message: str, count: int)
        """
        if not FACE_RECOGNITION_AVAILABLE:
            return False, "face_recognition library not installed.", 0

        encodings = []
        names = []
        count = 0
        errors = []

        if not os.path.exists(self.dataset_dir):
            return False, "Dataset directory not found.", 0

        student_folders = [d for d in os.listdir(self.dataset_dir)
                           if os.path.isdir(os.path.join(self.dataset_dir, d))]

        if not student_folders:
            return False, "No student face data found in dataset.", 0

        for reg_num in student_folders:
            student_path = os.path.join(self.dataset_dir, reg_num)
            image_files = [f for f in os.listdir(student_path)
                           if f.lower().endswith(('.jpg', '.jpeg', '.png'))]

            student_encodings = []
            for img_file in image_files:
                img_path = os.path.join(student_path, img_file)
                try:
                    image = face_recognition.load_image_file(img_path)
                    face_encs = face_recognition.face_encodings(image)
                    if face_encs:
                        student_encodings.append(face_encs[0])
                except Exception as e:
                    errors.append(f"{reg_num}/{img_file}: {e}")

            if student_encodings:
                # Use average encoding for more stability
                avg_encoding = np.mean(student_encodings, axis=0)
                encodings.append(avg_encoding)
                names.append(reg_num)
                count += 1
                print(f"[INFO] Encoded {reg_num} with {len(student_encodings)} images.")

        if not encodings:
            return False, "No valid face encodings could be generated.", 0

        # Save to file
        data = {'encodings': encodings, 'names': names}
        os.makedirs(os.path.dirname(self.encodings_file), exist_ok=True)
        with open(self.encodings_file, 'wb') as f:
            pickle.dump(data, f)

        # Reload
        self.known_encodings = encodings
        self.known_names = names

        msg = f"Training complete. Encoded {count} students."
        if errors:
            msg += f" ({len(errors)} errors skipped)"
        return True, msg, count

    def recognize_face(self, frame):
        """
        Detect and recognize faces in a given BGR frame.
        Returns list of dicts: [{name, reg_num, confidence, location}]
        """
        if not FACE_RECOGNITION_AVAILABLE:
            return []

        if not self.known_encodings:
            return []

        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Resize for faster processing
        small_frame = cv2.resize(rgb_frame, (0, 0), fx=0.5, fy=0.5)

        face_locations = face_recognition.face_locations(small_frame, model='hog')
        face_encodings = face_recognition.face_encodings(small_frame, face_locations)

        results = []
        for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
            # Scale back
            top *= 2
            right *= 2
            bottom *= 2
            left *= 2

            matches = face_recognition.compare_faces(
                self.known_encodings, face_encoding, tolerance=self.tolerance
            )
            face_distances = face_recognition.face_distance(self.known_encodings, face_encoding)

            name = "Unknown"
            reg_num = None
            confidence = 0.0

            if True in matches:
                best_match_index = np.argmin(face_distances)
                if matches[best_match_index]:
                    name = self.known_names[best_match_index]
                    reg_num = name
                    confidence = round((1 - face_distances[best_match_index]) * 100, 2)

            results.append({
                'name': name,
                'reg_num': reg_num,
                'confidence': confidence,
                'location': (top, right, bottom, left)
            })

        return results

    def capture_faces(self, registration_number, required_count=20):
        """
        Open webcam, detect face, capture `required_count` images.
        Saves to dataset/<registration_number>/
        Returns: (success: bool, message: str, captured: int)
        """
        save_dir = os.path.join(self.dataset_dir, registration_number)
        os.makedirs(save_dir, exist_ok=True)

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return False, "Could not open webcam.", 0

        # Load face detector
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )

        captured = 0
        frame_count = 0

        print(f"[INFO] Starting face capture for {registration_number}...")
        print("[INFO] Press 'q' to quit early.")

        while captured < required_count:
            ret, frame = cap.read()
            if not ret:
                break

            frame_count += 1
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5, minSize=(80, 80))

            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

                # Capture every 3rd frame to get variety
                if frame_count % 3 == 0 and captured < required_count:
                    face_img = frame[y:y + h, x:x + w]
                    img_path = os.path.join(save_dir, f"{captured + 1}.jpg")
                    cv2.imwrite(img_path, face_img)
                    captured += 1

            # Progress
            cv2.putText(frame, f"Captured: {captured}/{required_count}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.putText(frame, "Press Q to quit",
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
            cv2.imshow(f"Face Capture - {registration_number}", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()

        if captured == 0:
            return False, "No face detected. Please try again in good lighting.", 0

        return True, f"Successfully captured {captured} face images.", captured

    def draw_recognition_results(self, frame, results, student_map):
        """
        Draw bounding boxes and names on frame.
        student_map: {reg_num: student_name}
        """
        for result in results:
            top, right, bottom, left = result['location']
            reg_num = result['reg_num']
            confidence = result['confidence']

            if reg_num and reg_num in student_map:
                display_name = student_map[reg_num]
                color = (0, 255, 0)  # Green for known
                label = f"{display_name} ({confidence:.1f}%)"
            else:
                display_name = "Unknown"
                color = (0, 0, 255)  # Red for unknown
                label = "Unknown"

            cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
            cv2.rectangle(frame, (left, bottom - 35), (right, bottom), color, cv2.FILLED)
            cv2.putText(frame, label, (left + 6, bottom - 6),
                        cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 1)

        return frame

    def is_model_trained(self):
        return os.path.exists(self.encodings_file) and len(self.known_encodings) > 0

    def get_student_count_in_dataset(self):
        if not os.path.exists(self.dataset_dir):
            return 0
        return len([d for d in os.listdir(self.dataset_dir)
                    if os.path.isdir(os.path.join(self.dataset_dir, d))])

    def get_face_image_count(self, registration_number):
        folder = os.path.join(self.dataset_dir, registration_number)
        if not os.path.exists(folder):
            return 0
        return len([f for f in os.listdir(folder)
                    if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
