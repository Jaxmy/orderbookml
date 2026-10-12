"""组件用途：执行本机数据库初始化所需子命令并检查退出状态；不把密码打印到结果。。

原始说明：Project-scoped PostgreSQL cluster; no system service, no registry/PATH edits."""
import os
import secrets
import subprocess
import psycopg
from psycopg import sql
from core.io import ROOT,read,dump,utcnow

runtime=ROOT/'.runtime'; bin=runtime/'pgsql'/'bin'; data=ROOT/'data'/'postgres-native'
credentials=runtime/'database.json'

def command(name,args):
    """执行本机数据库初始化所需子命令并检查退出状态；不把密码打印到结果。

    输入参数：name、args（单位和范围由下方校验及调用方契约限定）。"""
    output=ROOT/'.tmp'/('postgres-command-'+name+'.log')
    # Background postgres children may inherit PIPE handles on Windows; use a file.
    with output.open('wb') as stream:
        result=subprocess.run([str(bin/(name+'.exe'))]+list(map(str,args)),stdout=stream,stderr=stream,
            creationflags=subprocess.CREATE_NO_WINDOW,timeout=90)
    if result.returncode:
        raise RuntimeError(name+' failed: '+output.read_text(errors='replace')[-2000:])
    return output.read_text(errors='replace')

if __name__=='__main__':
    if credentials.exists():
        raise ValueError('Native database already configured; use native_database.py to start it')
    recovery=runtime/'bootstrap-recovery.pw'
    recovering=data.exists() and recovery.exists()
    if data.exists() and not recovering: raise ValueError('Cluster path exists; inspect before setup')
    admin_pw=recovery.read_text(encoding='ascii') if recovering else secrets.token_hex(32)
    app_pw=secrets.token_hex(32)
    pwfile=runtime/'bootstrap.pw'; pwfile.write_text(admin_pw,encoding='ascii')
    try:
        if not recovering:
            command('initdb',['-D',data,'--username=bootstrap_admin','--pwfile='+str(pwfile),
                '--auth=scram-sha-256','--encoding=UTF8','--locale=C'])
            with (data/'postgresql.conf').open('a') as f:
                f.write("\nlisten_addresses = '127.0.0.1'\nport = 55432\nshared_buffers = '32MB'\nmax_connections = 12\nwork_mem = '4MB'\nmax_wal_size = '256MB'\nmin_wal_size = '80MB'\n")
            command('pg_ctl',['-D',data,'-l',ROOT/'logs'/'postgres.log','-w','start'])
        with psycopg.connect(host='127.0.0.1',port=55432,user='bootstrap_admin',password=admin_pw,dbname='postgres',autocommit=True) as c:
            c.execute(sql.SQL('CREATE ROLE researcher LOGIN PASSWORD {}').format(sql.Literal(app_pw)))
            c.execute('CREATE DATABASE research OWNER researcher')
        url=f'postgresql+psycopg://researcher:{app_pw}@127.0.0.1:55432/research'
        # Locally generated passwords: never print them or put them in logs/manifests.
        dump(credentials,dict(url=url,admin_password=admin_pw))
        os.environ['DATABASE_URL']=url
        from core.store import Store
        store=Store(); store.heartbeat('database',dict(status='native_postgresql',received_at=__import__('time').time()))
        with store.engine.connect() as c:
            from sqlalchemy import text
            version=c.scalar(text('SELECT version()'))
            size=c.scalar(text("SELECT pg_database_size(current_database())"))
        store.engine.dispose()
        dump(ROOT/'logs'/'postgres_validation.json',dict(time=utcnow(),version=version,database_bytes=size,
            port=55432,listen='127.0.0.1',cluster=str(data),windows_service_installed=False,
            application_role_superuser=False))
        print('PostgreSQL validated on localhost:55432; database bytes',size)
        recovery.unlink(missing_ok=True)
    finally:
        pwfile.unlink(missing_ok=True)
