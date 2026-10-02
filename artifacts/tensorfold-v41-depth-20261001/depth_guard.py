import concurrent.futures as cf, json, subprocess, time, urllib.request
nodes=['forge','anvil','ember','flame']
def read(node):
    cmd=['cat','/proc/meminfo'] if node=='forge' else ['ssh','-n','-o','BatchMode=yes','-o','ConnectTimeout=5',node,'cat /proc/meminfo']
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=10)
    p.check_returncode()
    return int(next(x.split()[1] for x in p.stdout.splitlines() if x.startswith('MemAvailable:')))/1048576
end=time.monotonic()+3600
low={n:0 for n in nodes}
while time.monotonic()<end:
    with cf.ThreadPoolExecutor(4) as pool:
        try: mem=dict(zip(nodes,pool.map(read,nodes)))
        except Exception as exc:
            print(json.dumps({'error':str(exc)}),flush=True); time.sleep(5); continue
    print(json.dumps({'time':time.time(),'available_gib':mem}),flush=True)
    for n,v in mem.items(): low[n]=low[n]+1 if v<3 else 0
    if max(low.values())>=2:
        print('ABORT: available memory below 3 GiB on two samples',flush=True)
        def stop(n):
            cmd=['docker','kill','dsv41-head'] if n=='forge' else ['ssh','-n',n,'docker kill dsv41-worker']
            return subprocess.run(cmd,capture_output=True,text=True,timeout=20).returncode
        with cf.ThreadPoolExecutor(4) as pool: list(pool.map(stop,nodes))
        raise SystemExit(2)
    time.sleep(5)
