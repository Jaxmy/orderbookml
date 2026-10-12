"""组件用途：项目原生PostgreSQL运行时准备。

原始说明：Download official EDB portable binaries into this project; no Windows service."""
import zipfile
import requests
from core.io import ROOT,dump,sha

if __name__=='__main__':
    runtime=ROOT/'.runtime'; runtime.mkdir(exist_ok=True)
    archive=runtime/'postgresql-17.11.zip'
    url='https://sbp.enterprisedb.com/getfile.jsp?fileid=1260616'
    if not archive.exists():
        tmp=archive.with_suffix('.part')
        with requests.get(url,stream=True,timeout=(20,60)) as r:
            r.raise_for_status(); total=0
            with tmp.open('xb') as f:
                for chunk in r.iter_content(1024*1024):
                    total+=len(chunk)
                    if total>500_000_000: raise ValueError('Runtime download budget')
                    f.write(chunk)
        tmp.rename(archive)
    extracted=0
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if not info.filename.startswith(('pgsql/bin/','pgsql/lib/','pgsql/share/','pgsql/LICENSE')): continue
            path=(runtime/info.filename).resolve()
            if runtime.resolve() not in path.parents: raise ValueError('Invalid archive path')
            extracted+=info.file_size
            if extracted>1_000_000_000: raise ValueError('Runtime expansion budget')
            z.extract(info,runtime)
    dump(ROOT/'logs'/'postgres_runtime.json',dict(url=url,archive_sha256=sha(archive),
        archive_bytes=archive.stat().st_size,extracted_bytes=extracted,path=str(runtime/'pgsql')))
    print('Portable PostgreSQL ready',extracted,'bytes')
