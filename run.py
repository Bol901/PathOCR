import argparse
import socket
import threading
import webbrowser
import sys
from pathlib import Path
from pathocr.storage import data_home


def instance_lock(home):
    """Keep a second launch from interrupting a live queue."""
    home.mkdir(parents=True,exist_ok=True)
    handle=(home/'instance.lock').open('a+b')
    handle.seek(0)
    if handle.read(1)==b'':
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    try:
        if sys.platform=='win32':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except (OSError,BlockingIOError):
        handle.close()
        return None
    return handle

import uvicorn

from pathocr.app import create_app


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='PathOCR — local PDF to Markdown')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--home',help='Override application data folder')
    parser.add_argument('--choose-directory',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--initial',default='',help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.choose_directory:
        import tkinter
        from tkinter import filedialog
        root=tkinter.Tk()
        root.withdraw()
        root.attributes('-topmost',True)
        chosen=filedialog.askdirectory(title='PathOCR — Choose default output folder',initialdir=args.initial or str(Path.home()))
        root.destroy()
        print(chosen)
        return
    home=Path(args.home).resolve() if args.home else data_home()
    home.mkdir(parents=True,exist_ok=True)
    if sys.stdout is None:
        sys.stdout=(home/'application.log').open('a',encoding='utf-8')
    if sys.stderr is None:
        sys.stderr=sys.stdout
    handle=instance_lock(home)
    if handle is None:
        url_file=home/'session-url.txt'
        if url_file.exists() and not args.no_browser:
            webbrowser.open(url_file.read_text(encoding='utf-8'))
        print('PathOCR is already running.')
        return
    sock = socket.socket()
    sock.bind(('127.0.0.1',args.port))
    port = sock.getsockname()[1]
    app = create_app(home)
    url = f'http://127.0.0.1:{port}/?token={app.state.token}'
    (home/'session-url.txt').write_text(url,encoding='utf-8')
    print(f'PathOCR started: {url}\nClick Quit app in the browser to close PathOCR.',flush=True)
    if not args.no_browser:
        threading.Timer(1.5,webbrowser.open,args=[url]).start()
    server = uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning',access_log=False,use_colors=False))
    app.state.shutdown=lambda:setattr(server,'should_exit',True)
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()
        handle.close()
        app.state.store.db.close()


if __name__ == '__main__':
    main()
