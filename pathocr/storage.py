import json
import os
import sqlite3
import threading
from pathlib import Path


def data_home():
    if os.environ.get('PATHOCR_HOME'):
        return Path(os.environ['PATHOCR_HOME']).expanduser().resolve()
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'PathOCR'
    if __import__('sys').platform == 'darwin':
        return Path.home() / 'Library/Application Support/PathOCR'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'pathocr'


class Store:
    def __init__(self, home):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / 'uploads').mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.home / 'jobs.sqlite', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, name TEXT, input TEXT, output TEXT, status TEXT, pages INTEGER, done INTEGER, error TEXT, created REAL, options TEXT)')
        self.db.execute("UPDATE jobs SET status='interrupted', error='The app closed before this task finished. Resume to continue.' WHERE status IN ('running','queued')")
        self.db.commit()

    def settings(self):
        defaults = dict(output_dir=str(Path.home() / 'Documents/PathOCR'), dpi=160, max_tokens=8192, acceleration='auto',gpu_layers=999, server_path='', model_path='', mmproj_path='')
        p = self.home / 'settings.json'
        if p.exists():
            saved = json.loads(p.read_text(encoding='utf-8'))
            if 'acceleration' not in saved:
                # Old releases wrote gpu_layers=0 by default, not as an explicit CPU preference.
                if saved.get('server_path'):
                    saved['acceleration'] = 'cpu' if saved.get('gpu_layers',0)==0 else 'auto'
                else:
                    saved['acceleration'] = 'auto'
                    saved['gpu_layers'] = 999
            defaults.update(saved)
        return defaults

    def save_settings(self, settings):
        with self.lock:
            p = self.home / 'settings.json'
            tmp = p.with_suffix('.tmp')
            tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
            tmp.replace(p)

    def add(self, values):
        with self.lock:
            self.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)', values)
            self.db.commit()

    def update(self, job_id, **values):
        allowed = {'status','done','error','output'}
        if not values or not set(values) <= allowed:
            raise ValueError('Invalid job update')
        with self.lock:
            self.db.execute('UPDATE jobs SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?', [*values.values(),job_id])
            self.db.commit()

    def jobs(self):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT * FROM jobs ORDER BY created DESC')]

    def job(self, job_id):
        with self.lock:
            r = self.db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            return dict(r) if r else None
