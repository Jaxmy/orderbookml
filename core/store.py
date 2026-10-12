"""组件用途：按URL缓存有界SQLAlchemy连接池，设置连接超时和健康检查；凭据只进入连接，不返回给看板。；保存实时观测和worker心跳的有界运行缓存；历史原始档案留在唯一文件目录。。

原始说明：Small operational store; historical raw archives stay in one canonical location."""
import os
import json
from functools import lru_cache
from sqlalchemy import create_engine,MetaData,Table,Column,String,Float,Text,select,delete,func
from .io import ROOT

@lru_cache(maxsize=8)
def engine_for(url):
    """按URL缓存有界SQLAlchemy连接池，设置连接超时和健康检查；凭据只进入连接，不返回给看板。

    输入参数：url（单位和范围由下方校验及调用方契约限定）。"""
    options={'connect_timeout':5} if url.startswith('postgresql') else {'timeout':5}
    return create_engine(url,pool_size=2,max_overflow=0,pool_pre_ping=True,pool_timeout=5,connect_args=options)

class Store:
    """保存实时观测和worker心跳的有界运行缓存；历史原始档案留在唯一文件目录。"""
    def __init__(self,url=None):
        """选择环境变量/本机数据库配置或SQLite后备，建立事件和状态表，设置SQLite容量和忙超时。

        输入参数：url（单位和范围由下方校验及调用方契约限定）。"""
        default='sqlite:///'+(ROOT/'data'/'operations.db').as_posix()
        native=ROOT/'.runtime'/'database.json'
        if native.exists():
            default=json.loads(native.read_text(encoding='utf-8'))['url']
        self.engine=engine_for(url or os.environ.get('DATABASE_URL',default))
        meta=MetaData()
        self.events=Table('market_events',meta,Column('id',String(160),primary_key=True),
            Column('kind',String(30),index=True),Column('available_at',Float,index=True),Column('payload',Text))
        self.status=Table('worker_status',meta,Column('id',String(30),primary_key=True),Column('payload',Text))
        meta.create_all(self.engine)
        if self.engine.dialect.name=='sqlite':
            with self.engine.begin() as c:
                c.exec_driver_sql('PRAGMA max_page_count=60000')
                c.exec_driver_sql('PRAGMA busy_timeout=10000')

    def put(self,kind,row):
        """单事务清理六小时前观测、检查事件大小/条数、按id去重再写入；达到上限拒绝而不是无限增长。

        输入参数：kind、row（单位和范围由下方校验及调用方契约限定）。"""
        payload=json.dumps(row,allow_nan=False)
        if len(payload.encode())>10_000: raise ValueError('Oversized event')
        with self.engine.begin() as c:
            # A bounded operational cache, not a second full history archive.
            c.execute(delete(self.events).where(self.events.c.available_at<row['available_at']-21600))
            count=c.scalar(select(func.count()).select_from(self.events))
            if count>=30000: raise ValueError('Operational retention cap reached')
            if c.scalar(select(self.events.c.id).where(self.events.c.id==row['id'])): return
            c.execute(self.events.insert().values(id=row['id'],kind=kind,available_at=row['available_at'],payload=payload))

    def heartbeat(self,key,value):
        """事务内替换对应worker状态记录，供健康检查判断运行及数据新鲜度。

        输入参数：key、value（单位和范围由下方校验及调用方契约限定）。"""
        with self.engine.begin() as c:
            c.execute(delete(self.status).where(self.status.c.id==key))
            c.execute(self.status.insert().values(id=key,payload=json.dumps(value)))

    def health(self):
        """读取状态表并反序列化为组件字典；不把数据库可用等同市场可执行。"""
        with self.engine.connect() as c:
            return {r.id:json.loads(r.payload) for r in c.execute(select(self.status))}

    def latest(self,kind,limit=100):
        """按可用时间倒序取指定事件，最多一千条，返回JSON数据列表供API及页面。

        输入参数：kind、limit（单位和范围由下方校验及调用方契约限定）。"""
        with self.engine.connect() as c:
            rows=c.execute(select(self.events.c.payload).where(self.events.c.kind==kind)
                .order_by(self.events.c.available_at.desc()).limit(min(limit,1000)))
            return [json.loads(r.payload) for r in rows]
