"""
3D Printing Quotation Engine API
Advanced quotation system with STEP/STL conversion, mesh validation, smart orientation, slicing, and cost calculation
Compatible with Next.js web applications through REST API
"""

import subprocess
import os
import uuid
import re
import time
import shutil
import json
from datetime import datetime
import math
from typing import Dict, Optional, Tuple, Any
import trimesh
from look import look

# === CONFIGURATION ===
CONFIG = {
    "paths": {
        "prusaslicer": "prusaslicer",
        "tweaker3": "tweaker3",
        "config_base": "./cfg.ini",
    },
    "printing": {
        "timeout": 300,  # 5 minutes max processing time
        "supported_formats": [".stl", ".STL", ".STEP", ".step", ".stp", ".STP"],
        "default_layer_height": 0.2,
        "default_infill": 15
    },
    "pricing": {
        "base_rate_per_hour": 3.0,  # $3 per print hour
        "material_multipliers": {
            "PLA": 0.8,
            "PETG": 1.0,
            "ABS": 1.2
        },
        "rush_multiplier": 1.2  # 20% extra for rush orders
    }
}

class QuotationEngine:
    """Advanced 3D printing quotation engine with STEP conversion, mesh validation, orientation, and pricing"""
    
    def __init__(self, config: Dict = None):
        self.config = config or CONFIG
        # self.ensure_directories()
    
    def ensure_directories(self):
        """Create necessary directories"""
        for dir_name in ["output_dir", "upload_dir"]:
            dir_path = self.config["paths"][dir_name]
            os.makedirs(dir_path, exist_ok=True)
    
    def validate_model(self, file_path: str) -> Tuple[bool, str]:
        """Validate uploaded 3D model file"""
        if not os.path.exists(file_path):
            return False, "File not found"
        
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in self.config["printing"]["supported_formats"]:
            return False, f"Unsupported format {file_ext}. Supported: {self.config['printing']['supported_formats']}"
        
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return False, "File is empty"
        
        return True, "Valid"
    
    def convert_step_to_stl(self, step_file: str, job_id: str) -> Tuple[Optional[str], str]:
        """
        Convert STEP/STP file to STL using PrusaSlicer
        Returns: (stl_path, message)
        """
        print(f"🔄 Converting STEP file to STL for job {job_id}")
        
        stl_file = os.path.join("temp", f"{job_id}.stl")
        
        cmd = [
            self.config["paths"]["prusaslicer"],
            "--export-stl",
            "--output", stl_file,
            step_file
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.config["printing"]["timeout"])
            
            if result.returncode != 0:
                error_msg = f"STEP conversion failed: {result.stderr}"
                # print(f"❌ {error_msg}")
                return None, error_msg
            
            if not os.path.exists(stl_file) or os.path.getsize(stl_file) == 0:
                return None, "STEP conversion produced empty file"
            
            # print(f"✅ STEP conversion successful")
            return stl_file, "Conversion successful"
            
        except Exception as e:
            error_msg = f"STEP conversion error: {str(e)}"
            # print(f"❌ {error_msg}")
            return None, error_msg
    
    def check_mesh_validity(self, stl_file: str) -> Tuple[bool, str]:
        """
        Check if STL mesh is valid (watertight, consistent winding, positive volume)
        Returns: (is_valid, message)
        """
        # print(f"🔍 Checking mesh validity...")
        
        try:
            mesh = trimesh.load_mesh(stl_file)
            
            is_winding_consistent = mesh.is_winding_consistent
            is_watertight = mesh.is_watertight
            has_volume = mesh.volume > 0
            
            if is_winding_consistent and is_watertight and has_volume:
                # print(f"✅ Mesh is valid (volume: {mesh.volume:.2f} mm³)")
                return True, "Mesh is valid"
            else:
                issues = []
                if not is_winding_consistent:
                    issues.append("inconsistent winding")
                if not is_watertight:
                    issues.append("not watertight")
                if not has_volume:
                    issues.append("no volume")
                
                error_msg = f"Mesh validation failed: {', '.join(issues)}"
                # print(f"❌ {error_msg}")
                return False, error_msg
                
        except Exception as e:
            error_msg = f"Mesh validation error: {str(e)}"
            # print(f"❌ {error_msg}")
            return False, error_msg
    
    def orient_stl_with_tweaker3(self, stl_file: str, job_id: str) -> Tuple[Optional[str], str, Dict]:
        """
        Orient STL file using Tweaker3 for optimal printing
        Returns: (oriented_stl_path, message, orientation_data)
        """
        # print(f"🔄 Orienting STL with Tweaker3 for job {job_id}")
        
        # Tweaker3 modifies the file in place, so we'll work with a copy
        oriented_stl = os.path.join("temp", f"{job_id}_oriented.stl")
        shutil.copy2(stl_file, oriented_stl)
        
        cmd = [
            self.config["paths"]["tweaker3"],
            "-i", oriented_stl,
            "-o", oriented_stl,
            "-vb",
            "-x",
            "-min", "sur" 
        ]
        
        orientation_data = {
            "complexity": "medium",
            "unprintability": 0,
            "tweaker3_output": ""
        }
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.config["printing"]["timeout"])
            
            # Store output for analysis
            orientation_data["tweaker3_output"] = result.stdout
            
            # Parse complexity from Tweaker3 output
            complexity = self.parse_tweaker3_complexity(result.stdout)
            orientation_data["complexity"] = complexity
            
            if result.returncode != 0:
                error_msg = f"Tweaker3 orientation failed: {result.stderr}"
                # print(f"⚠️ {error_msg}, using original orientation")
                return stl_file, "Orientation failed, using original", orientation_data
            
            # print(f"✅ Orientation successful (Complexity: {complexity})")
            return oriented_stl, "Orientation successful", orientation_data
            
        except Exception as e:
            error_msg = f"Orientation error: {str(e)}"
            # print(f"⚠️ {error_msg}, using original orientation")
            return stl_file, f"Orientation error, using original", orientation_data
    
    def parse_tweaker3_complexity(self, tweaker_output: str) -> str:
        """
        Parse Tweaker3 output to determine model complexity
        Based on unprintability score or support volume
        Returns: "low", "medium", or "high"
        """
        try:
            # Look for unprintability score in Tweaker3 output
            unprintability_match = re.search(r'Unprintability:\s*([\d.]+)', tweaker_output)
            if unprintability_match:
                unprintability = float(unprintability_match.group(1))
                
                # Classify based on unprintability score
                if unprintability < 5:
                    return "low"
                elif unprintability < 15:
                    return "medium"
                else:
                    return "high"
            
            # Look for alternative indicators (support volume, overhang area, etc.)
            support_match = re.search(r'Support.*?([\d.]+)%', tweaker_output, re.IGNORECASE)
            if support_match:
                support_pct = float(support_match.group(1))
                if support_pct < 10:
                    return "low"
                elif support_pct < 25:
                    return "medium"
                else:
                    return "high"
            
            # Default to medium complexity if no indicators found
            return "medium"
            
        except Exception as e:
            # print(f"⚠️ Could not parse complexity from Tweaker3: {e}")
            return "medium"
    
    def slice_model(self, stl_path: str, job_id: str, material: str = "PLA", 
                    layer_height: float = 0.2, infill: int =15) ->  Dict:
        """
        Slice the model and extract printing information
        Returns: ( slicing_data)
        """
        print(f"🔪 Slicing model (material: {material}, layer: {layer_height}mm, infill: {infill}%)")
        
        gcode_path = os.path.join("temp", f"{job_id}.gcode")
        config_file = look(layer_height, infill)
        
        cmd = [
            self.config["paths"]["prusaslicer"],
            "--load", config_file,
            "--export-gcode",
            "--output", gcode_path,
            stl_path
        ]
        
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=self.config["printing"]["timeout"]
            )
            print(result.stdout)
            
            if result.returncode != 0:
                error_msg = f"Slicer failed: {result.stderr}"
                # print(f"❌ {error_msg}")
                return {"error": error_msg}
            
            # Parse G-code for printing information
            slicing_data = self.parse_gcode(gcode_path, material, layer_height, infill)
            print(f"✅ Slicing completed - {slicing_data.get('print_time', 'Unknown')} estimated")
            shutil.os.remove(gcode_path)  # Clean up intermediate STL file
            
            return slicing_data
            
        except Exception as e:
            error_msg = f"Slicing error: {str(e)}"
            # print(f"❌ {error_msg}")
            return {"error": error_msg}
    
    def parse_gcode(self, gcode_path: str, material: str, layer_height: float, infill: int) -> Dict:
        """Extract detailed information from generated G-code"""
        data = {
            "print_time": None,
            "print_time_seconds": 0,
            "print_time_hours": 0,
            "filament_used_mm": 0,
            "filament_used_grams": 0,
            "material": material,
            "layer_height": layer_height,
            "infill_percentage": infill,
            "support_material": False
        }
        
        try:
            with open(gcode_path, "r") as f:
                content = f.read()
                
                # Extract print time
                time_match = re.search(r'; estimated printing time \(normal mode\) = (.+)', content)
                if time_match:
                    time_str = time_match.group(1).strip()
                    data["print_time"] = time_str
                    data["print_time_seconds"] = self.parse_time_to_seconds(time_str)
                    data["print_time_hours"] = round(data["print_time_seconds"] / 3600, 2)
                
                # Extract filament usage
                filament_match = re.search(r'; filament used \[mm\] = ([\d.]+)', content)
                if filament_match:
                    filament_mm = float(filament_match.group(1))
                    data["filament_used_mm"] = filament_mm
                    data["filament_used_grams"] = self.estimate_filament_weight(filament_mm, material)
                
                # Extract layer height from gcode if not set
                if not layer_height:
                    layer_match = re.search(r'; layer_height = ([\d.]+)', content)
                    if layer_match:
                        data["layer_height"] = float(layer_match.group(1))
                
                # Extract infill from gcode if not set
                if not infill:
                    infill_match = re.search(r'; fill_density = ([\d.]+)', content)
                    if infill_match:
                        data["infill_percentage"] = float(infill_match.group(1)) * 100
                
                # Check for support material
                data["support_material"] = "; support_material = 1" in content
                
        except Exception as e:
            print(f"⚠️ Warning: Could not parse G-code fully: {e}")
        
        return data
    
    def parse_time_to_seconds(self, time_str: str) -> int:
        """Convert time string like '2h 30m 45s' to seconds"""
        total_seconds = 0
        
        # Handle day
        day_match = re.search(r'(\d+)d', time_str)
        if day_match:
            total_seconds += int(day_match.group(1)) * 86400
        
        # Handle hours
        hour_match = re.search(r'(\d+)h', time_str)
        if hour_match:
            total_seconds += int(hour_match.group(1)) * 3600
        
        # Handle minutes  
        min_match = re.search(r'(\d+)m', time_str)
        if min_match:
            total_seconds += int(min_match.group(1)) * 60
        
        # Handle seconds
        sec_match = re.search(r'(\d+)s', time_str)
        if sec_match:
            total_seconds += int(sec_match.group(1))
        
        return total_seconds
    
    def estimate_filament_weight(self, filament_mm: float, material: str) -> float:
        """Estimate filament weight in grams based on length and material"""
        # Filament density (g/cm³) for 1.75mm diameter
        density_map = {
            "PLA": 1.24,
            "PETG": 1.27, 
            "ABS": 1.04,
            "TPU": 1.20
        }
        
        density = density_map.get(material, 1.24)  # Default to PLA
        
        # Calculate volume: π * r² * length (r = 0.875mm for 1.75mm filament)
        radius_cm = 0.0875  # 0.875mm = 0.0875cm
        length_cm = filament_mm / 10  # mm to cm
        volume_cm3 = math.pi * (radius_cm ** 2) * length_cm
        
        weight_grams = volume_cm3 * density
        return round(weight_grams, 2)
    
    def round_price(self, price: float) -> float:
        """
        Apply custom rounding rules for pricing:
        - Under $5: round to $4.90
        - Under $10: round to $9.90
        - Under $20: round down to nearest int - 0.1 (e.g., 17.5 → 16.90)
        - $20-$100: round down to nearest 5 - 0.1 (e.g., 48 → 44.90)
        - Above $100: round down to nearest 10 - 0.1 (e.g., 148 → 139.90)
        """
        if price < 5:
            return 4.90
        elif price < 10:
            return 9.90
        elif price < 20:
            # Round down to nearest int and subtract 0.1
            return math.floor(price) - 0.10
        elif price <= 100:
            # Round down to nearest 5 and subtract 0.1
            rounded_down = (math.floor(price / 5) * 5) - 0.10
            return max(rounded_down, 19.90)  # Ensure it doesn't go below $19.90
        else:
            # Round down to nearest 10 and subtract 0.1
            return (math.floor(price / 10) * 10) - 0.10
    
    def calculate_pricing(self, slicing_data: Dict, complexity: str = "medium", 
                         material: str = "PLA", rush_order: bool = False) -> Dict:
        """
        Calculate pricing using simplified formula:
        Base: print_time (hours) × 3
        Material multiplier: PLA=0.8, PETG=1.0, ABS=1.2
        Complexity multiplier: low=0.8, medium=1.0, high=1.2
        Rush order: ×1.2
        Then apply custom rounding rules
        """
        pricing = self.config["pricing"]
        
        # Complexity multipliers
        complexity_multipliers = {
            "low": 0.8,
            "medium": 1.0,
            "high": 1.2
        }
        
        # Get print time in hours
        time_hours = slicing_data.get("print_time_hours", 0)
        
        if time_hours == 0:
            time_hours = slicing_data.get("print_time_seconds", 0) / 3600
        
        # Base calculation: time × base rate
        base_cost = time_hours * pricing["base_rate_per_hour"]
        
        # Apply complexity multiplier
        complexity_mult = complexity_multipliers.get(complexity, 1.0)
        cost_after_complexity = base_cost * complexity_mult

        # Apply material multiplier
        material_mult = pricing["material_multipliers"].get(material, 1.0)
        cost_after_material = cost_after_complexity * material_mult
        
        
        # Apply rush order multiplier if needed
        if rush_order:
            final_cost = cost_after_material * pricing["rush_multiplier"]
        else:
            final_cost = cost_after_material
        
        # Apply custom rounding
        rounded_price = self.round_price(final_cost)
        
        return {
            "print_time_hours": round(time_hours, 2),
            "base_rate_per_hour": pricing["base_rate_per_hour"],
            "base_cost": round(base_cost, 2),
            "material": material,
            "material_multiplier": material_mult,
            "cost_after_material": round(cost_after_material, 2),
            "complexity": complexity,
            "complexity_multiplier": complexity_mult,
            "cost_after_complexity": round(cost_after_complexity, 2),
            "rush_order": rush_order,
            "rush_multiplier": pricing["rush_multiplier"] if rush_order else 1.0,
            "cost_before_rounding": round(final_cost, 2),
            "total": round(rounded_price, 2),
            "filament_weight_grams": slicing_data.get("filament_used_grams", 0)
        }
    
    def generate_quotation(self, input_file: str, material: str = "PLA", 
                          layer_height: float = 0.2, infill: int = 15,
                          rush_order: bool = False) -> Dict:
        """
        Generate complete quotation with STEP conversion, mesh validation, orientation, slicing, and pricing
        Main entry point for the quotation engine
        
        Workflow:
        1. Check if file is STEP/STP, convert to STL if needed
        2. Validate mesh (watertight, consistent winding, positive volume)
        3. Orient STL using Tweaker3 for optimal printing
        4. Slice with specified parameters (layer height, infill)
        5. Calculate price using simplified formula
        """
        job_id = str(uuid.uuid4())
        
        print(f"🚀 Starting quotation generation for job {job_id}")
        print(f"📁 Input file: {input_file}")
        print(f"🧱 Material: {material}, Layer: {layer_height}mm, Infill: {infill}%")
        print(f"⚡ Rush order: {rush_order}")
        
        # Validate input file
        is_valid, validation_msg = self.validate_model(input_file)
        if not is_valid:
            return {
                "success": False,
                "error": validation_msg,
                "job_id": job_id,
                "timestamp": datetime.now().isoformat()
            }
        
        # Step 1: Check if STEP/STP file and convert to STL
        file_ext = os.path.splitext(input_file)[1].lower()
        if file_ext in [".step", ".stp"]:
            stl_file, convert_msg = self.convert_step_to_stl(input_file, job_id)
            if stl_file is None:
                return {
                    "success": False,
                    "error": convert_msg,
                    "job_id": job_id,
                    "timestamp": datetime.now().isoformat()
                }
            conversion_performed = True
        else:
            stl_file = input_file
            conversion_performed = False
        
        # Step 2: Validate mesh
        mesh_valid, mesh_msg = self.check_mesh_validity(stl_file)
        if not mesh_valid:
            return {
                "success": False,
                "error": f"Mesh validation failed: {mesh_msg}",
                "job_id": job_id,
                "timestamp": datetime.now().isoformat()
            }
        
        # Step 3: Orient STL using Tweaker3
        oriented_stl, orient_msg, orientation_data = self.orient_stl_with_tweaker3(stl_file, job_id)
        if oriented_stl is None:
            return {
                "success": False,
                "error": f"Orientation failed: {orient_msg}",
                "job_id": job_id,
                "timestamp": datetime.now().isoformat()
            }
        
        complexity = orientation_data.get("complexity", "medium")
        print(f"📊 Model complexity: {complexity}")
        
        # Step 4: Slice model
        slicing_data = self.slice_model(oriented_stl, job_id, material, layer_height, infill)
        
        if slicing_data.get("error") is not None:
            return {
                "success": False,
                "error": slicing_data.get("error", "Slicing failed"),
                "job_id": job_id,
                "timestamp": datetime.now().isoformat()
            }
        
        # Step 5: Calculate pricing
        pricing_data = self.calculate_pricing(slicing_data, complexity, material, rush_order)
        
        quotation = {
            "success": True,
            "job_id": job_id,
            "timestamp": datetime.now().isoformat(),
            
            # File information
            "files": {
                "original_file": os.path.basename(input_file),
                "conversion_performed": conversion_performed,
                "stl_file": os.path.basename(stl_file) if conversion_performed else None,
                "oriented_model": os.path.basename(oriented_stl)
            },
            
            # Processing results
            "processing": {
                "mesh_valid": mesh_valid,
                "mesh_message": mesh_msg,
                "orientation_message": orient_msg,
                "complexity": complexity,
                "orientation_data": orientation_data
            },
            
            # Slicing results
            "slicing": slicing_data,
            
            # Pricing breakdown
            "pricing": pricing_data,
            
            # Summary
            "summary": {
                "material": material,
                "layer_height": layer_height,
                "infill_percentage": infill,
                "print_time": slicing_data.get("print_time", "Unknown"),
                "total_cost": pricing_data["total"],
                "estimated_delivery": "2-3 business days" if not rush_order else "24-48 hours"
            }
        }
        
        
        print(f"💰 Total cost: ${pricing_data['total']}")
        print(f"⏱️ Print time: {slicing_data.get('print_time', 'Unknown')}")
        
        return quotation
    
    def save_quotation(self, quotation: Dict):
        """Save quotation data to JSON file for record keeping"""
        try:
            quotations_dir = os.path.join("temp", "quotations")
            os.makedirs(quotations_dir, exist_ok=True)
            
            filename = f"{quotation['job_id']}_quotation.json"
            filepath = os.path.join(quotations_dir, filename)
            
            with open(filepath, 'w') as f:
                json.dump(quotation, f, indent=2)
            
            print(f"📄 Quotation saved: {filename}")
        except Exception as e:
            print(f"⚠️ Warning: Could not save quotation: {e}")

