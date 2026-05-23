import subprocess
import time
import socket
import os
import sys

def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except Exception:
        return False

def find_chrome():
    paths = [
        os.path.expandvars(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"C:\Users\%USERNAME%\AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

chrome = find_chrome()
if not chrome:
    print("Chrome not found")
    sys.exit(1)

profile_dir = os.path.abspath("profile_test")
os.makedirs(profile_dir, exist_ok=True)
port = 9222

print(f"Starting Chrome at {chrome}")
print(f"Profile: {profile_dir}")
print(f"Port: {port}")

proc = subprocess.Popen(
    [
        chrome,
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        "--start-maximized",
        "--new-window",
        "about:blank",
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    creationflags=0
)

print("Waiting for CDP port...")
for i in range(20):
    if _port_open("127.0.0.1", port):
        print(f"SUCCESS: Port {port} is open!")
        break
    time.sleep(1)
else:
    print(f"FAILED: Port {port} did not open.")

# Cleanup
print("Killing test chrome...")
subprocess.run(["taskkill", "/F", "/PID", str(proc.pid), "/T"])
