"""
Pytest configuration for Fancode OTT Testing
Provides HTML reporting and custom test execution setup
"""

import pytest
from datetime import datetime
from pathlib import Path
import os
import pytest_html
import logging
import io
import sys


class LogCapture:
    """Custom log capture for HTML reports"""
    def __init__(self):
        self.logs = []
        self.handler = None
        self.original_stdout = None
        self.original_stderr = None
        
    def capture_start(self):
        """Start capturing logs"""
        # Create a custom handler to capture log messages
        self.handler = logging.StreamHandler(io.StringIO())
        self.handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.handler.setFormatter(formatter)
        
        # Add handler to root logger
        logging.getLogger().addHandler(self.handler)
        logging.getLogger().setLevel(logging.DEBUG)
        
        # Also capture stdout/stderr
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
    
    def capture_stop(self):
        """Stop capturing and return logs"""
        try:
            # Get log output
            if self.handler and hasattr(self.handler.stream, 'getvalue'):
                log_content = self.handler.stream.getvalue()
            else:
                log_content = ""
            
            # Get stdout/stderr
            stdout_content = sys.stdout.getvalue() if hasattr(sys.stdout, 'getvalue') else ""
            stderr_content = sys.stderr.getvalue() if hasattr(sys.stderr, 'getvalue') else ""
            
            # Restore original streams
            if self.original_stdout:
                sys.stdout = self.original_stdout
            if self.original_stderr:
                sys.stderr = self.original_stderr
            
            # Remove handler
            if self.handler:
                logging.getLogger().removeHandler(self.handler)
            
            # Combine all outputs
            all_logs = []
            if log_content.strip():
                all_logs.extend(log_content.strip().split('\\n'))
            if stdout_content.strip():
                all_logs.extend([f"[STDOUT] {line}" for line in stdout_content.strip().split('\\n')])
            if stderr_content.strip():
                all_logs.extend([f"[STDERR] {line}" for line in stderr_content.strip().split('\\n')])
            
            return all_logs
        
        except Exception as e:
            return [f"[LOG_CAPTURE_ERROR] {str(e)}"]


@pytest.fixture(autouse=True)
def setup_test_directories(request):
    """Create directories for test execution and screenshots"""
    # Create unique execution directory using environment variable or timestamp
    execution_id = os.getenv('EXECUTION_ID')
    if not execution_id:
        from datetime import datetime
        execution_id = datetime.now().strftime("Execution_%Y%m%d_%H%M%S")
    
    base_dir = Path("TestResults") / execution_id
    base_dir.mkdir(parents=True, exist_ok=True)
    
    # Add attributes to the test node
    request.node.execution_dir = base_dir
    request.node.screenshot_dir = base_dir / "screenshots"
    request.node.screenshot_dir.mkdir(exist_ok=True)
    
    # Initialize log capture for this test
    if not hasattr(request.node, 'log_capture'):
        request.node.log_capture = LogCapture()


def pytest_configure(config):
    """Configure pytest with custom settings"""
    # Set HTML report title
    config._metadata = {
        'Project': 'Fancode OTT Automation',
        'Tester': 'Automation Team',
        'Test Environment': 'Android TV'
    }


def pytest_html_report_title(report):
    """Customize HTML report title"""
    report.title = "Fancode OTT Test Execution Report"


