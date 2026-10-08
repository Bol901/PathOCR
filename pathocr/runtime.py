"""Managed llama.cpp process and verified, resumable model installation."""
import hashlib
import os
import platform
import shutil
import socket
import secrets
import re
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from pathlib import Path

import httpx

LLAMA_TAG = 'b11511'
MODEL_REPO = 'https://huggingface.co/Abiray/OvisOCR2-GGUF/resolve/main/'
FILES = {
    'OvisOCR2-Q4_K_S.gguf': '75cc6c774cce6adaca8b9a218217d3fdb70835068e66277685642b25b79b8c45',
    'mmproj-F16.gguf': '7e371704e8f3c88638830e52866dfa88b2fd383155e3a0f9484e4ce037fdd42f',
}
PROMPT = 'Extract all readable content from the image in natural human reading order and output the result as a single Markdown document. Format formulas as LaTeX. Format tables as HTML: <table>...</table>. Preserve the original text without translation.'


def bundle_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def download(url, target, progress, expected=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (not expected or sha256(target) == expected):
        return
    partial = target.with_suffix(target.suffix + '.part')
    offset = partial.stat().st_size if partial.exists() else 0
    with httpx.Client(follow_redirects=True, timeout=120, trust_env=True) as client:
        with client.stream('GET', url, headers={'Range': f'bytes={offset}-'} if offset else {}) as r:
            if r.status_code == 416 and offset:
                if expected and sha256(partial) == expected:
                    partial.replace(target)
                    return
                partial.unlink()
                return download(url,target,progress,expected)
            r.raise_for_status()
            if r.status_code == 206 and not r.headers.get('content-range','').startswith(f'bytes {offset}-'):
                raise RuntimeError('Download resume offset mismatch. Please retry.')
            if r.status_code != 206:
                offset = 0
            total = offset + int(r.headers.get('content-length', 0))
            with partial.open('ab' if offset else 'wb') as f:
                for chunk in r.iter_bytes(1024 * 1024):
                    f.write(chunk)
                    offset += len(chunk)
                    progress(f'Downloading {target.name}', offset, total)
    if expected and sha256(partial) != expected:
        partial.unlink()
        raise RuntimeError(f'Checksum verification failed for {target.name}. Download it again.')
    partial.replace(target)


def runtime_backends():
    if platform.system() == 'Darwin':
        return ['metal']
    arch = platform.machine().lower()
    return ['cpu','vulkan','cuda'] if arch in ('amd64','x86_64') else ['cpu','vulkan']


def runtime_assets(backend, system=None, arch=None):
    system = system or platform.system()
    arch = arch or ('arm64' if platform.machine().lower() in ('aarch64','arm64') else 'x64')
    if system == 'Darwin':
        return [f'llama-{LLAMA_TAG}-bin-macos-{arch}.tar.gz']
    if system == 'Windows':
        if backend == 'cuda':
            version = '12.4' if arch == 'x64' else '13.4'
            return [f'llama-{LLAMA_TAG}-bin-win-cuda-{version}-{arch}.zip',f'cudart-llama-bin-win-cuda-{version}-{arch}.zip']
        return [f'llama-{LLAMA_TAG}-bin-win-{backend}-{arch}.zip']
    if backend == 'cuda':
        version = '12.8' if arch == 'x64' else '13.4'
        return [f'llama-{LLAMA_TAG}-bin-ubuntu-cuda-{version}-{arch}.tar.gz',f'cudart-llama-{LLAMA_TAG}-bin-ubuntu-cuda-{version}-{arch}.tar.gz']
    middle = '' if backend == 'cpu' else backend+'-'
    return [f'llama-{LLAMA_TAG}-bin-ubuntu-{middle}{arch}.tar.gz']


def extract_archive(archive, dest):
    dest.mkdir(parents=True,exist_ok=True)
    if archive.suffix == '.zip':
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                if not (dest / item.filename).resolve().is_relative_to(dest.resolve()):
                    raise RuntimeError('Archive contains an unsafe path')
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest,filter='data')


