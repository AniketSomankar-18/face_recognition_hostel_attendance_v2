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

# Senior AI Systems Engineer Design: 
# Using a unified search index for scalability.
class VectorSearchIndex:
    """
    A search index for face embeddings. 
    Can be easily swapped with FAISS for large-scale deployments.
    """
    def __init__(self, dimension=128):
        self.dimension = dimension
        self.vectors = []
        self.metadata = []

    def add(self, vector, meta):
        self.vectors.append(vector)
        self.metadata.append(meta)

    def search(self, query_vector, k=1, threshold=0.6):
        if not self.vectors:
            return []
        
        # Calculate Euclidean distances (Exact Search - O(N))
        # For >5000 users, swap this block with faiss.IndexFlatL2
        distances = np.linalg.norm(np.array(self.vectors) - query_vector, axis=1)
        results = []
        
        # Get top-k matches
        top_indices = np.argsort(distances)[:k]
        for idx in top_indices:
            dist = distances[idx]
            if dist < threshold:
                results.append({
                    'meta': self.metadata[idx],
                    'distance': float(dist),
                    'confidence': round((1 - dist) * 100, 2)
                })
        return results

class FaceRecognitionModule:
    def __init__(self, config):
        self.config = config
        self.dataset_dir = config.DATASET_DIR
        self.encodings_file = config.ENCODINGS_FILE
        self.tolerance = config.RECOGNITION_TOLERANCE
        self.index = VectorSearchIndex(dimension=128) # Default dlib dimension
        self._load_encodings()

    def _load_encodings(self):
        """Load pre-trained encodings from file into search index."""
        if os.path.exists(self.encodings_file):
            try:
                with open(self.encodings_file, 'rb') as f:
                    data = pickle.load(f)
                    encodings = data.get('encodings', [])
                    names = data.get('names', [])
                    
                    for enc, name in zip(encodings, names):
                        self.index.add(enc, {'reg_num': name})
                print(f"[INFO] Loaded {len(names)} identity embeddings into Search Index.")
            except Exception as e:
                print(f"[ERROR] Failed to load encodings: {e}")
        else:
            print("[INFO] No encodings file found. Running in Enrollment-only mode.")

    def train_model(self):
        """
        Enrollment Pipeline: identity representation from samples.
        AGGREGATION STRATEGY: Computed Centroid (Mean Vector)
        """
        if not FACE_RECOGNITION_AVAILABLE:
            return False, "Engine (dlib/face_recognition) not installed.", 0

        if not os.path.exists(self.dataset_dir):
            return False, "Dataset directory not found.", 0

        encodings = []
        names = []
        count = 0

        student_folders = [d for d in os.listdir(self.dataset_dir)
                           if os.path.isdir(os.path.join(self.dataset_dir, d))]

        for reg_num in student_folders:
            student_path = os.path.join(self.dataset_dir, reg_num)
            image_files = [f for f in os.listdir(student_path)
                           if f.lower().endswith(('.jpg', '.jpeg', '.png'))]

            current_student_samples = []
            for img_file in image_files[:10]: # Max 10 samples for efficiency
                img_path = os.path.join(student_path, img_file)
                try:
                    image = face_recognition.load_image_file(img_path)
                    face_encs = face_recognition.face_encodings(image)
                    if face_encs:
                        current_student_samples.append(face_encs[0])
                except Exception as e:
                    continue

            if current_student_samples:
                # Aggregate embeddings using Average (Centroid)
                avg_encoding = np.mean(current_student_samples, axis=0)
                encodings.append(avg_encoding)
                names.append(reg_num)
                count += 1

        if not encodings:
            return False, "No valid faces detected during enrollment.", 0

        # Persist Final Embeddings
        data = {'encodings': encodings, 'names': names}
        os.makedirs(os.path.dirname(self.encodings_file), exist_ok=True)
        with open(self.encodings_file, 'wb') as f:
            pickle.dump(data, f)

        # Refresh Index
        self.index = VectorSearchIndex()
        for enc, name in zip(encodings, names):
            self.index.add(enc, {'reg_num': name})

        return True, f"Successfully enrolled {count} identities.", count

    def recognize_face(self, frame):
        """
        Recognition Pipeline: Real-time search.
        Inference -> Vector Search -> Match
        """
        if not FACE_RECOGNITION_AVAILABLE or not self.index.vectors:
            return []

        # Optimization: Pre-process frame (Resize & RGB)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        small_frame = cv2.resize(rgb_frame, (0, 0), fx=0.5, fy=0.5)

        # Detect
        face_locations = face_recognition.face_locations(small_frame, model='hog')
        if not face_locations:
            return []

        # Extract
        face_encodings = face_recognition.face_encodings(small_frame, face_locations)

        results = []
        for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
            # Scalable Search Index Lookup
            matches = self.index.search(face_encoding, k=1, threshold=self.tolerance)
            
            if matches:
                match = matches[0]
                res = {
                    'name': match['meta']['reg_num'],
                    'reg_num': match['meta']['reg_num'],
                    'confidence': match['confidence'],
                    'location': (top*2, right*2, bottom*2, left*2)
                }
            else:
                res = {
                    'name': "Unknown",
                    'reg_num': None,
                    'confidence': 0.0,
                    'location': (top*2, right*2, bottom*2, left*2)
                }
            results.append(res)

        return results

    def capture_faces(self, registration_number, required_count=10):
        """
        Capture facial identity samples without GUI.
        Note: On Cloud servers, this will likely fail due to lack of local camera.
        The Raspberry Pi usually handles this via the /api/pi/frame endpoint.
        """
        save_dir = os.path.join(self.dataset_dir, registration_number)
        os.makedirs(save_dir, exist_ok=True)

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return False, "Camera access failed (No local sensor detected).", 0

        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        captured = 0
        frame_idx = 0

        # Limited attempts to prevent infinite loop on headless systems
        max_attempts = required_count * 10 
        attempts = 0

        while captured < required_count and attempts < max_attempts:
            ret, frame = cap.read()
            if not ret: break
            
            attempts += 1
            if attempts % 2 == 0: 
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(gray, 1.3, 5, minSize=(100, 100))
                
                for (x, y, w, h) in faces:
                    if captured >= required_count: break
                    face_img = frame[y:y+h, x:x+w]
                    cv2.imwrite(os.path.join(save_dir, f"{captured}.jpg"), face_img)
                    captured += 1
            
        cap.release()
        return (captured > 0), f"Captured {captured} samples.", captured

    def is_model_trained(self):
        """Check if the search index contains any identity embeddings."""
        return len(self.index.vectors) > 0

    def get_student_count_in_dataset(self):
        """Count unique student identity folders in the dataset directory."""
        if not os.path.exists(self.dataset_dir):
            return 0
        return len([d for d in os.listdir(self.dataset_dir) 
                   if os.path.isdir(os.path.join(self.dataset_dir, d))])

    def get_face_image_count(self, registration_number):
        """Get the count of identity samples for a specific student."""
        path = os.path.join(self.dataset_dir, registration_number)
        if not os.path.exists(path):
            return 0
        return len([f for f in os.listdir(path) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])

    def draw_recognition_results(self, frame, results, student_map):
        """Draw boxes and labels on the frame for visualization."""
        for res in results:
            top, right, bottom, left = res['location']
            name = res['name']
            confidence = res['confidence']
            
            # Use student_map (dict of registration_number to name) if available
            display_name = student_map.get(name, name) if student_map else name
            color = (0, 255, 0) if name != "Unknown" else (0, 0, 255)

            # Draw Box
            cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
            # Draw Label
            cv2.rectangle(frame, (left, bottom - 35), (right, bottom), color, cv2.FILLED)
            label = f"{display_name} ({confidence}%)"
            cv2.putText(frame, label, (left + 6, bottom - 6), 
                        cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 1)
        return frame