def pytest_html_results_summary(prefix, summary, postfix):
    """Add custom summary to HTML report"""
    prefix.extend([
        "<h2>Test Execution Summary</h2>",
        "<p><strong>Execution Date:</strong> {}</p>".format(
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    ])


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Enhanced failure reporting with comprehensive log capture
    """
    # Capture logs before test execution
    if call.when == 'setup':
        # Initialize log capture for this test
        if not hasattr(item, '_log_records'):
            item._log_records = []
    
    outcome = yield
    report = outcome.get_result()
    
    # Capture log output
    log_output = []
    if hasattr(item, 'caplog') and hasattr(item.caplog, 'records'):
        for record in item.caplog.records:
            log_output.append(f"[{record.levelname}] {record.name}: {record.getMessage()}")
    
    # Add extra information to report
    extra = getattr(report, 'extras', [])
    
    if report.when == 'call':
        # Try to get comprehensive log information from different sources
        all_log_output = []
        
        # Get existing captured logs
        all_log_output.extend(log_output)
        
        # Get logs from pytest's captured sections
        if hasattr(report, 'sections'):
            for section_name, section_content in report.sections:
                if section_name in ['Captured stdout call', 'Captured stderr call', 'Captured log call']:
                    if section_content.strip():
                        all_log_output.append(f"=== {section_name} ===")
                        all_log_output.extend(section_content.strip().split('\n'))
        
        # Also check for any captured output in the report
        for attr in ['capstdout', 'capstderr', 'caplog']:
            if hasattr(report, attr):
                content = getattr(report, attr)
                if content and str(content).strip():
                    all_log_output.append(f"=== {attr.upper()} ===")
                    all_log_output.extend(str(content).strip().split('\n'))
        
        # Add comprehensive log information to HTML report
        if all_log_output:
            log_html = "<h3>🔍 Test Execution Logs & Output:</h3>"
            log_html += "<details open style='margin: 10px 0; border: 1px solid #ddd; border-radius: 5px;'>"
            log_html += "<summary style='cursor: pointer; background: #f0f8ff; padding: 10px; font-weight: bold; color: #0066cc;'>📄 Click to expand/collapse all logs and output</summary>"
            log_html += "<div style='max-height: 600px; overflow-y: auto; padding: 10px;'>"
            log_html += "<pre style='background: #f8f9fa; padding: 15px; margin: 0; font-family: monospace; font-size: 10px; white-space: pre-wrap; line-height: 1.4;'>"
            log_html += "\n".join(all_log_output)
            log_html += "</pre></div></details>"
            extra.append(pytest_html.extras.html(log_html))
        
        # Enhanced failure reporting
        if report.failed:
            # Add detailed failure information to HTML report
            failure_info = []
            
            if hasattr(report, 'longrepr') and report.longrepr:
                failure_info.append(f"<h3>Failure Details:</h3>")
                failure_info.append(f"<pre style='color: red; background: #fff5f5; padding: 10px; border-radius: 5px; border-left: 4px solid #f56565;'>{report.longrepr}</pre>")
            
            # Add device information if available
            if hasattr(item, 'funcargs') and 'request' in item.funcargs:
                request = item.funcargs['request']
                if hasattr(request, 'node') and hasattr(request.node, 'device_id'):
                    failure_info.append(f"<p><strong>Device ID:</strong> {getattr(request.node, 'device_id', 'Unknown')}</p>")
                
                if hasattr(request.node, 'screenshot_dir'):
                    screenshots_dir = request.node.screenshot_dir
                    if screenshots_dir.exists():
                        screenshots = list(screenshots_dir.glob("*.png"))
                        if screenshots:
                            failure_info.append(f"<p><strong>Screenshots captured:</strong> {len(screenshots)}</p>")
                            # Add latest screenshots to report
                            for i, screenshot in enumerate(sorted(screenshots, key=lambda x: x.stat().st_mtime)[-3:]):
                                screenshot_html = f'<img src="{screenshot.relative_to(Path.cwd())}" style="max-width: 300px; margin: 5px; border: 1px solid #ddd;"/>'
                                extra.append(pytest_html.extras.html(screenshot_html))
            
            # Add failure summary
            if failure_info:
                extra.append(pytest_html.extras.html("\n".join(failure_info)))
        
        elif report.passed:
            # Add success information with logs
            success_html = "<p style='color: green;'><strong>✅ Test Passed Successfully</strong></p>"
            if log_output:
                success_html += "<details style='margin-top: 10px;'>"
                success_html += "<summary style='cursor: pointer; color: #0066cc;'>📄 Click to view execution logs</summary>"
                success_html += "<pre style='background: #f8f9fa; padding: 15px; border-radius: 5px; margin-top: 10px; max-height: 300px; overflow-y: auto; font-family: monospace; font-size: 11px;'>"
                success_html += "\n".join(log_output)
                success_html += "</pre></details>"
            extra.append(pytest_html.extras.html(success_html))
    
    report.extras = extra


def pytest_sessionfinish(session, exitstatus):
    """
    Enhanced session finish with failure summary
    """
    try:
        print("\n" + "=" * 60)
        print("All tests completed!")
        
        # Print failure summary if any failures occurred
        if hasattr(session, 'testsfailed') and session.testsfailed > 0:
            print(f"\n⚠️  FAILURES DETECTED: {session.testsfailed} test(s) failed")
            print("📋 Check the following files for detailed failure information:")
            
            # Look for failure logs in TestResults directories
            test_results = Path("TestResults")
            if test_results.exists():
                for exec_dir in test_results.iterdir():
                    if exec_dir.is_dir():
                        failure_log = exec_dir / "failed_scenarios.log"
                        detailed_log = exec_dir / "detailed_failures.json"
                        if failure_log.exists():
                            print(f"   📄 {failure_log}")
                        if detailed_log.exists():
                            print(f"   📊 {detailed_log}")
        else:
            print("\n✅ All tests passed successfully!")
        
        print("=" * 60)
    
    except Exception as e:
        # Don't let session finish errors break anything
        print(f"Warning: Error in session finish hook: {e}")
        pass
