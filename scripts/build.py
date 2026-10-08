"""Build on the target OS. End users do not need Python or a compiler."""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import zipfile
import importlib.metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def source_archive(target):
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in ('run.py','requirements.txt','README.md','LICENSE','THIRD_PARTY_NOTICES.md','VALIDATION.md','start.cmd','start.sh','.gitignore'):
            path=ROOT/name
            if path.exists():
                archive.write(path,arcname='PathOCR-source/'+name)
        for folder in ('pathocr','scripts','tests','packaging','.github'):
            for path in (ROOT/folder).rglob('*'):
                if path.is_file() and not any(p=='__pycache__' or p.startswith('tmp') for p in path.relative_to(ROOT/folder).parts):
                    archive.write(path,arcname='PathOCR-source/'+path.relative_to(ROOT).as_posix())


def package_files(dist, offline):
    package=dist/'PathOCR'
    for name in ('README.md','THIRD_PARTY_NOTICES.md','LICENSE','VALIDATION.md'):
        if (ROOT/name).exists():
            shutil.copy(ROOT/name,package/name)
    source_archive(package/'PathOCR-source.zip')
    for distribution in importlib.metadata.distributions():
        for entry in distribution.files or []:
            if '.dist-info' in str(entry) and any('license' in p.lower() or 'copying' in p.lower() or 'notice' in p.lower() for p in entry.parts):
                dest=package/'licenses'/distribution.metadata['Name']/Path(entry).name
                dest.parent.mkdir(parents=True,exist_ok=True)
                source=distribution.locate_file(entry)
                if source.is_file():
                    shutil.copy(source,dest)
    if os.name=='nt':
        for name in ('Install.cmd','install.ps1'):
            shutil.copy(ROOT/'packaging'/name,package/name)
    elif platform.system()=='Linux':
        shutil.copy(ROOT/'packaging/install.sh',package/'install.sh')
        (package/'install.sh').chmod(0o755)
    if platform.system()=='Darwin':
        dmg_root=dist/'dmg-content'
        dmg_root.mkdir(exist_ok=True)
        app_target=dmg_root/'PathOCR.app'
        if app_target.exists():
            shutil.rmtree(app_target)
        shutil.copytree(dist/'PathOCR.app',app_target,symlinks=True)
        if not (dmg_root/'Applications').exists():
            (dmg_root/'Applications').symlink_to('/Applications',target_is_directory=True)
        for name in ('README.md','THIRD_PARTY_NOTICES.md','LICENSE','VALIDATION.md','PathOCR-source.zip'):
            if (package/name).exists():
                shutil.copy(package/name,dmg_root/name)
        if (package/'licenses').exists():
            shutil.copytree(package/'licenses',dmg_root/'licenses',dirs_exist_ok=True)
        subprocess.run(['hdiutil','create','-volname','PathOCR','-srcfolder',str(dmg_root),'-ov','-format','UDZO',str(dist/'PathOCR-macos.dmg')],check=True)
    filename=f'PathOCR-{platform.system().lower()}-{platform.machine()}'+('-offline' if offline else '')
    shutil.make_archive(str(dist/filename),'zip',root_dir=dist,base_dir='PathOCR')
    print(f'Built {dist/filename}.zip')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--offline',action='store_true',help='Bundle model weights too (~710 MB)')
    parser.add_argument('--package-only',action='store_true',help='Repackage an existing build after updating documents')
    args = parser.parse_args()
    if args.package_only:
        package_files(ROOT/'dist',args.offline)
        return
    subprocess.run([sys.executable,str(ROOT/'scripts/fetch_assets.py'),'--runtime',*(['--models'] if args.offline else [])],check=True)
    cmd = [sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--name','PathOCR','--collect-all','pymupdf','--add-data',f'{ROOT / "pathocr/web"}{os.pathsep}pathocr/web','--add-data',f'{ROOT / "vendor/runtime"}{os.pathsep}vendor/runtime','--add-data',f'{ROOT / "vendor/llama-LICENSE"}{os.pathsep}vendor','--hidden-import','uvicorn.logging','--hidden-import','uvicorn.loops.auto','--hidden-import','uvicorn.protocols.http.auto','--hidden-import','uvicorn.lifespan.on']
    if args.offline:
        cmd += ['--add-data',f'{ROOT/"vendor/models"}{os.pathsep}vendor/models']
    if platform.system() == 'Darwin':
        cmd += ['--windowed','--osx-bundle-identifier','app.pathocr.local']
    cmd += [str(ROOT/'run.py')]
    subprocess.run(cmd,cwd=ROOT,check=True)
    dist = ROOT/'dist'
    package_files(dist,args.offline)


if __name__ == '__main__':
    main()
