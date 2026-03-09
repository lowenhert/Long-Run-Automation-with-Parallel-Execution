import json
from pathlib import Path
from datetime import datetime
import traceback
import logging
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

class ReportGenerator:
    def __init__(self, execution_dir: Path):
        self.execution_dir = execution_dir
        # Generate Excel filename with current date in DD-MM-YYYY format
        current_date = datetime.now().strftime("%d-%m-%Y")
        excel_filename = f"OTT_Playback_{current_date}.xlsx"
        self.excel_path = execution_dir / excel_filename
        self.detailed_log_path = execution_dir / "detailed_failures.json"
        self.failed_scenarios_log = execution_dir / "failed_scenarios.log"
        self._init_excel()
        self._init_failure_logs()

    def _init_excel(self):
        if not self.excel_path.exists():
            wb = Workbook()
            ws = wb.active
            ws.title = "OTT Playback Results"
            
            # Define headers
            self.headers = [
                "Ott_App_Name", "Content_Name", "Playback_Time_Seconds",
                "Timestamp", "Device_ID", "Status", "Screenshots_Folder",
                "Error_Type", "Error_Message", "Failed_Step"
            ]
            
            # Dark blue header style
            header_fill = PatternFill(start_color="00008B", end_color="00008B", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            thin_border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )
            
            # Write headers with styling
            for col, header in enumerate(self.headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center")
                cell.border = thin_border
            
            # Initial column widths based on header
            for col, header in enumerate(self.headers, 1):
                ws.column_dimensions[get_column_letter(col)].width = max(len(header) + 2, 15)
            
            wb.save(self.excel_path)
        else:
            self.headers = [
                "Ott_App_Name", "Content_Name", "Playback_Time_Seconds",
                "Timestamp", "Device_ID", "Status", "Screenshots_Folder",
                "Error_Type", "Error_Message", "Failed_Step"
            ]
    
    def _init_failure_logs(self):
        """Initialize detailed failure logging files"""
        if not self.detailed_log_path.exists():
            with open(self.detailed_log_path, "w") as f:
                json.dump({"failed_scenarios": []}, f, indent=2)
        
        if not self.failed_scenarios_log.exists():
            with open(self.failed_scenarios_log, "w") as f:
                f.write(f"Failed Scenarios Log - Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 80 + "\n\n")

    def add_result(self, app_name, content_name, playback_time, device_id, status, screenshots_folder, 
                   error_type="", error_message="", failed_step="", full_traceback=""):
        """Add test result with enhanced failure details"""
        wb = load_workbook(self.excel_path)
        ws = wb.active
        
        # Find next empty row
        next_row = ws.max_row + 1
        
        # Add data row
        row_data = [
            app_name, content_name, playback_time,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            device_id, status, screenshots_folder,
            error_type, error_message, failed_step
        ]
        
        # Border style for data cells
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        for col, value in enumerate(row_data, 1):
            cell = ws.cell(row=next_row, column=col, value=value)
            cell.border = thin_border
        
        # Auto-adjust column widths based on content
        for col in range(1, len(row_data) + 1):
            col_letter = get_column_letter(col)
            max_length = len(str(self.headers[col - 1])) + 2
            for row in range(1, next_row + 1):
                cell_value = ws.cell(row=row, column=col).value
                if cell_value:
                    max_length = max(max_length, len(str(cell_value)) + 2)
            ws.column_dimensions[col_letter].width = min(max_length, 50)  # Cap at 50
        
        wb.save(self.excel_path)
        
        # If failed, log detailed information
        if status == "FAILED":
            self._log_failure_details(app_name, content_name, device_id, error_type, 
                                    error_message, failed_step, full_traceback)
    
    def _log_failure_details(self, app_name, content_name, device_id, error_type, 
                           error_message, failed_step, full_traceback):
        """Log detailed failure information for analysis"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Add to JSON log for structured data
        try:
            with open(self.detailed_log_path, "r") as f:
                data = json.load(f)
            
            failure_entry = {
                "timestamp": timestamp,
                "app_name": app_name,
                "content_name": content_name,
                "device_id": device_id,
                "error_type": error_type,
                "error_message": error_message,
                "failed_step": failed_step,
                "full_traceback": full_traceback
            }
            
            data["failed_scenarios"].append(failure_entry)
            
            with open(self.detailed_log_path, "w") as f:
                json.dump(data, f, indent=2)
        
        except Exception as e:
            print(f"Warning: Could not update JSON failure log: {e}")
        
        # Add to text log for easy reading
        try:
            with open(self.failed_scenarios_log, "a") as f:
                f.write(f"FAILURE DETECTED - {timestamp}\n")
                f.write(f"App: {app_name} | Content: {content_name} | Device: {device_id}\n")
                f.write(f"Error Type: {error_type}\n")
                f.write(f"Failed Step: {failed_step}\n")
                f.write(f"Error Message: {error_message}\n")
                if full_traceback:
                    f.write(f"Full Traceback:\n{full_traceback}\n")
                f.write("-" * 80 + "\n\n")
        
        except Exception as e:
            print(f"Warning: Could not update text failure log: {e}")

    def get_failure_summary(self):
        """Get summary of all failures for reporting"""
        try:
            with open(self.detailed_log_path, "r") as f:
                data = json.load(f)
            return data.get("failed_scenarios", [])
        except Exception:
            return []