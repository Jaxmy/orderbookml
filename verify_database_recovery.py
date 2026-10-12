"""组件用途：数据库重启恢复核验。

原始说明：Backup/restore check on this project's native database only."""
import os
import subprocess
import psycopg
from sqlalchemy import text
from core.store import Store
from core.io import ROOT,read,dump,utcnow,sha
from setup_native_database import command,data,bin

if __name__=='__main__':
    settings=read(ROOT/'.runtime'/'database.json')
    store=Store(settings['url'])
    with store.engine.connect() as c: before=c.scalar(text('SELECT count(*) FROM market_events'))
    store.engine.dispose()
    command('pg_ctl',['-D',data,'-m','fast','-w','stop'])
    command('pg_ctl',['-D',data,'-l',ROOT/'logs'/'postgres.log','-w','start'])
    admin=dict(host='127.0.0.1',port=55432,user='bootstrap_admin',password=settings['admin_password'],dbname='postgres',autocommit=True)
    env=os.environ.copy(); env['PGPASSWORD']=settings['admin_password']
    backup=ROOT/'data'/'research-backup.dump'
    common=['-h','127.0.0.1','-p','55432','-U','bootstrap_admin']
    subprocess.run([str(bin/'pg_dump.exe')]+common+['-d','research','-Fc','-f',str(backup)],
        env=env,check=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=60)
    name='research_restore_check'
    with psycopg.connect(**admin) as c:
        if c.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone():
            raise ValueError('Restore-check database already exists; no destructive overwrite')
        c.execute('CREATE DATABASE research_restore_check OWNER researcher')
    try:
        subprocess.run([str(bin/'pg_restore.exe')]+common+['-d',name,str(backup)],env=env,check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,timeout=60)
        with psycopg.connect(**(admin|{'dbname':name})) as c:
            restored=c.execute('SELECT count(*) FROM market_events').fetchone()[0]
        with psycopg.connect(**(admin|{'dbname':'research'})) as c:
            after=c.execute('SELECT count(*) FROM market_events').fetchone()[0]
        if before!=after or after!=restored: raise ValueError('Restart / restore row count mismatch')
        dump(ROOT/'logs'/'postgres_recovery.json',dict(time=utcnow(),rows_before=before,rows_after_restart=after,
            rows_after_restore=restored,backup_sha256=sha(backup),backup_bytes=backup.stat().st_size,passed=True))
        print('Restart and backup/restore verified:',restored,'events')
    finally:
        with psycopg.connect(**admin) as c:
            c.execute('DROP DATABASE research_restore_check')
