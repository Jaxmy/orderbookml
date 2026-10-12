"""看板测试的确定性队列适配：隔离数据库，内联执行一次任务，保留真实计算逻辑。"""
from core import task_manager


def use_inline_queue(monkeypatch,tmp_path):
    """让 AppTest 在一次提交后看到结果；不启动真实后台进程，不影响非测试看板。"""
    monkeypatch.setattr(task_manager,'TASK_ROOT',tmp_path/'tasks')
    monkeypatch.setattr(task_manager,'DATABASE',tmp_path/'tasks'/'tasks.sqlite3')
    original=task_manager.submit_task
    def submit(kind,config,parent=None,start=True):
        """持久化真实配置后执行领取的任务，模拟后台完成，错误仍进入持久失败记录。"""
        identifier=original(kind,config,parent,start=False)
        task_manager.execute_task(task_manager.claim_next())
        return identifier
    monkeypatch.setattr(task_manager,'submit_task',submit)
