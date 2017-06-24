import sys, time, os, re
import pycurl, pexpect, socket
import subprocess
import shlex
from pipes import quote
from oslo_log import log
from multiprocessing import Process

LOG = log.getLogger(__name__)

actions = ["status", "on", "off", "reboot"]

options = {'--power-timeout': '20', '--power-wait': 2, '--retry-on': '1'}

EC_CONNECTION_LOST = "Failed: Connection lost"
EC_TIMED_OUT = "Failed: Connection timed out"
EC_WAITING_ON = "Failed: Timed out waiting to power ON"
EC_WAITING_OFF = "Failed: Timed out waiting to power OFF"

def create_command(action):
	cmd = options["--ipmitool-path"]
	cmd += " -I lanplus"
	cmd += " -H " + options["--ip"]
	cmd += " -U " + quote(options["--username"])
	cmd += " -P " + quote(options["--password"])
	cmd += " chassis power " + action

	return cmd

def run_command(command):
	try:
		process = subprocess.Popen(shlex.split(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	except OSError:
		sys.exit("ERROR: Unable to run %s\n" % command)

	thread = Process(target=process.wait)
	thread.start()
	thread.join(float(options["--power-timeout"]))
	if thread.is_alive():
		process.kill()
		sys.exit(EC_TIMED_OUT)

	status = process.wait()

	(pipe_stdout, pipe_stderr) = process.communicate()
	process.stdout.close()
	process.stderr.close()

	return (status, pipe_stdout, pipe_stderr)

def get_power_status():
	output = run_command(create_command("status"))
	match = re.search('[Cc]hassis [Pp]ower is [\\s]*([a-zA-Z]{2,3})', str(output))
	status = match.group(1) if match else None
	return status

def set_power_status():
	run_command(create_command(options["--action"]))
	return

def set_power_status_retry(retry_attempts=1):
	for _ in range(retry_attempts):
		set_power_status()
		time.sleep(int(options["--power-wait"]))

		for _ in range(int(options["--power-timeout"])):
			if get_power_status() != options["--action"]:
				time.sleep(1)
			else:
				return True
	return False

def fence_ipmilan(ipmitool_path, hostip, username, password, action):
    if action not in actions:
        sys.exit("Action not supported!")
    options['--action'] = action
    options['--ipmitool-path'] = ipmitool_path
    options['--ip'] = hostip
    options['--username'] = username
    options['--password'] = password

    status = get_power_status()
    try:
		if action == status:
			LOG.info("Success: Already %s" % (status.upper()))
			return True

		if action == "on":
			if set_power_status_retry(1 + int(options["--retry-on"])):
				LOG.info("Success: Powered ON")
				return True
			else:
				sys.exit(EC_WAITING_ON)
		elif action == "off":
			if set_power_status_retry():
				LOG.info("Success: Powered OFF")
				return True
			else:
				sys.exit(EC_WAITING_OFF)
		elif action == "reboot":
			power_on = False
			if status != "off":
				options["--action"] = "off"
				if not set_power_status_retry():
					sys.exit(EC_WAITING_OFF)

			options["--action"] = "on"
			try:
				power_on = set_power_status_retry(int(options["--retry-on"]))
			except Exception as ex:
				# an error occured during power ON phase in reboot
				# fence action was completed succesfully even in that case
				LOG.warn("%s", str(ex))

			if power_on == False:
				# this should not fail as node was fenced succesfully
				LOG.error(EC_WAITING_ON)

			LOG.info("Success: Rebooted")
			return True
		elif action == "status":
			sys.exit("Status: " + status.upper())
    except pexpect.EOF:
        LOG.error(EC_CONNECTION_LOST)
    except pexpect.TIMEOUT:
		LOG.error(EC_TIMED_OUT)
    except pycurl.error as ex:
		LOG.error("%s\n", str(ex))
    except socket.timeout as ex:
		LOG.error("%s\n", str(ex))
    return False

if __name__ == "__main__":
	print(fence_ipmilan(ipmitool_path='/usr/bin/ipmitool', hostip='*.*.*.*', username='username', password="password", action="status"))