# CLI Interface for testing
def main():
    """Command line interface for testing the quotation engine"""
    import argparse
    
    parser = argparse.ArgumentParser(description="3D Printing Quotation Engine")
    parser.add_argument("file", help="Path to STL/STEP/STP file")
    parser.add_argument("--material", default="PLA", choices=["PLA", "PETG", "ABS"], 
                       help="Printing material (default: PLA)")
    parser.add_argument("--layer", type=float, default=0.2, choices=[0.16, 0.2, 0.3],
                       help="Layer height in mm (default: 0.2)")
    parser.add_argument("--infill", type=int, default=20,
                       help="Infill percentage (default: 20)")
    parser.add_argument("--rush", action="store_true", help="Rush order (20%% extra cost)")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    
    args = parser.parse_args()
    
    # Create quotation engine
    engine = QuotationEngine()
    
    # Generate quotation
    result = engine.generate_quotation(
        input_file=args.file,
        material=args.material,
        layer_height=args.layer,
        infill=args.infill,
        rush_order=args.rush
    )
    
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        # Pretty print results
        if result["success"]:
            print("\n" + "="*60)
            print("         3D PRINTING QUOTATION")
            print("="*60)
            print(f"Job ID: {result['job_id']}")
            print(f"Material: {result['summary']['material']}")
            print(f"Layer Height: {result['summary']['layer_height']}mm")
            print(f"Infill: {result['summary']['infill_percentage']}%")
            print(f"Print Time: {result['summary']['print_time']}")
            print(f"Rush Order: {'Yes' if result['pricing']['rush_order'] else 'No'}")
            print("\n" + "-"*30 + " PRICING " + "-"*30)
            print(f"Base Cost:        ${result['pricing']['base_cost']:8.2f} ({result['pricing']['print_time_hours']:.2f}h × ${result['pricing']['base_rate_per_hour']}/h)")
            print(f"Material Factor:  {result['pricing']['material']} (×{result['pricing']['material_multiplier']})")
            if result['pricing']['rush_order']:
                print(f"Rush Order:       ×{result['pricing']['rush_multiplier']}")
            print(f"Before Rounding:  ${result['pricing']['cost_before_rounding']:8.2f}")
            print("-"*47)
            print(f"TOTAL:            ${result['pricing']['total']:8.2f}")
            print("="*60)
            print(f"Filament: {result['pricing']['filament_weight_grams']:.1f}g")
            
            if result['files']['conversion_performed']:
                print(f"✅ STEP file converted to STL")
            
            print(f"✅ Mesh validated successfully")
            print(f"✅ Model oriented for optimal printing")
            
        else:
            print(f"❌ Error: {result['error']}")

if __name__ == "__main__":
    main()
