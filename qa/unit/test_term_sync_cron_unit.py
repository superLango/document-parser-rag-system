"""L1 单元：术语集按 cron 定时同步（校验/计算/调度窗口）。"""

from datetime import datetime, timedelta, timezone

import pytest
from croniter import croniter

from app.core.exceptions import BusinessException
from app.services.glossary import term_base_service


async def test_validate_cron_ok():
    """L1TS-01：合法 cron 返回下次执行时间。"""
    data = term_base_service.validate_cron("0 2 * * *")
    assert data["cron"] == "0 2 * * *"
    nxt = datetime.fromisoformat(data["next_run_at"])
    assert nxt > datetime.now(timezone.utc) - timedelta(days=1)


async def test_validate_cron_alias():
    """L1TS-02：支持 @daily/@hourly 别名（croniter）。"""
    assert term_base_service.validate_cron("@daily")["cron"] == "@daily"
    assert term_base_service.validate_cron("@hourly")["cron"] == "@hourly"


async def test_validate_cron_invalid():
    """L1TS-03：非法 cron 抛业务异常。"""
    with pytest.raises(BusinessException):
        term_base_service.validate_cron("not a cron")
    with pytest.raises(BusinessException):
        term_base_service.validate_cron("99 99 * * *")


async def test_clean_cron_trims_and_validates():
    """L1TS-04：清洗空白并校验；空值返回空串。"""
    assert term_base_service._clean_cron("  0 2 * * *  ") == "0 2 * * *"
    assert term_base_service._clean_cron("") == ""
    assert term_base_service._clean_cron(None) == ""


def test_dispatch_window_match():
    """L1TS-05：调度窗口判断（当前分钟命中 cron 才触发）。"""
    now = datetime(2026, 8, 22, 2, 30, 10, tzinfo=timezone.utc)
    window_start = now - timedelta(seconds=60)
    # "0 2 * * *" 在 02:00 命中；02:30 窗口（02:29:10~02:30:10）不命中
    nxt = croniter("0 2 * * *", window_start).get_next(datetime)
    assert nxt > now  # 下一次是明天 02:00，不在当前窗口
    # "* * * * *" 每分钟命中：窗口内下一次 <= now
    nxt2 = croniter("* * * * *", window_start).get_next(datetime)
    assert nxt2 <= now
    # "30 2 * * *" 当前 02:30 命中
    nxt3 = croniter("30 2 * * *", window_start).get_next(datetime)
    assert nxt3 <= now


def test_compute_next_run_advances():
    """L1TS-06：下次执行时间计算在基准时间之后。"""
    base = datetime(2026, 8, 22, 1, 0, 0, tzinfo=timezone.utc)
    nxt = term_base_service._compute_next_run("0 2 * * *", base)
    assert nxt > base
    assert nxt.minute == 0 and nxt.hour == 2
