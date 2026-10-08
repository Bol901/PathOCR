"""Compare the same PDF, model, rendering and generation settings on CPU/GPU."""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
if hasattr(sys.stdout,'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from fastapi.testclient import TestClient
from pathocr.app import create_app


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['auto','cpu','cuda','vulkan'],default='auto')
    args=parser.parse_args()
    home=ROOT/f'.pathocr-bench-{args.mode}'
    app=create_app(home,'benchmark-token')
    settings=app.state.store.settings()
    settings.update(acceleration=args.mode,gpu_layers=0 if args.mode=='cpu' else 999,output_dir=str(home/'output'))
    app.state.store.save_settings(settings)
    try:
        with TestClient(app) as client:
            client.get('/?token=benchmark-token')
            start=time.monotonic()
            with (ROOT/'.pathocr-smoke/sample.pdf').open('rb') as f:
                response=client.post('/api/jobs',files={'file':('sample.pdf',f,'application/pdf')})
            response.raise_for_status()
            jid=response.json()['id']
            previous=None
            for _ in range(9000):
                job=app.state.store.job(jid)
                revision=(job['status'],job['done'])
                if previous!=revision:
                    print(revision,flush=True)
                    previous=revision
                if job['status'] not in ('queued','running'):
                    break
                time.sleep(.1)
            elapsed=round(time.monotonic()-start,2)
            assert job['status']=='completed',job
            engine=app.state.runtime.status()
            text=Path(job['output']).read_text(encoding='utf-8')
            assert '42' in text and '128' in re.sub(r'\s+','',text) and '中文' in text,text
            result=dict(seconds=elapsed,mode=args.mode,runtime=engine,job=job)
            (home/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
            if args.mode!='cpu':
                assert engine['backend']!='cpu' and engine['offloaded_layers']>0,engine
    finally:
        app.state.store.db.close()


if __name__=='__main__':
    main()
