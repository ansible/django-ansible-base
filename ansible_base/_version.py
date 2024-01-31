import datetime
import subprocess

calver_now = datetime.datetime.now().strftime("%Y.%m.%d")
shaw = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).decode('ascii').strip()
version = f'{calver_now}-{shaw}'
