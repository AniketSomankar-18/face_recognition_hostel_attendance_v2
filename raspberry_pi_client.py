import cv2
import requests
import base64
import time
import os

# Deployment Configuration: Change this to your public Cloud URL or env
SERVER_URL = os.environ.get('SERVER_URL', "http://localhost:5000")
USERNAME = "warden"
PASSWORD = "warden123"

def main():
    print("="*60)
    print("   HOSTEL ATTENDANCE SYSTEM - EDGE CAMERA NODE")
    print("="*60)
    
    COOLDOWN = 1.5
    POLLING_DELAY = 3.0
    camera_is_on = False
    cap = None
    backoff_count = 0
    
    print("\n[READY] Listening for Dashboard commands. Feel free to minimize this window.\n")

    try:
        while True:
            # 1. State Polling Phase
            try:
                state_resp = requests.get(f"{SERVER_URL}/api/camera/state", timeout=5)
                
                if state_resp.status_code != 200:
                    print(f"[SERVER] Error fetching state. Status: {state_resp.status_code}")
                    time.sleep(POLLING_DELAY)
                    continue

                state_data = state_resp.json()
                is_active = state_data.get('active', False)
                backoff_count = 0 # Reset on success
            except Exception as e:
                backoff_count = min(backoff_count + 1, 10)
                wait_time = POLLING_DELAY * (1.5 ** backoff_count)
                print(f"[NETWORK] Cannot reach server. Retrying in {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            # 2. State Transition Management
            if is_active and not camera_is_on:
                print("[STATE] ACTIVATED - Opening Camera Sensor...")
                cap = cv2.VideoCapture(0)
                if not cap.isOpened():
                    print("[HARDWARE] ERROR: Camera not found on this device!")
                    is_active = False # Force standby
                else:
                    camera_is_on = True
                    print("[STATE] Camera Live. Streaming faces to Cloud...")
                
            elif not is_active and camera_is_on:
                print("[STATE] STANDBY - Releasing Camera Sensor.")
                if cap:
                    cap.release()
                camera_is_on = False

            # 3. Execution Phase
            if is_active and camera_is_on:
                ret, frame = cap.read()
                if ret:
                    ret2, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if ret2:
                        encoded = base64.b64encode(buffer).decode('utf-8')
                        data_uri = f"data:image/jpeg;base64,{encoded}"
                        
                        try:
                            resp = requests.post(f"{SERVER_URL}/api/recognize_frame",
                                               json={"image": data_uri},
                                               timeout=8)
                            
                            if resp.status_code == 200:
                                result = resp.json()
                                f_count = result.get("faces_count", 0)
                                if f_count > 0:
                                    # Output recognized names for local debugging on Pi
                                    names = [r['name'] for r in result.get('results', []) if r.get('name')]
                                    print(f"[MATCH] Found {f_count} faces: {', '.join(names)}")
                            else:
                                print(f"[SERVER] Error uploading frame. Status: {resp.status_code}")
                        except Exception as e:
                            print(f"[UPLOAD] Failed to send frame: {e}")
                            
                time.sleep(COOLDOWN)
            else:
                time.sleep(POLLING_DELAY)
            
    except KeyboardInterrupt:
        print("\n[STOP] Shutting down Edge Client.")
    finally:
        if cap:
            cap.release()

if __name__ == "__main__":
    main()
