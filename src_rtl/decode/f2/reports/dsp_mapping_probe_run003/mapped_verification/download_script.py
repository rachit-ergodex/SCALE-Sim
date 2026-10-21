from pathlib import Path
import base64,concurrent.futures,hashlib,json,subprocess,time,sys
metadata=json.loads(Path(sys.argv[1]).read_text())
root=Path('/private/tmp/scalesim-mapped-equivalence-download');root.mkdir(exist_ok=True)
helper='/private/tmp/scalesim_m7a_ssm.py'
remote=metadata['archive'];size=metadata['bytes'];expected=metadata['sha256']
def chunk(i):
 script=root/f'chunk-{i:03}.sh'
 script.write_text("python3 - <<'INNER'\nfrom pathlib import Path\nimport base64\np=Path("+repr(remote)+")\nwith p.open('rb') as f:\n f.seek("+str(i*9000)+")\n print(base64.b64encode(f.read(9000)).decode())\nINNER\n")
 command=subprocess.check_output(['python3',helper,'send',str(script)],text=True).strip()
 for attempt in range(30):
  proc=subprocess.run(['python3',helper,'get',command],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  if proc.returncode:time.sleep(1);continue
  result=json.loads(proc.stdout)
  if result['Status']=='Success':break
  if result['Status'] not in ('Pending','InProgress','Delayed'):raise RuntimeError(result)
  time.sleep(1)
 else:raise RuntimeError('Timeout '+command)
 data=base64.b64decode(result['Output'].strip(),validate=True)
 assert len(data)==min(9000,size-i*9000),(i,len(data))
 (root/f'chunk-{i:03}.bin').write_bytes(data)
 print('Downloaded chunk',i,'bytes',len(data),flush=True)
 return {'chunk':i,'command':command,'bytes':len(data)}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 records=list(pool.map(chunk,range((size+8999)//9000)))
data=b''.join((root/f'chunk-{i:03}.bin').read_bytes() for i in range(len(records)))
assert hashlib.sha256(data).hexdigest()==expected
archive=root/'mapped-equivalence-evidence-002.tar.gz';archive.write_bytes(data)
(root/'download.json').write_text(json.dumps({'archive':str(archive),'remote_archive':remote,'sha256':expected,'bytes':len(data),'chunks':records},indent=2)+'\n')
print('VERIFIED',expected,'bytes',len(data),flush=True)
