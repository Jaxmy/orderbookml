"""组件用途：原生 PostgreSQL 管理与健康实例复用。"""
import argparse
import json
from sqlalchemy import create_engine, text
from setup_native_database import command,data,ROOT

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('action',choices=['start','stop','status','ensure'])
    action=p.parse_args().action
    if action=='ensure':
        # pg_ctl status can miss an already-running Windows cluster after an
        # interrupted parent shell.  Prove this is our database with its local
        # application credentials before attempting another server start.
        engine=None
        try:
            credentials=json.loads((ROOT/'.runtime'/'database.json').read_text(encoding='utf-8'))
            engine=create_engine(credentials['url'],connect_args={'connect_timeout':2},pool_pre_ping=True)
            with engine.connect() as connection:
                connection.execute(text('SELECT 1'))
            print('Project PostgreSQL authenticated connection is ready.')
            raise SystemExit(0)
        except SystemExit:
            raise
        except Exception:
            pass
        finally:
            if engine is not None:
                engine.dispose()
        try:
            print(command('pg_ctl',['-D',data,'status']))
            raise SystemExit(0)
        except RuntimeError:
            action='start'
    args=['-D',data]
    if action=='start': args+=['-l',ROOT/'logs'/'postgres.log','-w']
    if action=='stop': args+=['-m','fast','-w']
    print(command('pg_ctl',args+[action]))
