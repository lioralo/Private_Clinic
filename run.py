#!/usr/bin/env python3
"""
Auto runner for Private Clinic Management System
Handles installation, testing, and running the application
"""

import subprocess
import sys
import os
import argparse
import signal
import atexit
import time
import psutil
import socket
from pathlib import Path


class AutoRunner:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.root_dir = Path(__file__).parent
        self.app_process = None
        self.shutting_down = False
        
        # Register cleanup on exit
        atexit.register(self.cleanup)
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
    def log(self, message, level="INFO"):
        """Print log messages"""
        print(f"[{level}] {message}", flush=True)
    
    def _signal_handler(self, signum, frame):
        """Handle interrupt signals gracefully"""
        if self.shutting_down:
            return
        self.shutting_down = True
        self.log("Shutdown signal received, terminating application...", level="WARNING")
        self.cleanup()
        sys.exit(0)
    
    def cleanup(self):
        """Terminate the app process and close the port"""
        if not self.app_process:
            return
            
        try:
            # Check if process is still running
            if self.app_process.poll() is None:
                self.log("Closing application and releasing port...")
                
                # Try to terminate gracefully first
                try:
                    self.app_process.terminate()
                    self.app_process.wait(timeout=3)
                    self.log("✓ Application terminated gracefully", level="SUCCESS")
                    return
                except subprocess.TimeoutExpired:
                    pass
                
                # If that didn't work, kill the process group
                try:
                    # Get the process to find child processes
                    parent = psutil.Process(self.app_process.pid)
                    children = parent.children(recursive=True)
                    
                    # Kill children first
                    for child in children:
                        try:
                            child.terminate()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    
                    # Give them time to die
                    gone, alive = psutil.wait_procs(children, timeout=2)
                    
                    # Force kill any remaining
                    for child in alive:
                        try:
                            child.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    
                    # Kill parent
                    self.app_process.kill()
                    self.app_process.wait(timeout=2)
                    self.log("✓ Application killed forcefully", level="SUCCESS")
                    
                except (psutil.NoSuchProcess, Exception) as e:
                    self.log(f"Error killing process: {e}", level="WARNING")
                    try:
                        self.app_process.kill()
                        self.app_process.wait()
                    except:
                        pass
                
                # Give the port time to be released
                time.sleep(0.5)
        except Exception as e:
            self.log(f"Cleanup error: {e}", level="WARNING")
    
    def run_command(self, cmd, description):
        """Execute shell command with error handling"""
        self.log(f"Running: {description}")
        if self.verbose:
            self.log(f"Command: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, check=True, cwd=self.root_dir)
            self.log(f"✓ {description} completed", level="SUCCESS")
            return True
        except subprocess.CalledProcessError as e:
            self.log(f"✗ Failed to {description}", level="ERROR")
            return False
    
    def install_dependencies(self):
        """Install required dependencies from requirements.txt"""
        requirements_path = self.root_dir / "requirements.txt"
        
        if not requirements_path.exists():
            self.log("requirements.txt not found", level="WARNING")
            return False
        
        return self.run_command(
            [sys.executable, "-m", "pip", "install", "-q", "-r", str(requirements_path)],
            "install dependencies"
        )
    
    def run_tests(self):
        """Run the test suite"""
        test_file = self.root_dir / "test_app.py"
        
        if not test_file.exists():
            self.log("test_app.py not found", level="WARNING")
            return False
        
        return self.run_command(
            [sys.executable, str(test_file)],
            "run tests"
        )

    def is_port_in_use(self, port, host="127.0.0.1"):
        """Return True when a TCP port is already occupied."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            return s.connect_ex((host, port)) == 0

    def find_available_port(self, start_port=5000, max_tries=100):
        """Find an open TCP port, starting from start_port."""
        for port in range(start_port, start_port + max_tries):
            if not self.is_port_in_use(port):
                return port
        raise RuntimeError(f"No available port found in range {start_port}-{start_port + max_tries - 1}")
    
    def run_app(self):
        """Start the Flask application"""
        app_file = self.root_dir / "app.py"
        
        if not app_file.exists():
            self.log("app.py not found", level="ERROR")
            return False

        try:
            requested_port = int(os.environ.get("PORT", "5000"))
        except ValueError:
            requested_port = 5000

        port = self.find_available_port(requested_port)
        if port != requested_port:
            self.log(f"Port {requested_port} is in use. Falling back to port {port}.", level="WARNING")
        
        self.log(f"Starting application on http://127.0.0.1:{port}")
        self.log("Press Ctrl+C to stop the application")
        
        try:
            env = os.environ.copy()
            env["PORT"] = str(port)
            self.app_process = subprocess.Popen(
                [sys.executable, str(app_file)],
                cwd=self.root_dir,
                env=env
            )
            self.log("✓ Application started (PID: {})".format(self.app_process.pid), level="SUCCESS")
            
            # Wait for the process to complete
            self.app_process.wait()
            return self.app_process.returncode == 0
        except Exception as e:
            self.log(f"Failed to start application: {e}", level="ERROR")
            return False
    
    def execute(self, install=True, test=False, run=True):
        """Execute the auto runner pipeline"""
        self.log("=" * 50)
        self.log("Private Clinic Management System - Auto Runner")
        self.log("=" * 50)
        
        if install:
            if not self.install_dependencies():
                return False
        
        if test:
            if not self.run_tests():
                return False
        
        if run:
            if not self.run_app():
                return False
        
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Auto runner for Private Clinic Management System"
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip dependency installation"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run tests before starting the app"
    )
    parser.add_argument(
        "--test-only",
        action="store_true",
        help="Run tests and exit (don't start the app)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    runner = AutoRunner(verbose=args.verbose)
    
    success = runner.execute(
        install=not args.skip_install,
        test=args.test or args.test_only,
        run=not args.test_only
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
