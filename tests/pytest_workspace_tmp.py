"""Small pytest tmp_path fixture rooted on the writable project volume."""
from pathlib import Path
import uuid

import pytest

from core.io import ROOT


@pytest.fixture
def tmp_path():
    """为测试建立工作区内唯一临时目录，避开Windows系统临时目录权限问题，不删除历史证据。"""
    root = ROOT / 'data' / 'experiments' / 'test_artifacts' / 'pytest-workspace-m18'
    root.mkdir(parents=True, exist_ok=True)
    folder = root / uuid.uuid4().hex
    folder.mkdir()
    return folder
