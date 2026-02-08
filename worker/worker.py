import glob
import redis
import json
import os
import time
import httpx
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import uuid

from quotation_engine import QuotationEngine

def download_file(url):
    try:
        path = url.split('?')[0]
        ext = path.split('.')[-1] if '.' in path else 'stl'
        # Use absolute path to ensure we write to the writable temp dir
        filename = f"/app/temp/{str(uuid.uuid4())}.{ext}"
        
        with httpx.Client() as client:
            resp = client.get(url, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
            with open(filename, 'wb') as f:
                f.write(resp.content)
        return filename
    except Exception as e:
        print(f"Download failed: {e}")
        return None

def start_health_check_server():
    """
    Starts a dummy HTTP server on port 7860 to satisfy Hugging Face's health check.
    """
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Worker is running!")
        def log_message(self, format, *args):
            pass # Suppress logs

    server = HTTPServer(('0.0.0.0', 7860), HealthHandler)
    print("🏥 Health check server listening on port 7860")
    server.serve_forever()

def main():
    # 1. Start Health Check server FIRST
    # This prevents "Launch timed out" errors if Redis fails
    t = threading.Thread(target=start_health_check_server, daemon=True)
    t.start()
    
    # 2. Connect to Redis (Safely)
    REDIS_URL = os.getenv("REDIS_URL")
    print(f"🔌 Connecting to Redis...")
    
    r = None
    while r is None:
        try:
            if REDIS_URL:
                r = redis.from_url(REDIS_URL)
            else:
                r = redis.Redis(host="localhost", port=6379, db=0)
            r.ping() # Test connection
            print("✅ Redis Connected!")
        except Exception as e:
            print(f"❌ Redis Connection Failed: {e}")
            print("Retrying in 5 seconds...")
            time.sleep(5) # Wait before retrying to avoid log spam

    # 3. Initialize Engine
    engine = QuotationEngine()
    print("Worker started. Waiting for jobs...")

    while True:
        try:
            # Blocking pop
            _, job_json = r.blpop("print_jobs")
            job = json.loads(job_json)
            job_id = job['id']
            print(f"Processing Job {job_id}...")

            r.set(f"status:{job_id}", "processing", ex=86400)
            
            file_path = None
            try:
                # Download
                file_path = download_file(job['download_url'])
                if not file_path:
                    raise Exception("Failed to download file")

                # Slice
                result = engine.generate_quotation(
                    input_file=file_path,
                    material=job['material'],
                    layer_height=float(job.get('layer_height', 0.2)),
                    infill=int(job.get('infill', 15)),
                    rush_order=job.get('rush', False),
                    job_id=job_id
                )

                if not result or not result.get("success"):
                     raise Exception(result.get("error", "Generation failed"))

                r.set(f"result:{job_id}", json.dumps(result), ex=86400)
                r.set(f"status:{job_id}", "completed", ex=86400)
                print(f"✅ Job {job_id} completed!")

            except Exception as e:
                print(f"❌ Job {job_id} failed: {e}")
                error_data = {"success": False, "error": str(e)}
                r.set(f"result:{job_id}", json.dumps(error_data), ex=86400)
                r.set(f"status:{job_id}", "failed", ex=86400)

            finally:
                # Cleanup
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except: pass
                
                # Clean up intermediate files using glob
                # Ensure we target the specific temp dir
                for f in glob.glob(f"/app/temp/*{job_id}*"):
                    try:
                        os.remove(f)
                    except: pass

        except Exception as main_e:
            print(f"Critical Worker Loop Error: {main_e}")
            time.sleep(1)

if __name__ == "__main__":
    main()