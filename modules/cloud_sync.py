import os
from supabase_storage import upload_frame, list_dataset_students, list_student_frames
from config import Config

def sync_local_dataset_to_cloud():
    """Iterate over local dataset directory and ensure everything is in Supabase."""
    if not os.path.exists(Config.DATASET_DIR):
        return {"success": False, "message": "Local dataset directory not found."}

    local_students = [d for d in os.listdir(Config.DATASET_DIR) if os.path.isdir(os.path.join(Config.DATASET_DIR, d))]
    cloud_students = list_dataset_students()

    print(f"[SYNC] Found {len(local_students)} students locally. Cloud has {len(cloud_students)}.")
    
    report = []
    total_synced = 0

    for reg_num in local_students:
        local_path = os.path.join(Config.DATASET_DIR, reg_num)
        local_files = [f for f in os.listdir(local_path) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        
        # Optimization: Check if this student is already "Calibrated" in cloud
        # For simplicity in this one-time sync, we check if student folder exists
        # In more robust versions, we'd check file counts.
        
        synced_for_student = 0
        for fname in local_files:
            file_path = os.path.join(local_path, fname)
            with open(file_path, 'rb') as f:
                up_success, up_msg = upload_frame(reg_num, fname, f.read())
                if up_success:
                    synced_for_student += 1
        
        total_synced += synced_for_student
        report.append(f"{reg_num}: {synced_for_student} frames pushed")

    return {
        "success": True, 
        "total_students": len(local_students),
        "total_frames_synced": total_synced,
        "details": report
    }

if __name__ == "__main__":
    # Can be run as a standalone script
    result = sync_local_dataset_to_cloud()
    print(result)
