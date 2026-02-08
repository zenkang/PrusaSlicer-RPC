import glob
import redis
import json
import os
import time
import httpx
import uuid

from quotation_engine import QuotationEngine

# Configuration
# REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
# r = redis.Redis(host=REDIS_HOST, port=6379, db=0)

# NEW: Cloud URL Support
REDIS_URL = os.getenv("REDIS_URL")

if REDIS_URL:
    # Handles password, SSL, and port automatically
    r = redis.from_url(REDIS_URL)
else:
    # Local fallback
    r = redis.Redis(host="localhost", port=6379, db=0)

# Helper: Reimplementing the download logic from your old app.py
def download_file(url):
    try:
        path = url.split('?')[0]
        ext = path.split('.')[-1] if '.' in path else 'stl'
        filename = f"temp/{str(uuid.uuid4())}.{ext}"
        os.makedirs("temp", exist_ok=True)
        
        with httpx.Client() as client:
            resp = client.get(url, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
            with open(filename, 'wb') as f:
                f.write(resp.content)
        return filename
    except Exception as e:
        print(f"Download failed: {e}")
        return None

def main():
    print("Worker started. Waiting for jobs...")
    
    # Initialize your Engine once (saves startup time!)
    engine = QuotationEngine()

    while True:
        # 1. Wait for a job (Blocking Pop)
        # This will pause execution here until Redis has data
        _, job_json = r.blpop("print_jobs")
        
        job = json.loads(job_json)
        job_id = job['id']
        print(f"Processing Job {job_id}...")

        # Update status to "processing"
        r.set(f"status:{job_id}", "processing", ex=86400)

        try:
            # 2. Download
            file_path = download_file(job['download_url'])
            if not file_path:
                raise Exception("Failed to download file")

            # 3. Process (Your heavy logic)
            # Note: We convert string numbers to proper types if needed
            result = engine.generate_quotation(
                input_file=file_path,
                material=job['material'],
                layer_height=float(job.get('layer_height', 0.2)),
                infill=int(job.get('infill', 15)),
                rush_order=job.get('rush', False),
                job_id=job_id
            )

            if not result or not result.get("success"):
                error_detail = result.get("error", "Unknown error") if result else "Failed to generate quotation"
                raise Exception(f"Quotation generation failed: {error_detail}")

            # 4. Save Result
            # Store result in Redis under "result:{id}"
            r.set(f"result:{job_id}", json.dumps(result), ex=86400)
            print(f"Job {job_id} completed!")

        except Exception as e:
            print(f"Job {job_id} failed: {e}")
            error_data = {"success": False, "error": str(e)}
            r.set(f"result:{job_id}", json.dumps(error_data), ex=86400)
        
        finally:
            print(f"🧹 Cleaning up artifacts for {job_id}...")
            
            # 1. Remove the main downloaded file
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError as e:
                    print(f"Error deleting input file: {e}")

            # 2. Remove any intermediate files (oriented stl, gcode, etc.)
            # This looks for any file in 'temp/' that contains the job_id
            for f in glob.glob(f"temp/*{job_id}*"):
                try:
                    os.remove(f)
                except OSError as e:
                    print(f"Error deleting artifact {f}: {e}")

if __name__ == "__main__":
    main()