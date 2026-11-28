#!/usr/bin/env python3
"""sudo_run.py NODE 'shell command' : run a command as root on a Spark; password from the vault via stdin, never printed."""
import subprocess, sys, os, json
BW='/Users/agent/.hermes/bin/vaultwarden-bw'
node, cmd = sys.argv[1], sys.argv[2]
item = subprocess.run([BW,'get','item','Spark4 SSH (gx10-395e)','--raw'],capture_output=True,text=True)
pw = json.loads(item.stdout)['login']['password']
p = subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',node,"sudo -S -p '' bash -c "+__import__('shlex').quote(cmd)],
                   input=pw+'\n',capture_output=True,text=True,timeout=int(os.environ.get('T','280')))
out=(p.stdout+p.stderr).replace(pw,'***')
print(out.rstrip()); sys.exit(p.returncode)
