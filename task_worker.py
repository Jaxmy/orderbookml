"""持久研究队列的独立进程入口，与看板生命周期隔离。"""
from core.task_manager import run_worker
if __name__=='__main__':
    run_worker()
