from typing import Tuple
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import uuid
import os
from quotation_engine import QuotationEngine
import shutil

os.makedirs("temp", exist_ok=True)

app = FastAPI()

class QuotationResponse(BaseModel):
    price : float
    filename : str
    material : str
    rush : bool
    layer_height : str
    infill : int


class QuotationRequest(BaseModel):
    download_url: str
    filename: str
    material: str
    layer_height: str
    infill: int
    rush: bool




async def download_file(url) -> Tuple[bool, str]: 
    try:
        # Extract extension from URL path (before query parameters)
        path = url.split('?')[0]  # Remove query parameters
        ext = path.split('.')[-1] if '.' in path else 'stl'
        tmp = f"temp/{str(uuid.uuid4())}.{ext}"
        
        # Make a GET request to the URL
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30.0, follow_redirects=True)
            # Raise an exception if the request was unsuccessful
            response.raise_for_status()

            # Open the file in binary write mode and save the content
            with open(tmp, 'wb') as f:
                f.write(response.content)
        
        print(f"Successfully downloaded {tmp}")
        return True, tmp

    except httpx.HTTPStatusError as e:
        print(f"Error during request: {e.response.status_code} {e.response.reason_phrase}")
        return False, ""
    except httpx.RequestError as e:
        print(f"An error occurred while trying to request {url}: {e}")
        return False, ""
    except Exception as e:
        print(f"Unexpected error downloading file: {e}")
        return False, ""


@app.get("/")
async def root():
    return {"message": "3D Printing Quotation Engine API", "version": "1.0"}

@app.get("/health")
async def health_check():
    """Health check endpoint for AWS load balancers"""
    return {"status": "healthy", "service": "quotation-engine"}

@app.post("/quote/")
async def generate_quote(quotation_request: QuotationRequest):

    response = await download_file(quotation_request.download_url)
    if not response[0]:
        raise HTTPException(status_code=400, detail="Failed to download file from URL")

    file_path = response[1]
    
    # Verify file exists and has content
    if not os.path.exists(file_path):
        raise HTTPException(status_code=500, detail="Downloaded file not found")
    
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        raise HTTPException(status_code=500, detail="Downloaded file is empty")
    
    print(f"File downloaded successfully: {file_path} ({file_size} bytes)")
    
    try:
        engine = QuotationEngine()
        result = engine.generate_quotation(
            input_file=file_path,
            material=quotation_request.material,
            layer_height=float(quotation_request.layer_height),
            infill=quotation_request.infill,
            rush_order=quotation_request.rush
        )
        
        if not result or not result.get("success"):
            error_detail = result.get("error", "Unknown error") if result else "Failed to generate quotation"
            raise HTTPException(status_code=500, detail=error_detail)
        
        price = result.get("summary", {}).get("total_cost", 0.0)
        
        return QuotationResponse(
            price=price,
            filename=quotation_request.filename,
            material=quotation_request.material,
            rush=quotation_request.rush,
            layer_height=quotation_request.layer_height,
            infill=quotation_request.infill
        )
    finally:
        # Clean up file in finally block to ensure it's always deleted
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Warning: Could not delete temporary file {file_path}: {e}")
