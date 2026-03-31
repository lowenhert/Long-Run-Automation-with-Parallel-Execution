#!/usr/bin/env python3
"""
Unified Interactive Test Runner
Supports module-based test execution with step-by-step Excel reporting.
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
            try:
                folder_name = folder.name
                if folder_name.startswith("Execution_"):
                    date_str = folder_name.split("_")[1]
                    folder_date = datetime.strptime(date_str, "%Y%m%d")
                    if folder_date < cutoff_date:
                        shutil.rmtree(folder)
                        deleted_count += 1
            except (ValueError, IndexError):
                continue

        if deleted_count > 0:
            print(f"🗑️  Cleaned up {deleted_count} test result(s) older than {days} days")

    def load_config(self):
        """Load settings from settings.yaml"""
        try:
            with open("config/settings.yaml") as f:
                self.settings = yaml.safe_load(f)
            print("✅ Loaded settings.yaml")
        except Exception as e:
            print(f"❌ Failed to load settings: {e}")
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
            print("✅ Scheduler initialized")
        except Exception as e:
            print(f"⚠️  Scheduler initialization failed: {e}")

    def _run_scheduled_tests(self):
        """Run all tests on all devices (called by scheduler)"""
        try:
            if not self.devices:
                print("⚠️  No devices available for scheduled test")
                return None
            exec_dir = self._run_parental_lock_test(self.devices)
            self._run_favourite_channels_test(self.devices, exec_dir)
            self._run_remote_pairing_test(self.devices, exec_dir)
            return exec_dir
        except Exception as e:
            print(f"❌ Error in scheduled test execution: {e}")
            return None

    def _send_scheduled_email(self, exec_dir):
        """Send email report after scheduled tests"""
        if not exec_dir or not self.email_sender or not self.email_sender.enabled:
            return
        try:
            excel_files = list(exec_dir.rglob("Long Run Automation report.xlsx"))
            if not excel_files:
                print(f"⚠️  No Excel report found in {exec_dir}")
                return
            print("\\n📧 Sending scheduled email report...")
            self.email_sender.send_report(str(excel_files[0]), exec_dir.name)
        except Exception as e:
            print(f"❌ Failed to send scheduled email: {e}")

    # ──────────────────────────────────────────────────────────────
    # Setup & Connectivity
    # ──────────────────────────────────────────────────────────────

    def check_setup(self):
        """Verify project setup"""
        print("🔧 Checking project setup...")

        try:
            self.devices = DeviceManager.get_connected_devices()
            if not self.devices:
                print("❌ No Android devices connected via ADB")
                return False
            print(f"✅ Found {len(self.devices)} connected device(s): {', '.join(self.devices)}")
        except Exception as e:
            print(f"❌ Device check failed: {e}")
            return False

        required_files = [
            "config/settings.yaml",
            "test/test_parental_lock_setup.py",
            "test/test_favourite_channels_setup.py",
            "test/test_remote_pairing.py",
        ]
        for fp in required_files:
            if Path(fp).exists():
                print(f"✅ {fp} exists")
            else:
                print(f"❌ {fp} missing")
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

                screenshot = device.take_screenshot(
                    f"connectivity_test_{device_id.replace(':', '_')}.png"
                )
                if screenshot:
                    print(f"  ✅ Screenshot test passed: {screenshot}")
                else:
                    print("  ❌ Screenshot test failed")
                    return False

                print("  📱 Testing navigation...")
                device.home()
                time.sleep(1)
                print("  ✅ Navigation test passed")

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

    def select_devices(self):
        """Let user select which devices to test on"""
        self.show_devices()
        while True:
            try:
                choice = input(
                    f"\nSelect devices (1-{len(self.devices)}, 'all', or comma-separated): "
                ).strip().lower()

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

    # ──────────────────────────────────────────────────────────────
    # Test Modules
    # ──────────────────────────────────────────────────────────────

    def _run_parental_lock_test(self, selected_devices):
        """Run the Parental Lock Setup test on selected devices."""
        exec_id = datetime.now().strftime("Execution_%Y%m%d_%H%M%S")
        test_file = "test/test_parental_lock_setup.py"

        print(f"\n🔒 Running Parental Lock Setup test")
        print(f"🆔 Execution ID: {exec_id}")

        for device_id in selected_devices:
            device_safe = device_id.replace(':', '_').replace('.', '_')
            exec_dir = Path("TestResults") / exec_id / f"device_{device_safe}"
            exec_dir.mkdir(parents=True, exist_ok=True)

            env = os.environ.copy()
            env["DEVICE_ID"] = device_id
            env["DEVICE_NAME"] = device_id
            env["TARGET_DEVICE"] = device_id
            env["EXECUTION_ID"] = exec_id

            cmd = [
                self.python_exe, "-m", "pytest",
                test_file,
                "-v", "--tb=short", "--capture=no",
                "--log-cli-level=DEBUG",
                "--log-cli-format=%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "--log-file-level=DEBUG",
                f"--log-file={exec_dir}/test_parental_lock.log",
                f"--html={exec_dir}/report_parental_lock.html",
                "--self-contained-html",
            ]
            print(f"  [{device_id}] Running parental lock test…")
            try:
                result = subprocess.run(
                    cmd, env=env, capture_output=True, text=True, timeout=30000
                )
                symbol = "✅" if result.returncode == 0 else "❌"
                print(
                    f"  [{device_id}] {symbol} Parental Lock "
                    f"{'PASSED' if result.returncode == 0 else 'FAILED'}"
                )
                if result.returncode != 0 and result.stderr:
                    print(f"  [{device_id}]   stderr: {result.stderr[:300]}")
            except subprocess.TimeoutExpired:
                print(f"  [{device_id}] ⏰ Parental Lock TIMED OUT")
            except Exception as e:
                print(f"  [{device_id}] ❌ Parental Lock ERROR: {e}")

        self.last_execution_dir = Path("TestResults") / exec_id
        print("\n🎉 Parental Lock test completed!")
        return self.last_execution_dir

    def _run_favourite_channels_test(self, selected_devices, existing_exec_dir=None):
        """Run the Favourite Channels Setup test on selected devices."""
        if existing_exec_dir:
            exec_id = existing_exec_dir.name
        else:
            exec_id = datetime.now().strftime("Execution_%Y%m%d_%H%M%S")
        test_file = "test/test_favourite_channels_setup.py"

        print(f"\n⭐ Running Favourite Channels Setup test")
        print(f"🆔 Execution ID: {exec_id}")

        for device_id in selected_devices:
            device_safe = device_id.replace(':', '_').replace('.', '_')
            exec_dir = Path("TestResults") / exec_id / f"device_{device_safe}"
            exec_dir.mkdir(parents=True, exist_ok=True)

            env = os.environ.copy()
            env["DEVICE_ID"] = device_id
            env["DEVICE_NAME"] = device_id
            env["TARGET_DEVICE"] = device_id
            env["EXECUTION_ID"] = exec_id

            cmd = [
                self.python_exe, "-m", "pytest",
                test_file,
                "-v", "--tb=short", "--capture=no",
                "--log-cli-level=DEBUG",
                "--log-cli-format=%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "--log-file-level=DEBUG",
                f"--log-file={exec_dir}/test_favourite_channels.log",
                f"--html={exec_dir}/report_favourite_channels.html",
                "--self-contained-html",
            ]
            print(f"  [{device_id}] Running favourite channels test…")
            try:
                result = subprocess.run(
                    cmd, env=env, capture_output=True, text=True, timeout=30000
                )
                symbol = "✅" if result.returncode == 0 else "❌"
                print(
                    f"  [{device_id}] {symbol} Favourite Channels "
                    f"{'PASSED' if result.returncode == 0 else 'FAILED'}"
                )
                if result.returncode != 0 and result.stderr:
                    print(f"  [{device_id}]   stderr: {result.stderr[:300]}")
            except subprocess.TimeoutExpired:
                print(f"  [{device_id}] ⏰ Favourite Channels TIMED OUT")
            except Exception as e:
                print(f"  [{device_id}] ❌ Favourite Channels ERROR: {e}")

        self.last_execution_dir = Path("TestResults") / exec_id
        print("\n🎉 Favourite Channels test completed!")
        return self.last_execution_dir

    def _run_remote_pairing_test(self, selected_devices, existing_exec_dir=None):
        """Run the Remote Pairing Check test on selected devices."""
        if existing_exec_dir:
            exec_id = existing_exec_dir.name
        else:
            exec_id = datetime.now().strftime("Execution_%Y%m%d_%H%M%S")
        test_file = "test/test_remote_pairing.py"

        print(f"\n📡 Running Remote Pairing Check test")
        print(f"🆔 Execution ID: {exec_id}")

        for device_id in selected_devices:
            device_safe = device_id.replace(':', '_').replace('.', '_')
            exec_dir = Path("TestResults") / exec_id / f"device_{device_safe}"
            exec_dir.mkdir(parents=True, exist_ok=True)

            env = os.environ.copy()
            env["DEVICE_ID"] = device_id
            env["DEVICE_NAME"] = device_id
            env["TARGET_DEVICE"] = device_id
            env["EXECUTION_ID"] = exec_id

            cmd = [
                self.python_exe, "-m", "pytest",
                test_file,
                "-v", "--tb=short", "--capture=no",
                "--log-cli-level=DEBUG",
                "--log-cli-format=%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "--log-file-level=DEBUG",
                f"--log-file={exec_dir}/test_remote_pairing.log",
                f"--html={exec_dir}/report_remote_pairing.html",
                "--self-contained-html",
            ]
            print(f"  [{device_id}] Running remote pairing check…")
            try:
                result = subprocess.run(
                    cmd, env=env, capture_output=True, text=True, timeout=30000
                )
                symbol = "✅" if result.returncode == 0 else "❌"
                print(
                    f"  [{device_id}] {symbol} Remote Pairing "
                    f"{'PASSED' if result.returncode == 0 else 'FAILED'}"
                )
                if result.returncode != 0 and result.stderr:
                    print(f"  [{device_id}]   stderr: {result.stderr[:300]}")
            except subprocess.TimeoutExpired:
                print(f"  [{device_id}] ⏰ Remote Pairing TIMED OUT")
            except Exception as e:
                print(f"  [{device_id}] ❌ Remote Pairing ERROR: {e}")

        self.last_execution_dir = Path("TestResults") / exec_id
        print("\n🎉 Remote Pairing check completed!")
        return self.last_execution_dir

    # ──────────────────────────────────────────────────────────────
    # Main Menu
    # ──────────────────────────────────────────────────────────────

    def main_menu(self):
        """Main interactive menu"""
        print("\n" + "=" * 60)
        print("🎬 TEST AUTOMATION RUNNER")
        print("=" * 60)

        while True:
            print("\nAvailable Test Modules:")
            print("  • Parental Lock Setup (Channel Lock)")
            print("  • Favourite Channels Setup")
            print("  • Remote Pairing Check")
            print("\nSelect an option:")
            print("1. 🔌 Test Device Connectivity")
            print("2. 🔒 Run Parental Lock Setup Test")
            print("3. ⭐ Run Favourite Channels Setup Test")
            print("4. 📡 Run Remote Pairing Check Test")
            print("5. 🚀 Run All Tests")
            print("6. 📅 Schedule Tests")
            print("7. 📧 Email Report (Last Execution)")
            print("8. ❌ Exit")

            try:
                choice = input("\nEnter your choice (1-8): ").strip()

                if choice == '1':
                    self.test_connectivity()
                    input("\nPress Enter to continue...")

                elif choice == '2':
                    selected_devices = self.select_devices()
                    self._run_parental_lock_test(selected_devices)

                    if (self.last_execution_dir and self.email_sender
                            and self.email_sender.enabled):
                        send_email = input(
                            "\n📧 Send email report? (y/n): "
                        ).strip().lower()
                        if send_email == 'y':
                            self.send_email_report()
                    input("\nPress Enter to continue...")

                elif choice == '3':
                    selected_devices = self.select_devices()
                    self._run_favourite_channels_test(selected_devices)

                    if (self.last_execution_dir and self.email_sender
                            and self.email_sender.enabled):
                        send_email = input(
                            "\n📧 Send email report? (y/n): "
                        ).strip().lower()
                        if send_email == 'y':
                            self.send_email_report()
                    input("\nPress Enter to continue...")

                elif choice == '4':
                    selected_devices = self.select_devices()
                    self._run_remote_pairing_test(selected_devices)

                    if (self.last_execution_dir and self.email_sender
                            and self.email_sender.enabled):
                        send_email = input(
                            "\n📧 Send email report? (y/n): "
                        ).strip().lower()
                        if send_email == 'y':
                            self.send_email_report()
                    input("\nPress Enter to continue...")

                elif choice == '5':
                    selected_devices = self.select_devices()
                    exec_dir = self._run_parental_lock_test(selected_devices)
                    self._run_favourite_channels_test(selected_devices, exec_dir)
                    self._run_remote_pairing_test(selected_devices, exec_dir)

                    if (self.last_execution_dir and self.email_sender
                            and self.email_sender.enabled):
                        send_email = input(
                            "\n📧 Send email report? (y/n): "
                        ).strip().lower()
                        if send_email == 'y':
                            self.send_email_report()
                    input("\nPress Enter to continue...")

                elif choice == '6':
                    self.schedule_tests_menu()
                    input("\nPress Enter to continue...")

                elif choice == '7':
                    self.send_email_report()
                    input("\nPress Enter to continue...")

                elif choice == '8':
                    print("👋 Goodbye!")
                    if self.scheduler:
                        self.scheduler.stop_scheduler()
                    sys.exit(0)

                else:
                    print("❌ Invalid choice. Please select 1-8.")

            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                sys.exit(0)
            except Exception as e:
                print(f"❌ Error: {e}")
                input("Press Enter to continue...")

    def schedule_tests_menu(self):
        """Schedule tests menu"""
        print("\n" + "=" * 60)
        print("📅 SCHEDULE TESTS")
        print("=" * 60)

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
                    if not self.scheduler.is_running:
                        self.scheduler.start_scheduler()
                        print("✅ Scheduler started in background")

            elif choice == '2':
                hours = int(input("Enter interval in hours: ").strip())
                if self.scheduler.schedule_recurring('hourly', hours):
                    print(f"✅ Tests scheduled every {hours} hour(s)")
                    if not self.scheduler.is_running:
                        self.scheduler.start_scheduler()
                        print("✅ Scheduler started in background")

            elif choice == '3':
                days = int(input("Enter interval in days: ").strip())
                run_time = input(
                    "Enter time (HH:MM, 24-hour format) or leave empty: "
                ).strip() or None
                if self.scheduler.schedule_recurring('daily', days, run_time):
                    msg = f"✅ Tests scheduled every {days} day(s)"
                    if run_time:
                        msg += f" at {run_time}"
                    print(msg)
                    if not self.scheduler.is_running:
                        self.scheduler.start_scheduler()
                        print("✅ Scheduler started in background")

            elif choice == '4':
                weeks = int(input("Enter interval in weeks: ").strip())
                run_time = input(
                    "Enter time (HH:MM, 24-hour format) or leave empty: "
                ).strip() or None
                if self.scheduler.schedule_recurring('weekly', weeks, run_time):
                    msg = f"✅ Tests scheduled every {weeks} week(s)"
                    if run_time:
                        msg += f" at {run_time}"
                    print(msg)
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
                        print(
                            f"\n⏰ Next run: {next_run.strftime('%Y-%m-%d %H:%M:%S')}"
                        )
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
        print("\n" + "=" * 60)
        print("📧 SEND EMAIL REPORT")
        print("=" * 60)

        if not self.email_sender:
            print("❌ Email sender not initialized")
            return
        if not self.email_sender.enabled:
            print("❌ Email notifications are disabled in settings.yaml")
            return
        if not self.last_execution_dir:
            print("❌ No execution results available. Run tests first.")
            return

        excel_files = list(self.last_execution_dir.rglob("Long Run Automation report.xlsx"))
        if not excel_files:
            print(f"❌ No Excel report found in {self.last_execution_dir}")
            return

        excel_path = excel_files[0]
        print(f"\n📄 Report: {excel_path.name}")
        print(f"📁 Execution: {self.last_execution_dir.name}")
        print(f"📧 Recipients: {', '.join(self.email_sender.recipient_emails)}")

        confirm = input("\nSend email report? (y/n): ").strip().lower()
        if confirm == 'y':
            print("\n📤 Sending email...")
            if self.email_sender.send_report(
                str(excel_path), self.last_execution_dir.name
            ):
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