def install_runtime(home, progress, backends=None):
    home = Path(home)
    backends = backends or runtime_backends()
    pending = []
    exe = 'llama-server.exe' if platform.system() == 'Windows' else 'llama-server'
    for backend in backends:
        folder = home / 'runtime' / backend
        manifest = folder / 'pathocr-runtime.json'
        if manifest.exists() and json_manifest(manifest).get('tag') == LLAMA_TAG and any(folder.rglob(exe)):
            continue
        pending.append(backend)
    if not pending:
        return
    system = platform.system()
    with httpx.Client(follow_redirects=True, timeout=60) as c:
        r = c.get(f'https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{LLAMA_TAG}')
        r.raise_for_status()
        assets = {a['name']:a for a in r.json()['assets']}
    for backend in pending:
        dest = home / 'runtime' / backend
        for name in runtime_assets(backend):
            if name not in assets:
                raise RuntimeError(f'No runtime found for {system}/{backend}: {name}')
            asset = assets[name]
            archive = home / name
            digest = asset.get('digest','') or ''
            download(asset['browser_download_url'],archive,progress,digest.removeprefix('sha256:') if digest.startswith('sha256:') else None)
            extract_archive(archive,dest)
            archive.unlink()
        for p in dest.rglob(exe):
            p.chmod(p.stat().st_mode | 0o111)
        import json
        (dest/'pathocr-runtime.json').write_text(json.dumps(dict(tag=LLAMA_TAG,backend=backend)),encoding='utf-8')


def json_manifest(path):
    import json
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,OSError):
        return {}


def subprocess_env(server, root=None):
    env = os.environ.copy()
    directories = [server.parent]
    if root:
        # Official CUDA support libraries may be in a separate lib/ directory.
        directories += sorted({p.parent for p in root.rglob('*') if p.is_file() and (p.suffix=='.dll' or '.so' in p.name)})
    if os.name == 'nt':
        env['PATH'] = os.pathsep.join(map(str,directories)) + os.pathsep + env.get('PATH','')
    else:
        wsl = Path('/usr/lib/wsl/lib')
        if wsl.is_dir():
            directories.append(wsl)
        # PyInstaller changes LD_LIBRARY_PATH. Restore it before starting an external binary.
        original = env.get('LD_LIBRARY_PATH_ORIG',env.get('LD_LIBRARY_PATH',''))
        env['LD_LIBRARY_PATH'] = os.pathsep.join(map(str,directories)) + (os.pathsep+original if original else '')
    return env


def parse_devices(output):
    devices = []
    for line in output.splitlines():
        match = re.match(r'\s*((?:CUDA|Vulkan|Metal)\d*)\s*:\s*(.+)',line,re.I)
        if match and not any(word in line.lower() for word in ('llvmpipe','lavapipe','software','basic render')):
            devices.append(dict(id=match[1],name=match[2].strip()))
    return devices


