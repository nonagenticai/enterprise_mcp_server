import os
import subprocess


def run_user_command(user_cmd):
    # VULN: command injection via shell=True with untrusted input (bandit B602, HIGH)
    return subprocess.Popen(user_cmd, shell=True)


def run_os(user_cmd):
    # VULN: os.system with untrusted input (bandit B605, HIGH)
    return os.system(user_cmd)
