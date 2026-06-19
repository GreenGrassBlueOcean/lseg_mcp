import time, urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
run_id = 25660220616

while True:
  try:
    req = urllib.request.Request(f'https://api.github.com/repos/GreenGrassBlueOcean/lseg_mcp/actions/runs/{run_id}/jobs')
    jobs = json.loads(urllib.request.urlopen(req, context=ctx).read().decode('utf-8'))['jobs']
    win_job = next(j for j in jobs if 'windows' in j['name'].lower() and 'launch' in j['name'].lower())
    print(f'Status: {win_job["status"]}, Conclusion: {win_job.get("conclusion")}')
    if win_job['status'] == 'completed':
      req_log = urllib.request.Request(f'https://api.github.com/repos/GreenGrassBlueOcean/lseg_mcp/actions/jobs/{win_job["id"]}/logs', headers={'User-Agent': 'Mozilla/5.0'})
      try:
          print(urllib.request.urlopen(req_log, context=ctx).read().decode('utf-8'))
      except Exception as ex:
          print("Log fetch error:", ex)
      break

  except Exception as e:
    print(e)
  time.sleep(10)
