import asyncio
import json
import os
import re
import secrets
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import fitz
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .runtime import Runtime, bundle_root
from .storage import Store, data_home
from .worker import Worker
from . import __version__


class Settings(BaseModel):
    output_dir: str = Field(min_length=1)
    dpi: int = Field(default=160,ge=72,le=300)
    max_tokens: int = Field(default=8192,ge=1024,le=12288)
    acceleration: Literal['auto','cuda','vulkan','metal','cpu'] = 'auto'
    gpu_layers: int = Field(default=999,ge=0,le=999)
    server_path: str = ''
    model_path: str = ''
    mmproj_path: str = ''


def create_app(home=None, token=None, *, auto_setup=True):
    store = Store(home or data_home())
    runtime = Runtime(store)
    worker = Worker(store,runtime)
    access_token = token or secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        worker.start()
        if auto_setup:
            runtime.setup()
        yield
        worker.stop()

    app = FastAPI(title='PathOCR',version=__version__,lifespan=lifespan)
    app.state.store, app.state.runtime, app.state.worker = store,runtime,worker
    app.state.token = access_token

    @app.middleware('http')
    async def local_access(request: Request, call_next):
        host = request.headers.get('host','').split(':')[0]
        if host not in ('127.0.0.1','localhost','testserver'):
            return JSONResponse({'detail':'Local access only'},status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != f'{request.url.scheme}://{request.headers.get("host")}':
            return JSONResponse({'detail':'Origin is not allowed'},status_code=403)
        bootstrap = request.url.path == '/' and secrets.compare_digest(request.query_params.get('token',''),access_token)
        authenticated = secrets.compare_digest(request.cookies.get('pathocr_session',''),access_token)
        if not bootstrap and not authenticated:
            return JSONResponse({'detail':'Open the app using the PathOCR launch window'},status_code=401)
        response = await call_next(request)
        if bootstrap:
            response.set_cookie('pathocr_session',access_token,httponly=True,samesite='strict')
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-src 'self'; object-src 'none'; connect-src 'self'; frame-ancestors 'none'"
        return response

    def get_job(jid):
        job = store.job(jid)
        if not job:
            raise HTTPException(404,'Task not found')
        return job

    @app.get('/')
    def index():
        return FileResponse(bundle_root() / 'pathocr/web/index.html')

    @app.get('/api/state')
    def state():
        jobs = store.jobs()
        for job in jobs:
            job.pop('input',None)
            job.pop('options',None)
        return dict(jobs=jobs,runtime=runtime.status(),settings=store.settings())

    @app.post('/api/setup')
    def setup():
        runtime.setup()
        return runtime.status()

    @app.put('/api/settings')
    def settings(value: Settings):
        if any(j['status'] in ('running','queued') for j in store.jobs()) or runtime.status()['status'] in ('installing','loading'):
            raise HTTPException(409,'Wait for tasks and installation to finish before changing settings')
        s = value.model_dump()
        path = Path(s['output_dir']).expanduser()
        if not path.is_absolute():
            raise HTTPException(400,'Output folder must be an absolute path')
        try:
            path.mkdir(parents=True,exist_ok=True)
            probe = path / f'.pathocr-{secrets.token_hex(8)}'
            probe.write_text('test')
            probe.unlink()
        except OSError as e:
            raise HTTPException(400,f'Output folder is not writable: {e}')
        s['output_dir'] = str(path.resolve())
        runtime.stop()
        store.save_settings(s)
        return s

    @app.post('/api/jobs')
    async def upload(file: UploadFile):
        if not (file.filename or '').lower().endswith('.pdf'):
            raise HTTPException(400,'Only PDF files are supported')
        jid = secrets.token_hex(16)
        path = store.home / 'uploads' / (jid+'.pdf')
        size = 0
        try:
            with path.open('wb') as out:
                while chunk := await file.read(1024*1024):
                    size += len(chunk)
                    if size > 2*1024**3:
                        raise HTTPException(413,'Each PDF must be smaller than 2 GB')
                    await asyncio.to_thread(out.write,chunk)
            with fitz.open(path) as doc:
                if doc.needs_pass:
                    raise HTTPException(400,'This PDF is password-protected. Decrypt it first.')
                pages = len(doc)
                if not pages:
                    raise HTTPException(400,'PDF has no pages')
            name = re.split(r'[/\\]',file.filename)[-1]
            stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',Path(name).stem).rstrip('. ')[:100] or 'document'
            s = store.settings()
            output = Path(s['output_dir']) / f'{stem}-{jid[:8]}.md'
            store.add((jid,name,str(path),str(output),'queued',pages,0,'',time.time(),json.dumps(s)))
            worker.submit(jid)
            return dict(id=jid,name=name)
        except HTTPException:
            path.unlink(missing_ok=True)
            raise
        except Exception as e:
            path.unlink(missing_ok=True)
            raise HTTPException(400,f'Unable to read PDF: {e}')
        finally:
            await file.close()

    @app.post('/api/jobs/{jid}/cancel')
    def cancel(jid: str):
        get_job(jid)
        worker.cancel(jid)
        return {'ok':True}

    @app.post('/api/jobs/{jid}/retry')
    def retry(jid: str):
        job = get_job(jid)
        if job['status'] not in ('error','cancelled','interrupted'):
            raise HTTPException(409,'Only failed, cancelled, or interrupted tasks can be resumed')
        store.update(jid,status='queued',error='')
        worker.submit(jid)
        return {'ok':True}

    @app.get('/api/jobs/{jid}/pdf')
    def pdf(jid: str):
        return FileResponse(get_job(jid)['input'],media_type='application/pdf')

    @app.get('/api/jobs/{jid}/page/{number}')
    def page(jid: str,number: int):
        job = get_job(jid)
        if number < 1 or number > job['pages']:
            raise HTTPException(404,'Page not found')
        with fitz.open(job['input']) as doc:
            p = doc[number-1]
            pix = p.get_pixmap(matrix=fitz.Matrix(1200/p.rect.width,1200/p.rect.width),alpha=False)
            return Response(pix.tobytes('png'),media_type='image/png')

    @app.get('/api/jobs/{jid}/markdown')
    def markdown(jid: str):
        job = get_job(jid)
        p = Path(job['output']) if job['status']=='completed' else worker.partial(jid)
        return {'text':p.read_text(encoding='utf-8') if p.exists() else ''}

    @app.get('/api/jobs/{jid}/download')
    def download(jid: str):
        job = get_job(jid)
        if job['status'] != 'completed' or not Path(job['output']).exists():
            raise HTTPException(409,'The result has not been saved or the file was moved')
        return FileResponse(job['output'],media_type='text/markdown; charset=utf-8',filename=Path(job['output']).name)

    @app.post('/api/open-output')
    def open_output():
        path = Path(store.settings()['output_dir'])
        path.mkdir(parents=True,exist_ok=True)
        if os.name == 'nt':
            os.startfile(path)
        else:
            import sys
            subprocess.Popen(['open' if sys.platform=='darwin' else 'xdg-open',str(path)])
        return {'ok':True}

    @app.post('/api/choose-output')
    def choose_output():
        import sys
        command = [sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(bundle_root()/'run.py')]
        result = subprocess.run([*command,'--choose-directory','--initial',store.settings()['output_dir']],capture_output=True,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode:
            raise HTTPException(400,'The folder picker is unavailable. Enter an absolute path manually.')
        return {'path':result.stdout.strip()}

    @app.post('/api/shutdown')
    def shutdown():
        callback = getattr(app.state,'shutdown',None)
        if callback:
            threading = __import__('threading')
            threading.Timer(.3,callback).start()
        return {'ok':True}

    app.mount('/static',StaticFiles(directory=bundle_root() / 'pathocr/web'),name='static')
    return app
