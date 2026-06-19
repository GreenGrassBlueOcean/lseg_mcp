import time, subprocess, sys
print("Starting run_server.cmd...")
proc = subprocess.Popen(['cmd.exe', '/c', 'run_server.cmd'], stdin=subprocess.PIPE, stdout=sys.stdout, stderr=sys.stderr)
time.sleep(10)
print('poll:', proc.poll())
if proc.poll() is None:
    proc.terminate()
