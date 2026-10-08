"""Real two-page model test. Outputs remain in .pathocr-smoke for inspection."""
import json
import sys
import time
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
if hasattr(sys.stdout,'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import fitz
from fastapi.testclient import TestClient
from pathocr.app import create_app


def main():
    home=ROOT/'.pathocr-smoke'
    app=create_app(home,'smoke-token')
    settings=app.state.store.settings()
    settings['output_dir']=str(home/'output')
    app.state.store.save_settings(settings)
    with fitz.open() as doc:
        p=doc.new_page(width=595,height=842)
        p.insert_text((50,70),'PathOCR validation',fontsize=24)
        p.insert_text((50,120),'This document is processed locally.',fontsize=14)
        p.insert_text((50,160),'Invoice total: 42 USD',fontsize=14)
        p=doc.new_page(width=595,height=842)
        p.insert_text((50,70),'中文识别测试',fontname='china-s',fontsize=24)
        p.insert_text((50,120),'默认保存为 Markdown，支持批量处理。',fontname='china-s',fontsize=16)
        p.insert_text((50,165),'金额：128 元',fontname='china-s',fontsize=16)
        pdf=doc.tobytes()
        doc.save(home/'sample.pdf')
    start=time.monotonic()
    with TestClient(app) as client:
        client.get('/?token=smoke-token')
        response=client.post('/api/jobs',files={'file':('sample.pdf',pdf,'application/pdf')})
        response.raise_for_status()
        jid=response.json()['id']
        previous=None
        for _ in range(900):
            job=app.state.store.job(jid)
            revision=(job['status'],job['done'])
            if revision!=previous:
                print(revision,flush=True)
                previous=revision
            if job['status'] not in ('running','queued'):
                break
            time.sleep(1)
        if job['status']!='completed':
            raise RuntimeError(json.dumps(job,ensure_ascii=False))
        text=Path(job['output']).read_text(encoding='utf-8')
        print(text)
        normalized = re.sub(r'\s+','',text)
        assert '42' in normalized and '128' in normalized and '中文' in normalized,text
        (home/'smoke-result.json').write_text(json.dumps(dict(job=job,seconds=round(time.monotonic()-start,2)),ensure_ascii=False,indent=2),encoding='utf-8')
        print('Real OCR passed',flush=True)
    app.state.store.db.close()


if __name__=='__main__':
    main()
