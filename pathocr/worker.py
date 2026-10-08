import base64
import json
import queue
import threading
from pathlib import Path

import fitz
import httpx

from .runtime import PROMPT


class Cancelled(Exception):
    pass


class Worker:
    def __init__(self, store, runtime):
        self.store, self.runtime = store, runtime
        self.queue = queue.Queue()
        self.stop_event = threading.Event()
        self.cancelled = set()
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def start(self):
        self.thread.start()

    def submit(self, job_id):
        self.cancelled.discard(job_id)
        self.queue.put(job_id)

    def cancel(self, job_id):
        self.cancelled.add(job_id)
        job = self.store.job(job_id)
        if job and job['status'] == 'queued':
            self.store.update(job_id,status='cancelled')

    def check(self, job_id):
        if self.stop_event.is_set() or job_id in self.cancelled:
            raise Cancelled()

    def loop(self):
        while not self.stop_event.is_set():
            try:
                job_id = self.queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                job = self.store.job(job_id)
                if job and job['status'] == 'queued':
                    while not self.runtime.status()['installed'] or self.runtime.status()['status'] in ('installing','loading'):
                        self.check(job_id)
                        self.stop_event.wait(.5)
                    self.process(job)
            except Cancelled:
                self.store.update(job_id,status='interrupted' if self.stop_event.is_set() else 'cancelled')
            except Exception as e:
                self.store.update(job_id,status='interrupted' if self.stop_event.is_set() else 'error',error=str(e))
            finally:
                self.queue.task_done()

    def partial(self, job_id):
        return self.store.home / 'results' / job_id / 'partial.md'

    def process(self, job):
        jid = job['id']
        self.check(jid)
        self.store.update(jid,status='running',error='')
        self.runtime.ensure()
        options = json.loads(job['options'])
        pages_dir = self.partial(jid).parent
        pages_dir.mkdir(parents=True,exist_ok=True)
        with fitz.open(job['input']) as doc, httpx.Client(timeout=httpx.Timeout(1800,connect=10),trust_env=False,headers={'Authorization':'Bearer '+self.runtime.api_key}) as client:
            for number in range(job['pages']):
                self.check(jid)
                saved = pages_dir / f'{number + 1:06d}.md'
                if not saved.exists():
                    page = doc[number]
                    scale = min(options['dpi'] / 72, 2400 / max(page.rect.width,page.rect.height))
                    pix = page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False,colorspace=fitz.csRGB)
                    encoded = base64.b64encode(pix.tobytes('png')).decode('ascii')
                    del pix
                    payload = dict(model='ovisocr',temperature=0,max_tokens=options['max_tokens'],stream=True,messages=[dict(role='user',content=[dict(type='text',text=PROMPT),dict(type='image_url',image_url=dict(url='data:image/png;base64,'+encoded))])])
                    try:
                        text = self.recognize(client,payload,jid,number+1)
                    except Exception as e:
                        self.check(jid)
                        message=str(e).lower()
                        gpu_error=any(word in message for word in ('out of memory','cuda error','vulkan error','failed to allocate','allocation failed','device lost','vk_error_device_lost','cublas'))
                        if self.runtime.status().get('backend') not in ('cuda','vulkan','metal') or not (gpu_error or isinstance(e,httpx.TransportError)):
                            raise
                        self.runtime.fallback_to_cpu(e)
                        self.check(jid)
                        text = self.recognize(client,payload,jid,number+1)
                    if text.startswith('```markdown\n') and text.endswith('```'):
                        text = text[len('```markdown\n'):-3].strip()
                    temp = saved.with_suffix('.tmp')
                    temp.write_text(text,encoding='utf-8')
                    temp.replace(saved)
                self.assemble(pages_dir, self.partial(jid))
                self.store.update(jid,done=number+1)
        self.check(jid)
        output = Path(job['output'])
        output.parent.mkdir(parents=True,exist_ok=True)
        temp = output.with_suffix('.md.tmp')
        temp.write_bytes(self.partial(jid).read_bytes())
        temp.replace(output)
        self.store.update(jid,status='completed',done=job['pages'])

    def recognize(self,client,payload,jid,number):
        chunks=[]
        finish=None
        with client.stream('POST',f'http://127.0.0.1:{self.runtime.port}/v1/chat/completions',json=payload) as response:
            if response.status_code!=200:
                response.read()
                raise RuntimeError(f'OCR failed on page {number}: {response.text[:500]}')
            for line in response.iter_lines():
                self.check(jid)
                if not line.startswith('data: '):
                    continue
                data=line[6:]
                if data=='[DONE]':
                    break
                event=json.loads(data)
                if 'error' in event:
                    raise RuntimeError(str(event['error']))
                for choice in event.get('choices',[]):
                    chunks.append(choice.get('delta',{}).get('content') or '')
                    finish=choice.get('finish_reason') or finish
        if finish=='length':
            raise RuntimeError(f'Page {number} reached the output limit. Increase the maximum output tokens and upload the file again.')
        if finish is None:
            raise RuntimeError(f'Page {number} response ended without a completion marker')
        text=''.join(chunks).strip()
        if not text:
            raise RuntimeError(f'Page {number} returned an empty result. Check the model and projector files.')
        return text

    @staticmethod
    def assemble(folder, destination):
        temp = destination.with_suffix('.tmp')
        with temp.open('w',encoding='utf-8') as out:
            for p in sorted(folder.glob('[0-9]*.md')):
                out.write(f'<!-- page {int(p.stem)} -->\n\n')
                out.write(p.read_text(encoding='utf-8'))
                out.write('\n\n')
        temp.replace(destination)

    def stop(self):
        self.stop_event.set()
        self.runtime.close()
        self.thread.join(timeout=15)
