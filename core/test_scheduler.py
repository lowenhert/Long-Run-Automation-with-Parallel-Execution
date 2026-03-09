"""
Test Scheduler Module for OTT Playback Tests
Schedules automated test execution at specified times or intervals
"""

import schedule
import time
import threading
from datetime import datetime
import logging

log = logging.getLogger(__name__)


class TestScheduler:
    def __init__(self, test_runner_callback, email_callback=None):
        """
        Initialize test scheduler
        
        Args:
            test_runner_callback: Function to call when scheduled test should run
            email_callback: Function to call after test completion to send email
        """
        self.test_runner_callback = test_runner_callback
        self.email_callback = email_callback
        self.scheduler_thread = None
        self.is_running = False
        self.scheduled_jobs = []
        self.auto_email = True  # Automatically send email after scheduled tests
    
    def schedule_once(self, run_time):
        """
        Schedule a one-time test execution
        
        Args:
            run_time: Time string in HH:MM format (24-hour)
            
        Returns:
            bool: True if scheduled successfully
        """
        try:
            schedule.every().day.at(run_time).do(self._run_scheduled_test).tag('once')
            
            self.scheduled_jobs.append({
                'type': 'once',
                'time': run_time,
                'scheduled_at': datetime.now()
            })
            
            log.info(f"✅ Test scheduled for {run_time}")
            return True
            
        except Exception as e:
            log.error(f"❌ Failed to schedule test: {e}")
            return False
    
    def schedule_recurring(self, interval_type, interval_value, run_time=None):
        """
        Schedule recurring test execution
        
        Args:
            interval_type: 'hourly', 'daily', 'weekly'
            interval_value: Number of hours/days/weeks between executions
            run_time: For daily/weekly, specific time in HH:MM format
            
        Returns:
            bool: True if scheduled successfully
        """
        try:
            if interval_type == 'hourly':
                schedule.every(interval_value).hours.do(self._run_scheduled_test).tag('recurring')
                schedule_desc = f"every {interval_value} hour(s)"
                
            elif interval_type == 'daily':
                if run_time:
                    schedule.every(interval_value).days.at(run_time).do(self._run_scheduled_test).tag('recurring')
                    schedule_desc = f"every {interval_value} day(s) at {run_time}"
                else:
                    schedule.every(interval_value).days.do(self._run_scheduled_test).tag('recurring')
                    schedule_desc = f"every {interval_value} day(s)"
                    
            elif interval_type == 'weekly':
                if run_time:
                    schedule.every(interval_value).weeks.at(run_time).do(self._run_scheduled_test).tag('recurring')
                    schedule_desc = f"every {interval_value} week(s) at {run_time}"
                else:
                    schedule.every(interval_value).weeks.do(self._run_scheduled_test).tag('recurring')
                    schedule_desc = f"every {interval_value} week(s)"
            else:
                log.error(f"❌ Invalid interval type: {interval_type}")
                return False
            
            self.scheduled_jobs.append({
                'type': 'recurring',
                'interval_type': interval_type,
                'interval_value': interval_value,
                'time': run_time,
                'description': schedule_desc,
                'scheduled_at': datetime.now()
            })
            
            log.info(f"✅ Recurring test scheduled: {schedule_desc}")
            return True
            
        except Exception as e:
            log.error(f"❌ Failed to schedule recurring test: {e}")
            return False
    
    def _run_scheduled_test(self):
        """Internal method called by scheduler to execute tests"""
        try:
            log.info(f"🕐 Scheduled test starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"\n" + "="*60)
            print(f"🕐 SCHEDULED TEST EXECUTION STARTED")
            print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("="*60 + "\n")
            
            # Call the test runner callback
            exec_dir = self.test_runner_callback()
            
            log.info("✅ Scheduled test completed")
            print(f"\n" + "="*60)
            print(f"✅ SCHEDULED TEST EXECUTION COMPLETED")
            print("="*60 + "\n")
            
            # Automatically send email if callback is provided and auto_email is True
            if self.auto_email and self.email_callback and exec_dir:
                print("📧 Automatically sending email report...")
                self.email_callback(exec_dir)
            
        except Exception as e:
            log.error(f"❌ Error during scheduled test execution: {e}")
            print(f"❌ Scheduled test failed: {e}")
    
    def start_scheduler(self):
        """Start the scheduler in a background thread"""
        if self.is_running:
            log.warning("Scheduler is already running")
            return False
        
        self.is_running = True
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()
        log.info("✅ Scheduler started in background")
        return True
    
    def _scheduler_loop(self):
        """Background loop that checks for scheduled jobs"""
        while self.is_running:
            schedule.run_pending()
            time.sleep(30)  # Check every 30 seconds
    
    def stop_scheduler(self):
        """Stop the scheduler"""
        self.is_running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        log.info("✅ Scheduler stopped")
    
    def clear_all_schedules(self):
        """Clear all scheduled jobs"""
        schedule.clear()
        self.scheduled_jobs = []
        log.info("✅ All schedules cleared")
    
    def list_schedules(self):
        """Return list of all scheduled jobs"""
        return self.scheduled_jobs
    
    def get_next_run_time(self):
        """Get the next scheduled run time"""
        jobs = schedule.get_jobs()
        if not jobs:
            return None
        
        next_run = min(job.next_run for job in jobs)
        return next_run
