"""End-to-end test of the built executable over real HTTP and real inference."""
import json
import re
import subprocess
import sys
import time
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parent.parent
if hasattr(sys.stdout,'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def main():
    home=ROOT/'.pathocr-packaged'
    home.mkdir(exist_ok=True)
    url_file=home/'session-url.txt'
    url_file.unlink(missing_ok=True)
    exe=ROOT/'dist/PathOCR'/('PathOCR.exe' if sys.platform=='win32' else 'PathOCR')
    start=time.monotonic()
    with (home/'app.log').open('w',encoding='utf-8') as log:
        proc=subprocess.Popen([str(exe),'--no-browser','--home',str(home)],stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        try:
            for _ in range(60):
                if url_file.exists():
                    break
                if proc.poll() is not None:
                    raise RuntimeError('Packaged application failed: '+(home/'app.log').read_text(encoding='utf-8'))
                time.sleep(1)
            url=url_file.read_text(encoding='utf-8')
            base=url.split('/?')[0]
            with httpx.Client(timeout=60,trust_env=False) as client:
                for _ in range(30):
                    try:
                        client.get(url).raise_for_status()
                        break
                    except httpx.HTTPError:
                        time.sleep(.5)
                state=client.get(base+'/api/state').json()
                assert state['runtime']['installed'],state
                settings=state['settings']
                settings['output_dir']=str(home/'output')
                client.put(base+'/api/settings',json=settings).raise_for_status()
                for resource in ['/static/style.css','/static/app.js','/static/vendor/marked.js','/static/vendor/purify.js']:
                    client.get(base+resource).raise_for_status()
                with (ROOT/'.pathocr-smoke/sample.pdf').open('rb') as f:
                    response=client.post(base+'/api/jobs',files={'file':('sample.pdf',f,'application/pdf')})
                response.raise_for_status()
                jid=response.json()['id']
                previous=None
                for _ in range(900):
                    state=client.get(base+'/api/state').json()
                    job=next(j for j in state['jobs'] if j['id']==jid)
                    revision=(job['status'],job['done'])
                    if revision!=previous:
                        print(revision,flush=True)
                        previous=revision
                    if job['status'] not in ('queued','running'):
                        break
                    time.sleep(1)
                assert job['status']=='completed',job
                text=client.get(base+f'/api/jobs/{jid}/markdown').json()['text']
                assert '42' in re.sub(r'\s+','',text) and '128' in re.sub(r'\s+','',text) and '中文' in text,text
                assert Path(job['output']).read_text(encoding='utf-8')==text
                client.get(base+f'/api/jobs/{jid}/page/2').raise_for_status()
                download=client.get(base+f'/api/jobs/{jid}/download')
                download.raise_for_status()
                assert download.text.replace('\r\n','\n')==text
                result=dict(job=job,seconds=round(time.monotonic()-start,2),executable=str(exe))
                result['runtime']=state['runtime']
                print('Active backend:',state['runtime'],flush=True)
                (home/'smoke-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                print(text,flush=True)
                print('Packaged real OCR passed',result['seconds'],'seconds',flush=True)
                client.post(base+'/api/shutdown').raise_for_status()
                proc.wait(timeout=30)
                assert proc.returncode==0,proc.returncode
        finally:
            if proc.poll() is None:
                try:
                    with httpx.Client(timeout=5,trust_env=False) as cleanup:
                        cleanup.get(url)
                        cleanup.post(base+'/api/shutdown')
                    proc.wait(timeout=30)
                except Exception:
                    proc.terminate()
                    proc.wait(timeout=30)


if __name__=='__main__':
    main()
