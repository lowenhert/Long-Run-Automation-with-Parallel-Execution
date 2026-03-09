#!/usr/bin/env python3
"""
Unified Interactive OTT Test Runner
Combines connectivity testing, individual test case selection, and parallel execution
"""

import sys
import os
import subprocess
import time
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil
import yaml

# Import project modules
from core.device_manager import DeviceManager
from libraries.DeviceController import DeviceController
from core.email_sender import EmailSender
from core.test_scheduler import TestScheduler

class InteractiveTestRunner:
    def __init__(self):
        self.python_exe = sys.executable
        self.devices = []
        self.test_cases = []
        self.non_drm_test_cases = []
        self.drm_test_cases = []
        self.settings = {}
        self.email_sender = None
        self.scheduler = None
        self.last_execution_dir = None
        self.load_config()
        self._init_email_and_scheduler()
        self._garbage_collect_old_results()
    
    def _garbage_collect_old_results(self, days=30):
        """Delete TestResults folders older than specified days"""
        results_dir = Path("TestResults")
        if not results_dir.exists():
            return
        
        cutoff_date = datetime.now() - timedelta(days=days)
        deleted_count = 0
        
        for folder in results_dir.iterdir():
            if not folder.is_dir():
                continue
            
            # Try to parse execution date from folder name (Execution_YYYYMMDD_HHMMSS)
            try:
                folder_name = folder.name
                if folder_name.startswith("Execution_"):
                    date_str = folder_name.split("_")[1]  # YYYYMMDD
                    folder_date = datetime.strptime(date_str, "%Y%m%d")
                    
                    if folder_date < cutoff_date:
                        shutil.rmtree(folder)
                        deleted_count += 1
            except (ValueError, IndexError):
                # Skip folders that don't match expected format
                continue
        
        if deleted_count > 0:
            print(f"🗑️  Cleaned up {deleted_count} test result(s) older than {days} days")
    
    def load_config(self):
        """Load test cases from configuration"""
        try:
            # Load settings
            with open("config/settings.yaml") as f:
                self.settings = yaml.safe_load(f)
                print(f"✅ Loaded settings (playback_duration: {self.settings.get('playback_duration', 30)}s)")
            
            # Load test cases
            with open("config/test_cases.yaml") as f:
                config = yaml.safe_load(f)
                all_test_cases = config["test_cases"]
                
                # Separate DRM and non-DRM test cases
                self.non_drm_test_cases = [case for case in all_test_cases if not case.get("drm", False)]
                self.drm_test_cases = [case for case in all_test_cases if case.get("drm", False)]
                self.test_cases = all_test_cases  # Keep all for compatibility
                self.all_test_cases = all_test_cases  # Canonical full list for index lookups
                
            print(f"✅ Loaded {len(self.non_drm_test_cases)} non-DRM test cases")
            print(f"✅ Loaded {len(self.drm_test_cases)} DRM test cases")
        except Exception as e:
            print(f"❌ Failed to load test cases: {e}")
            sys.exit(1)
    
    def _init_email_and_scheduler(self):
        """Initialize email sender and scheduler"""
        try:
            email_config = self.settings.get('email', {})
            self.email_sender = EmailSender(email_config)
            if email_config.get('enabled', False):
                recipients = ', '.join(email_config.get('recipient_emails', []))
                print(f"✅ Email notifications enabled (to: {recipients})")
        except Exception as e:
            print(f"⚠️  Email sender initialization failed: {e}")
        
        try:
            self.scheduler = TestScheduler(
                test_runner_callback=self._run_scheduled_tests,
                email_callback=self._send_scheduled_email
            )
            print(f"✅ Scheduler initialized")
        except Exception as e:
            print(f"⚠️  Scheduler initialization failed: {e}")
    
    def _run_scheduled_tests(self):
        """Run all tests on all devices (called by scheduler)"""
        try:
            if not self.devices:
                print("⚠️  No devices available for scheduled test")
                return None
            
            exec_id = datetime.now().strftime("Execution_%Y%m%d_%H%M%S")
            exec_dir = Path("TestResults") / exec_id
            
            # Run all test cases on all devices
            cases = self.all_test_cases
            total = len(cases)
            
            print(f"\\n📋 Running {total} scheduled tests on {len(self.devices)} device(s)")
            
            if len(self.devices) == 1:
                self._run_device_sequence(self.devices[0], cases, exec_id)
            else:
                with ThreadPoolExecutor(max_workers=len(self.devices)) as executor:
                    futures = {
                        executor.submit(self._run_device_sequence, dev, cases, exec_id): dev
                        for dev in self.devices
                    }
                    for future in as_completed(futures):
                        dev = futures[future]
                        try:
                            future.result()
                        except Exception as e:
                            print(f"❌ Device {dev} raised an error: {e}")
            
            self.last_execution_dir = exec_dir
            return exec_dir
            
        except Exception as e:
            print(f"❌ Error in scheduled test execution: {e}")
            return None
    
    def _send_scheduled_email(self, exec_dir):
        """Send email report after scheduled test (called by scheduler)"""
        if not exec_dir or not self.email_sender or not self.email_sender.enabled:
            return
        
        try:
            excel_files = list(exec_dir.glob("OTT_Playback_*.xlsx"))
            if not excel_files:
                excel_path = exec_dir / "test_results.xlsx"
                if not excel_path.exists():
                    print(f"⚠️  No Excel report found in {exec_dir}")
                    return
            else:
                excel_path = excel_files[0]
            
            print(f"\\n📧 Sending scheduled email report...")
            self.email_sender.send_report(str(excel_path), exec_dir.name)
        except Exception as e:
            print(f"❌ Failed to send scheduled email: {e}")
    
    def check_setup(self):
        """Verify project setup"""
        print("🔧 Checking project setup...")
        
        # Check devices
        try:
            self.devices = DeviceManager.get_connected_devices()
            if not self.devices:
                print("❌ No Android devices connected via ADB")
                print("   Please connect your Android TV and enable ADB debugging")
                return False
            print(f"✅ Found {len(self.devices)} connected device(s): {', '.join(self.devices)}")
        except Exception as e:
            print(f"❌ Device check failed: {e}")
            return False
        
        # Check required files
        required_files = [
            "config/settings.yaml",
            "config/test_cases.yaml", 
            "test/test_ott_playback.py",
            "test/test_ott_drm_playback.py"
        ]
        
        for file_path in required_files:
            if Path(file_path).exists():
                print(f"✅ {file_path} exists")
            else:
                print(f"❌ {file_path} missing")
                return False
        
        print("✅ Project setup verified!")
        return True
    
    def test_connectivity(self):
        """Test basic device connectivity"""
        print("\n🧪 Testing device connectivity...")
        
        for device_id in self.devices:
            try:
                device = DeviceController(device_id)
                print(f"📱 Testing device: {device_id}")
                
                # Test screenshot capability
                screenshot = device.take_screenshot(f"connectivity_test_{device_id.replace(':', '_')}.png")
                if screenshot:
                    print(f"  ✅ Screenshot test passed: {screenshot}")
                else:
                    print(f"  ❌ Screenshot test failed")
                    return False
                    
                # Test navigation
                print(f"  📱 Testing navigation...")
                device.home()
                time.sleep(1)
                print(f"  ✅ Navigation test passed")
                
            except Exception as e:
                print(f"  ❌ Connectivity test failed for {device_id}: {e}")
                return False
        
        print("✅ All device connectivity tests passed!")
        return True
    
    def show_devices(self):
        """Display available devices"""
        print("\n📱 Available Devices:")
        for i, device in enumerate(self.devices, 1):
            print(f"  {i}. {device}")
    
    def show_test_cases(self, test_type="all"):
        """Display available test cases"""
        if test_type == "non-drm":
            cases = self.non_drm_test_cases
            print("\n🎬 Available Non-DRM Test Cases:")
        elif test_type == "drm":
            cases = self.drm_test_cases
            print("\n🎬 Available DRM Test Cases:")
        else:
            cases = self.test_cases
            print("\n🎬 Available Test Cases:")
            
        for i, test_case in enumerate(cases, 1):
            app_name = test_case['app_name']
            duration = test_case.get('playback_duration', self.settings.get('playback_duration', 30))
            drm_flag = "(DRM)" if test_case.get("drm", False) else "(Non-DRM)"
            print(f"  {i}. {app_name} {drm_flag} (Duration: {duration}s)")
    
    def select_devices(self):
        """Let user select which devices to test on"""
        self.show_devices()
        
        while True:
            try:
                choice = input(f"\nSelect devices (1-{len(self.devices)}, 'all', or comma-separated): ").strip().lower()
                
                if choice == 'all':
                    return self.devices.copy()
                
                if ',' in choice:
                    indices = [int(x.strip()) - 1 for x in choice.split(',')]
                    selected = [self.devices[i] for i in indices if 0 <= i < len(self.devices)]
                    if selected:
                        return selected
                else:
                    index = int(choice) - 1
                    if 0 <= index < len(self.devices):
                        return [self.devices[index]]
                
                print("❌ Invalid selection. Please try again.")
                
            except (ValueError, IndexError):
                print("❌ Invalid input. Please enter numbers.")
    
    def select_test_cases(self, test_type="all"):
        """Let user select which test cases to run"""
        if test_type == "non-drm":
            cases = self.non_drm_test_cases
        elif test_type == "drm":
            cases = self.drm_test_cases
        else:
            cases = self.test_cases
            
        self.show_test_cases(test_type)
        
        while True:
            try:
                choice = input(f"\nSelect test cases (1-{len(cases)}, 'all', or comma-separated): ").strip().lower()
                
                if choice == 'all':
                    return cases.copy()
                
                if ',' in choice:
                    indices = [int(x.strip()) - 1 for x in choice.split(',')]
                    selected = [cases[i] for i in indices if 0 <= i < len(cases)]
                    if selected:
                        return selected
                else:
                    index = int(choice) - 1
                    if 0 <= index < len(cases):
                        return [cases[index]]
                
                print("❌ Invalid selection. Please try again.")
                
            except (ValueError, IndexError):
                print("❌ Invalid input. Please enter numbers.")
    
    def _resolve_global_index(self, test_case, fallback_idx):
        """Find the global index of a test case in the full yaml list."""
        idx = next(
            (j for j, tc in enumerate(self.all_test_cases)
             if tc.get('id') == test_case.get('id')),
            None
        )
        if idx is None:
            idx = next(
                (j for j, tc in enumerate(self.all_test_cases)
                 if tc['app_name'] == test_case['app_name']),
                fallback_idx
            )
        return idx

    def _run_device_sequence(self, device_id, cases, exec_id):
        """Run the full test sequence for one device (called in a thread)."""
        env = os.environ.copy()
        env["DEVICE_NAME"] = device_id
        env["TARGET_DEVICE"] = device_id
        env["EXECUTION_ID"] = exec_id
        device_safe = device_id.replace(":", "_").replace(".", "_")
        exec_dir = Path("TestResults") / exec_id / f"device_{device_safe}"
        exec_dir.mkdir(parents=True, exist_ok=True)
        total = len(cases)

        try:
            for idx, test_case in enumerate(cases, 1):
                app_name = test_case["app_name"]
                is_drm = test_case.get("drm", False)
                test_file = "test/test_ott_drm_playback.py" if is_drm else "test/test_ott_playback.py"
                tag = "DRM" if is_drm else "non-DRM"
                global_index = self._resolve_global_index(test_case, idx - 1)

                print(f"  [{device_id}] [{idx}/{total}] {tag}: {app_name}")
                test_env = env.copy()
                test_env["DEVICE_ID"] = device_id
                test_env["CURRENT_TEST_CASE"] = str(global_index)

                cmd = [
                    self.python_exe, "-m", "pytest",
                    test_file,
                    "-v", "--tb=short", "--capture=no",
                    "--log-cli-level=DEBUG",
                    "--log-cli-format=%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    "--log-file-level=DEBUG",
                    f"--log-file={exec_dir}/test_{tag.lower()}_{app_name.lower()}_{idx}.log",
                    f"--html={exec_dir}/report_{tag.lower()}_{app_name.lower()}_{idx}.html",
                    "--self-contained-html"
                ]
                try:
                    result = subprocess.run(cmd, env=test_env, capture_output=True, text=True, timeout=30000)
                    symbol = "✅" if result.returncode == 0 else "❌"
                    print(f"  [{device_id}] {symbol} {tag} {app_name} "
                          f"{'PASSED' if result.returncode == 0 else 'FAILED'}")
                    if result.returncode != 0 and result.stderr:
                        print(f"  [{device_id}]   stderr: {result.stderr[:300]}")
                except subprocess.TimeoutExpired:
                    print(f"  [{device_id}] ⏰ {tag} {app_name} TIMED OUT")
                except Exception as e:
                    print(f"  [{device_id}] ❌ {tag} {app_name} ERROR: {e}")

        finally:
            # ── Rail reset — runs ONCE after ALL 12 apps are done ─────────────
            # Presses left x30 to return cursor to rail start, then HOME
            print(f"\n  [{device_id}] 🔄 Performing final rail reset...")
            try:
                device = DeviceController(device_id)
                device.navigate_down(2)
                for _ in range(31):
                    device.left()
                    time.sleep(0.1)
                time.sleep(0.5)
                device.up()
                device.up()
                print(f"  [{device_id}] ✅ Rail reset complete")
            except Exception as reset_exc:
                print(f"  [{device_id}] ❌ Rail reset failed: {reset_exc}")

        print(f"\n📊 Results for {device_id}: {exec_dir}")
        return exec_dir

    def run_yaml_sequence_tests(self, selected_devices, selected_cases=None):
        """Run tests in YAML order. Multiple devices run in parallel threads,
        each device runs its own cases sequentially."""
        cases = selected_cases if selected_cases is not None else self.all_test_cases
        total = len(cases)
        exec_id = datetime.now().strftime("Execution_%Y%m%d_%H%M%S")

        print(f"\n📋 Running {total} tests in YAML sequence order")
        print("   " + "  →  ".join(
            f"{tc['app_name']}({'DRM' if tc.get('drm') else 'non-DRM'})"
            for tc in cases
        ))
        print(f"🆔 Execution ID: {exec_id}")

        if len(selected_devices) == 1:
            # Single device — run directly
            self._run_device_sequence(selected_devices[0], cases, exec_id)
        else:
            # Multiple devices — run all in parallel, each device gets its own thread
            print(f"\n⚡ Running on {len(selected_devices)} devices in parallel...")
            with ThreadPoolExecutor(max_workers=len(selected_devices)) as executor:
                futures = {
                    executor.submit(self._run_device_sequence, dev, cases, exec_id): dev
                    for dev in selected_devices
                }
                for future in as_completed(futures):
                    dev = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        print(f"❌ Device {dev} raised an error: {e}")

        print("\n🎉 YAML sequence execution completed!")
        
        # Store last execution directory for email reports
        self.last_execution_dir = Path("TestResults") / exec_id
        return self.last_execution_dir

    def main_menu(self):
        """Main interactive menu"""
        print("\n" + "="*60)
        print("🎬 OTT PLAYBACK TEST RUNNER")
        print("="*60)

        while True:
            print(f"\nTest cases loaded: {len(self.all_test_cases)} total "
                  f"({len(self.non_drm_test_cases)} non-DRM, {len(self.drm_test_cases)} DRM)")
            print("\nSelect an option:")
            print("1. 🔌 Test Device Connectivity")
            print("2. 🎯 Run Selected Test Cases (YAML order)")
            print("3. 🚀 Run All Test Cases (YAML order)")
            print("4. 📅 Schedule Tests")
            print("5. 📧 Email Report (Last Execution)")
            print("6. ❌ Exit")

            try:
                choice = input("\nEnter your choice (1-6): ").strip()

                if choice == '1':
                    self.test_connectivity()
                    input("\nPress Enter to continue...")

                elif choice == '2':
                    # Show all cases in yaml order and let user pick
                    self.show_test_cases("all")
                    selected_cases = self.select_test_cases("all")
                    selected_devices = self.select_devices()
                    self.run_yaml_sequence_tests(selected_devices, selected_cases)
                    
                    # Ask if user wants to email the report
                    if self.last_execution_dir and self.email_sender and self.email_sender.enabled:
                        send_email = input("\n📧 Send email report? (y/n): ").strip().lower()
                        if send_email == 'y':
                            self.send_email_report()
                    input("\nPress Enter to continue...")

                elif choice == '3':
                    selected_devices = self.select_devices()
                    self.run_yaml_sequence_tests(selected_devices)
                    
                    # Ask if user wants to email the report
                    if self.last_execution_dir and self.email_sender and self.email_sender.enabled:
                        send_email = input("\n📧 Send email report? (y/n): ").strip().lower()
                        if send_email == 'y':
                            self.send_email_report()
                    input("\nPress Enter to continue...")

                elif choice == '4':
                    self.schedule_tests_menu()
                    input("\nPress Enter to continue...")

                elif choice == '5':
                    self.send_email_report()
                    input("\nPress Enter to continue...")

                elif choice == '6':
                    print("👋 Goodbye!")
                    if self.scheduler:
                        self.scheduler.stop_scheduler()
                    sys.exit(0)

                else:
                    print("❌ Invalid choice. Please select 1-6.")

            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                sys.exit(0)
            except Exception as e:
                print(f"❌ Error: {e}")
                input("Press Enter to continue...")
    
    def schedule_tests_menu(self):
        """Schedule tests menu"""
        print("\n" + "="*60)
        print("📅 SCHEDULE TESTS")
        print("="*60)
        
        print("\nScheduling Options:")
        print("1. Schedule Once (Specific Time)")
        print("2. Schedule Recurring (Hourly)")
        print("3. Schedule Recurring (Daily)")
        print("4. Schedule Recurring (Weekly)")
        print("5. View Scheduled Tests")
        print("6. Clear All Schedules")
        print("7. Back to Main Menu")
        
        try:
            choice = input("\nEnter your choice (1-7): ").strip()
            
            if choice == '1':
                run_time = input("Enter time (HH:MM, 24-hour format): ").strip()
                if self.scheduler.schedule_once(run_time):
                    print(f"✅ Test scheduled for {run_time}")
                    print("   📧 Email will be sent automatically after test completion")
                    if not self.scheduler.is_running:
                        self.scheduler.start_scheduler()
                        print("✅ Scheduler started in background")
            
            elif choice == '2':
                hours = int(input("Enter interval in hours: ").strip())
                if self.scheduler.schedule_recurring('hourly', hours):
                    print(f"✅ Tests scheduled every {hours} hour(s)")
                    print("   📧 Email will be sent automatically after each test run")
                    if not self.scheduler.is_running:
                        self.scheduler.start_scheduler()
                        print("✅ Scheduler started in background")
            
            elif choice == '3':
                days = int(input("Enter interval in days: ").strip())
                run_time = input("Enter time (HH:MM, 24-hour format) or leave empty: ").strip()
                run_time = run_time if run_time else None
                if self.scheduler.schedule_recurring('daily', days, run_time):
                    print(f"✅ Tests scheduled every {days} day(s)" + (f" at {run_time}" if run_time else ""))
                    print("   📧 Email will be sent automatically after each test run")
                    if not self.scheduler.is_running:
                        self.scheduler.start_scheduler()
                        print("✅ Scheduler started in background")
            
            elif choice == '4':
                weeks = int(input("Enter interval in weeks: ").strip())
                run_time = input("Enter time (HH:MM, 24-hour format) or leave empty: ").strip()
                run_time = run_time if run_time else None
                if self.scheduler.schedule_recurring('weekly', weeks, run_time):
                    print(f"✅ Tests scheduled every {weeks} week(s)" + (f" at {run_time}" if run_time else ""))
                    print("   📧 Email will be sent automatically after each test run")
                    if not self.scheduler.is_running:
                        self.scheduler.start_scheduler()
                        print("✅ Scheduler started in background")
            
            elif choice == '5':
                schedules = self.scheduler.list_schedules()
                if schedules:
                    print("\n📋 Scheduled Tests:")
                    for i, sched in enumerate(schedules, 1):
                        if sched['type'] == 'once':
                            print(f"  {i}. One-time at {sched['time']}")
                        else:
                            print(f"  {i}. {sched['description']}")
                    
                    next_run = self.scheduler.get_next_run_time()
                    if next_run:
                        print(f"\n⏰ Next run: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"📧 Auto-email: Enabled")
                else:
                    print("\nℹ️  No scheduled tests")
            
            elif choice == '6':
                confirm = input("Clear all schedules? (y/n): ").strip().lower()
                if confirm == 'y':
                    self.scheduler.clear_all_schedules()
                    print("✅ All schedules cleared")
            
            elif choice == '7':
                return
            
            else:
                print("❌ Invalid choice")
        
        except ValueError:
            print("❌ Invalid input. Please enter numbers only.")
        except Exception as e:
            print(f"❌ Error: {e}")
    
    def send_email_report(self):
        """Send email report for the last execution"""
        print("\n" + "="*60)
        print("📧 SEND EMAIL REPORT")
        print("="*60)
        
        if not self.email_sender:
            print("❌ Email sender not initialized")
            return
        
        if not self.email_sender.enabled:
            print("❌ Email notifications are disabled in settings.yaml")
            print("   Update config/settings.yaml to enable email notifications")
            return
        
        if not self.last_execution_dir:
            print("❌ No execution results available. Run tests first.")
            return
        
        # Find the Excel report
        excel_files = list(self.last_execution_dir.glob("OTT_Playback_*.xlsx"))
        if not excel_files:
            excel_path = self.last_execution_dir / "test_results.xlsx"
            if not excel_path.exists():
                print(f"❌ No Excel report found in {self.last_execution_dir}")
                return
        else:
            excel_path = excel_files[0]
        
        print(f"\n📄 Report: {excel_path.name}")
        print(f"📁 Execution: {self.last_execution_dir.name}")
        print(f"📧 Recipients: {', '.join(self.email_sender.recipient_emails)}")
        
        confirm = input("\nSend email report? (y/n): ").strip().lower()
        if confirm == 'y':
            print("\n📤 Sending email...")
            if self.email_sender.send_report(str(excel_path), self.last_execution_dir.name):
                print("\n✅ Email sent successfully!")
            else:
                print("\n❌ Failed to send email. Check logs for details.")
        else:
            print("❌ Email sending cancelled")
    
def main():
    try:
        runner = InteractiveTestRunner()
        
        if not runner.check_setup():
            print("\n❌ Setup check failed. Please fix the issues above.")
            sys.exit(1)
        
        runner.main_menu()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        sys.exit(0)

if __name__ == "__main__":
    main()