def probe_devices(server, root=None):
    try:
        result = subprocess.run([str(server),'--list-devices'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30,env=subprocess_env(server,root),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        output = result.stdout+'\n'+result.stderr
        devices = parse_devices(output) if result.returncode==0 else []
        return devices, '' if devices else 'No hardware GPU is available, or the driver/runtime is incompatible'
    except (OSError,subprocess.TimeoutExpired) as e:
        return [],str(e)


def choose_device(devices):
    def score(device):
        name=device['name'].lower()
        dedicated=any(word in name for word in ('nvidia','radeon',' arc ')) and not any(word in name for word in ('uhd','iris'))
        free=re.search(r'(\d+)\s*MiB free',device['name'])
        return int(dedicated),int(free[1]) if free else 0
    return max(devices,key=score)


class Runtime:
    def __init__(self, store):
        self.store = store
        self.proc = None
        self.port = None
        self.api_key = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.start_lock = threading.Lock()
        self.state = dict(status='missing', message='Install the OCR engine and models to get started', received=0,total=0,backend='pending',vision_backend='pending',devices=[],offloaded_layers=0,fallback_reason='')
        self.log = None
        self.install_attempted = set()
        self.closed = threading.Event()

    def servers(self):
        exe = 'llama-server.exe' if os.name == 'nt' else 'llama-server'
        found = []
        for base in (self.store.home/'runtime',bundle_root()/'vendor/runtime'):
            for backend in ('cuda','vulkan','metal','cpu'):
                root = base/backend
                for p in sorted(root.rglob(exe)):
                    if p.is_file():
                        found.append((backend,p,root))
            for p in sorted(base.rglob(exe)):
                if p.is_file() and not any(p.is_relative_to(base/b) for b in ('cuda','vulkan','metal','cpu')):
                    found.append(('metal' if platform.system()=='Darwin' else 'cpu',p,p.parent))
        return found

    def paths(self):
        s = self.store.settings()
        candidates = self.servers()
        server = Path(s['server_path']) if s['server_path'] else (candidates[0][1] if candidates else None)
        models = {}
        for key, name in [('model_path','OvisOCR2-Q4_K_S.gguf'), ('mmproj_path','mmproj-F16.gguf')]:
            models[key] = Path(s[key]) if s[key] else self.store.home / 'models' / name
            if not s[key] and not models[key].exists() and (bundle_root() / 'vendor/models' / name).exists():
                models[key] = bundle_root() / 'vendor/models' / name
        return server, models['model_path'], models['mmproj_path']

    def status(self):
        with self.lock:
            result = dict(self.state)
            result['installed'] = all(p and p.is_file() for p in self.paths())
            return result

    def progress(self, message, received=0, total=0):
        with self.lock:
            self.state.update(message=message,received=received,total=total)

    def setup(self):
        with self.lock:
            if self.state['status'] in ('installing','loading','ready'):
                return
            self.state.update(status='installing',message='Preparing installation…')
        threading.Thread(target=self._setup, daemon=True).start()

    def _setup(self):
        try:
            server, model, projector = self.paths()
            if not server or not server.is_file():
                requested = self.store.settings()['acceleration']
                install_runtime(self.store.home,self.progress,backends=['cpu'] if requested=='cpu' and platform.system()!='Darwin' else None)
            for target, name in [(model,'OvisOCR2-Q4_K_S.gguf'),(projector,'mmproj-F16.gguf')]:
                key = 'model_path' if name=='OvisOCR2-Q4_K_S.gguf' else 'mmproj_path'
                if self.store.settings()[key]:
                    if not target.is_file():
                        raise RuntimeError(f'Configured local file does not exist: {target}')
                else:
                    download(MODEL_REPO + name, target, self.progress, FILES[name])
            self.ensure()
        except Exception as e:
            with self.lock:
                self.state.update(status='error',message=str(e))

    def ensure(self):
        with self.start_lock:
            try:
                self._ensure()
            except Exception as e:
                self._stop_process()
                with self.lock:
                    self.state.update(status='error',message=str(e))
                raise

    def _ensure(self):
        with self.lock:
            if self.proc and self.proc.poll() is None and self.state['status'] == 'ready':
                return
            server, model, projector = self.paths()
            if not all(p and p.is_file() for p in (model,projector)):
                raise RuntimeError('Install the OCR engine and models, or configure local files in Preferences')
            self.state.update(status='loading',message='Detecting GPU acceleration…',received=0,total=0,backend='pending',vision_backend='pending',devices=[],offloaded_layers=0,fallback_reason='')
        s = self.store.settings()
        requested = s['acceleration']
        cpu_only = requested=='cpu' or s['gpu_layers']==0
        warnings = []
        if s['server_path']:
            gpu_plans = [('custom',server,server.parent)] if not cpu_only else []
            cpu_plans = [('cpu',server,server.parent)]
        else:
            backends = ['metal'] if platform.system()=='Darwin' else ['cuda','vulkan']
            wanted = [] if cpu_only else (backends if requested=='auto' else [requested])
            for backend in wanted:
                if not any(b==backend for b,_,_ in self.servers()) and backend not in self.install_attempted:
                    self.install_attempted.add(backend)
                    try:
                        self.state.update(status='installing',message=f'Installing the {backend.upper()} runtime…')
                        install_runtime(self.store.home,self.progress,[backend])
                    except Exception as e:
                        warnings.append(f'{backend.upper()} installation failed: {e}')
            available = self.servers()
            gpu_plans = [matches[0] for backend in wanted if (matches:=[entry for entry in available if entry[0]==backend])]
            cpu_plans = [entry for entry in available if entry[0]=='cpu']
            if platform.system()=='Darwin':
                cpu_plans = [('cpu',p,r) for b,p,r in available if b=='metal']
        for backend,path,root in gpu_plans:
            if not path or not path.is_file():
                continue
            self.progress(f'Detecting {backend.upper()} devices…')
            devices, error = probe_devices(path,root)
            if not devices:
                warnings.append(f'{backend.upper()}: {error}')
                continue
            selected = choose_device(devices)
            actual = selected['id'].rstrip('0123456789').lower() if backend=='custom' else backend
            try:
                layers = self._launch(path,root,model,projector,s['gpu_layers'],actual,selected['id'])
                message = f'GPU acceleration enabled · {actual.upper()} · {selected["name"]}'
                if actual=='vulkan':
                    message+=' · CPU vision compatibility mode'
                with self.lock:
                    self.state.update(status='ready',message=message,backend=actual,vision_backend='cpu' if actual=='vulkan' else actual,devices=[selected],offloaded_layers=layers,fallback_reason='; '.join(warnings))
                return
            except Exception as e:
                warnings.append(f'{actual.upper()} startup failed: {e}')
                self._stop_process()
                log_path = self.store.home/'llama-server.log'
                if log_path.exists():
                    shutil.copyfile(log_path,self.store.home/f'llama-server-{actual}-failed.log')
        if not cpu_plans:
            try:
                install_runtime(self.store.home,self.progress,['metal'] if platform.system()=='Darwin' else ['cpu'])
                cpu_plans = [('cpu',p,r) for b,p,r in self.servers() if b in ('cpu','metal')]
            except Exception as e:
                raise RuntimeError('No GPU or CPU runtime is available: '+str(e))
        if not cpu_plans:
            raise RuntimeError('No CPU runtime is available')
        reason = '; '.join(warnings)
        try:
            _,path,root = cpu_plans[0]
            self._launch(path,root,model,projector,0,'cpu')
            with self.lock:
                self.state.update(status='ready',message='CPU mode enabled'+(' · GPU unavailable; automatically using CPU' if not cpu_only else ''),backend='cpu',vision_backend='cpu',devices=[],offloaded_layers=0,fallback_reason=reason)
        except Exception as e:
            self._stop_process()
            with self.lock:
                self.state.update(status='error',message=str(e),fallback_reason=reason)
            raise

    def _launch(self, server, root, model, projector, layers, backend, device=None):
        self._stop_process()
        with self.lock:
            if self.closed.is_set():
                raise RuntimeError('The app is closing')
            self.state.update(status='loading',message=f'Loading model · {backend.upper()}…',received=0,total=0)
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0))
                self.port = sock.getsockname()[1]
            self.log = (self.store.home / 'llama-server.log').open('w',encoding='utf-8')
            device_args = ['--device',device,'--mmproj-device',device] if device else []
            if backend=='vulkan':
                device_args=['--device',device,'--mmproj-device','none','--no-mmproj-offload']
            if layers==0:
                device_args = ['--device','none','--no-mmproj-offload','--no-op-offload']
            self.proc = subprocess.Popen([str(server), '-m',str(model),'--mmproj',str(projector),'--host','127.0.0.1','--port',str(self.port),'--api-key',self.api_key,'-c','16384','-ngl',str(layers),'--parallel','1','--flash-attn','off','-lv','4', *device_args], cwd=str(server.parent),env=subprocess_env(server,root),stdout=self.log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            with httpx.Client(timeout=2,trust_env=False) as c:
                for _ in range(240):
                    if not self.proc or self.proc.poll() is not None:
                        raise RuntimeError('Model startup failed. Check llama-server.log for runtime or model compatibility errors.')
                    try:
                        if c.get(f'http://127.0.0.1:{self.port}/health').status_code == 200:
                            content = (self.store.home/'llama-server.log').read_text(encoding='utf-8',errors='replace')
                            matches = re.findall(r'offloaded\s+(\d+)/(\d+)\s+layers',content)
                            offloaded = max((int(m[0]) for m in matches),default=0)
                            if layers and not offloaded:
                                raise RuntimeError('The runtime started but no model layers were offloaded to the GPU')
                            return offloaded
                    except httpx.HTTPError:
                        pass
                    time.sleep(1)
            raise RuntimeError('Model loading timed out. Check llama-server.log.')
        except Exception as e:
            self._stop_process()
            raise

    def fallback_to_cpu(self, reason):
        """Recover an in-flight page after GPU allocation/device failure without losing completed pages."""
        with self.start_lock:
            s=self.store.settings()
            _,model,projector=self.paths()
            if s['server_path']:
                server=Path(s['server_path'])
                root=server.parent
            else:
                candidates=[entry for entry in self.servers() if entry[0] in ('cpu','metal')]
                if not candidates:
                    install_runtime(self.store.home,self.progress,['metal'] if platform.system()=='Darwin' else ['cpu'])
                    candidates=[entry for entry in self.servers() if entry[0] in ('cpu','metal')]
                if not candidates:
                    raise RuntimeError('CPU fallback runtime is unavailable')
                _,server,root=candidates[0]
            try:
                self._launch(server,root,model,projector,0,'cpu')
            except Exception as e:
                self._stop_process()
                with self.lock:
                    self.state.update(status='error',message=str(e),fallback_reason=str(reason))
                raise
            with self.lock:
                self.state.update(status='ready',message='CPU mode: GPU inference failed; automatically retrying the current page',backend='cpu',vision_backend='cpu',devices=[],offloaded_layers=0,fallback_reason=str(reason))

    def stop(self):
        self._stop_process()
        with self.lock:
            self.state.update(status='missing',message='Engine has not started',backend='pending',vision_backend='pending',devices=[],offloaded_layers=0,fallback_reason='')

    def close(self):
        self.closed.set()
        self.stop()

    def _stop_process(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
            self.proc = None
            if self.log:
                self.log.close()
                self.log = None
