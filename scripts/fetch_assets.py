"""Fetch redistributable browser libraries and optionally the pinned inference runtime/model."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0,str(ROOT))
from pathocr.runtime import FILES, MODEL_REPO, download, install_runtime


def progress(message,received=0,total=0):
    if received == 0 or received == total:
        print(message, f'{received}/{total}' if total else '',flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime',action='store_true')
    parser.add_argument('--models',action='store_true')
    args = parser.parse_args()
    libs = ROOT / 'pathocr/web/vendor'
    download('https://www.gnu.org/licenses/agpl-3.0.txt',ROOT/'LICENSE',progress)
    download('https://cdn.jsdelivr.net/npm/marked@15.0.12/lib/marked.umd.js',libs/'marked.js',progress)
    download('https://cdn.jsdelivr.net/npm/dompurify@3.2.7/dist/purify.min.js',libs/'purify.js',progress)
    download('https://cdn.jsdelivr.net/npm/marked@15.0.12/LICENSE.md',libs/'marked-LICENSE.md',progress)
    download('https://cdn.jsdelivr.net/npm/dompurify@3.2.7/LICENSE',libs/'dompurify-LICENSE',progress)
    vendor = ROOT / 'vendor'
    vendor.mkdir(exist_ok=True)
    if args.runtime:
        install_runtime(vendor,progress)
        download('https://raw.githubusercontent.com/ggml-org/llama.cpp/b11511/LICENSE',vendor/'llama-LICENSE',progress)
    if args.models:
        for name,digest in FILES.items():
            download(MODEL_REPO+name,vendor/'models'/name,progress,digest)
        download('https://www.apache.org/licenses/LICENSE-2.0.txt',vendor/'models/LICENSE',progress)


if __name__ == '__main__':
    main()
