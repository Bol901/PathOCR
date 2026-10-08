import base64
import io
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from pathocr.app import create_app
from pathocr.storage import Store


def make_pdf(pages=2):
    with fitz.open() as doc:
        for n in range(pages):
            p = doc.new_page()
            p.insert_text((50,70),f'Test document page {n+1}')
        return doc.tobytes()


class ModelHandler(BaseHTTPRequestHandler):
    calls = []
    finish_reason = 'stop'
    fail_first = False

    def log_message(self,*args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        type(self).calls.append(body)
        if type(self).fail_first and len(type(self).calls)==1:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error":"CUDA out of memory"}')
            return
        self.send_response(200)
        self.send_header('Content-Type','text/event-stream')
        self.end_headers()
        chunks = [dict(choices=[dict(delta=dict(content='# Test\n\n<table><tr><td>42</td></tr></table>'),finish_reason=None)]),dict(choices=[dict(delta={},finish_reason=type(self).finish_reason)])]
        for chunk in chunks:
            self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n')


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.home = Path(self.tmp.name)
        self.app = create_app(self.home,'test-token',auto_setup=False)
        settings = self.app.state.store.settings()
        settings['output_dir'] = str(self.home/'output')
        self.app.state.store.save_settings(settings)
        ModelHandler.calls = []
        ModelHandler.finish_reason = 'stop'
        ModelHandler.fail_first = False
        self.model = ThreadingHTTPServer(('127.0.0.1',0),ModelHandler)
        threading.Thread(target=self.model.serve_forever,daemon=True).start()
        self.app.state.runtime.port = self.model.server_port
        self.app.state.runtime.ensure = lambda: None
        self.app.state.runtime.status = lambda: dict(installed=True,status='ready',message='test')
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.client.get('/?token=test-token')

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.model.shutdown()
        self.model.server_close()
        self.app.state.store.db.close()
        self.tmp.cleanup()

    def upload(self,name='test.pdf',pages=2):
        r = self.client.post('/api/jobs',files={'file':(name,make_pdf(pages),'application/pdf')})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()['id']

    def wait(self,jid):
        for _ in range(200):
            job = self.app.state.store.job(jid)
            if job['status'] not in ('running','queued'):
                return job
            time.sleep(.05)
        self.fail('Worker did not complete')

    def test_real_pdf_stream_protocol_and_autosave(self):
        jid = self.upload()
        job = self.wait(jid)
        self.assertEqual(job['status'],'completed',job['error'])
        self.assertEqual(job['done'],2)
        result = Path(job['output']).read_text(encoding='utf-8')
        self.assertIn('<!-- page 2 -->',result)
        self.assertIn('<table>',result)
        self.assertEqual(len(ModelHandler.calls),2)
        call = ModelHandler.calls[0]
        self.assertTrue(call['stream'])
        data = call['messages'][0]['content'][1]['image_url']['url']
        self.assertTrue(base64.b64decode(data.split(',')[1]).startswith(b'\x89PNG'))
        self.assertEqual(self.client.get(f'/api/jobs/{jid}/download').status_code,200)
        self.assertIn('page 2',self.client.get(f'/api/jobs/{jid}/markdown').json()['text'])
        self.assertEqual(self.client.get(f'/api/jobs/{jid}/page/1').headers['content-type'],'image/png')
        self.assertEqual(self.client.get(f'/api/jobs/{jid}/page/0').status_code,404)

    def test_invalid_and_encrypted_pdf(self):
        for name,data in [('test.txt',b'abc'),('test.pdf',b'not a PDF')]:
            self.assertEqual(self.client.post('/api/jobs',files={'file':(name,data)}).status_code,400)
        with fitz.open() as doc:
            doc.new_page()
            data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,user_pw='secret',owner_pw='owner')
        self.assertEqual(self.client.post('/api/jobs',files={'file':('locked.pdf',data)}).status_code,400)
        self.assertEqual(len(list((self.home/'uploads').glob('*'))),0)

    def test_same_names_and_path_traversal(self):
        a,b = self.upload('../../same.pdf',1),self.upload('../../same.pdf',1)
        ja,jb = self.wait(a),self.wait(b)
        self.assertNotEqual(ja['output'],jb['output'])
        self.assertEqual(Path(ja['output']).parent,self.home/'output')
        self.assertEqual(ja['name'],'same.pdf')

    def test_interrupted_retry_skips_completed_pages(self):
        jid = self.upload()
        job = self.wait(jid)
        folder = self.app.state.worker.partial(jid).parent
        (folder/'000002.md').unlink()
        self.app.state.store.update(jid,status='interrupted',done=1)
        ModelHandler.calls = []
        self.assertEqual(self.client.post(f'/api/jobs/{jid}/retry').status_code,200)
        self.assertEqual(self.wait(jid)['status'],'completed')
        self.assertEqual(len(ModelHandler.calls),1)

    def test_truncation_is_failure(self):
        ModelHandler.finish_reason='length'
        job=self.wait(self.upload(pages=1))
        self.assertEqual(job['status'],'error')
        self.assertFalse(Path(job['output']).exists())

    def test_gpu_inference_oom_retries_current_page_on_cpu(self):
        ModelHandler.fail_first=True
        backend=['cuda']
        calls=[]
        self.app.state.runtime.status=lambda:dict(installed=True,status='ready',backend=backend[0])
        def fallback(reason):
            calls.append(str(reason))
            backend[0]='cpu'
        self.app.state.runtime.fallback_to_cpu=fallback
        job=self.wait(self.upload(pages=1))
        self.assertEqual(job['status'],'completed',job['error'])
        self.assertEqual(len(ModelHandler.calls),2)
        self.assertEqual(len(calls),1)
        self.assertEqual(job['done'],1)

    def test_incomplete_stream_is_not_saved_as_success(self):
        ModelHandler.finish_reason=None
        job=self.wait(self.upload(pages=1))
        self.assertEqual(job['status'],'error')
        self.assertFalse(Path(job['output']).exists())

    def test_cancel_queued(self):
        worker=self.app.state.worker
        original=worker.process
        gate=threading.Event()
        worker.process=lambda j:(gate.wait(3),original(j))[-1]
        first=self.upload(pages=1)
        second=self.upload(pages=1)
        self.client.post(f'/api/jobs/{second}/cancel')
        gate.set()
        self.wait(first)
        self.assertEqual(self.app.state.store.job(second)['status'],'cancelled')

    def test_security_and_settings(self):
        self.assertEqual(TestClient(self.app).get('/api/state').status_code,401)
        self.assertEqual(self.client.get('/api/state',headers={'host':'evil.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/setup',headers={'origin':'https://evil.example'}).status_code,403)
        value=self.app.state.store.settings()
        value['output_dir']='relative/path'
        self.assertEqual(self.client.put('/api/settings',json=value).status_code,400)
        value['output_dir']=str(self.home/'new-output')
        self.assertEqual(self.client.put('/api/settings',json=value).status_code,200)
        self.assertTrue((self.home/'new-output').exists())


class RecoveryTests(unittest.TestCase):
    def test_restart_marks_work_interrupted(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as t:
            store=Store(t)
            store.add(('id','name','input','output','queued',2,1,'',time.time(),'{}'))
            store.db.close()
            store=Store(t)
            self.assertEqual(store.job('id')['status'],'interrupted')
            self.assertEqual(store.job('id')['done'],1)
            store.db.close()


if __name__ == '__main__':
    unittest.main()
