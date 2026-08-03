"""雪花算法（Snowflake）唯一 ID 生成器。

生成 128 位全局唯一 ID，经 Base62 编码为字母数字混合字符串：

    ID = Base62( 时间戳(41bit) | 机器ID(10bit) | 序列号(12bit) | 随机数(65bit) )

特性：
    - 字母数字混合：Base62 编码（0-9, A-Z, a-z），兼顾可读性与紧凑性，
      适合作为数据库主键、文件目录名、arq job_id。
    - 全局唯一：时间戳 + 机器ID + 序列号 + 随机数四重保证。即使时钟回拨，
      65 bit 随机数也使碰撞概率趋近于零（2^-65 量级）。
    - 趋势递增：时间戳占据高位，ID 按时间趋势递增（同毫秒内因随机数无序，
      跨毫秒严格递增），利于 B+ 树索引聚集。
    - 长度稳定：约 22 位字符（相比纯数字 18 位更长，熵更高），无特殊字符，
      URL/文件名/Redis 键安全。
    - 线程安全：内部加锁保护时间戳与序列号分配。

ID 结构（128 bit）::

    | 41 bit 时间戳(ms) | 10 bit 机器ID | 12 bit 序列号 | 65 bit 随机数 |
    |     高位 → 低位                                            |

使用方式::

    from app.core.snowflake import snowflake_generator

    task_id = snowflake_generator.generate_id_str()
    # 如 "7XkLm2Q9vN4pR1aB3hYz6t"

机器 ID 配置：
    通过环境变量 ``SNOWFLAKE_MACHINE_ID`` 配置（0-1023，默认 1），
    多实例部署时需为每个实例分配不同机器 ID。
"""

from __future__ import annotations

import os
import secrets
import threading
import time

# 自定义纪元：2024-01-01 00:00:00 UTC（毫秒）
# 用近期纪元减少时间戳位数消耗，41 位可用约 69 年
_EPOCH_MS: int = 1704067200000

# 各部分位宽（总和 = 41 + 10 + 12 + 65 = 128 bit）
_MACHINE_ID_BITS: int = 10
_SEQUENCE_BITS: int = 12
_RANDOM_BITS: int = 65

# 最大值
_MAX_MACHINE_ID: int = (1 << _MACHINE_ID_BITS) - 1  # 1023
_MAX_SEQUENCE: int = (1 << _SEQUENCE_BITS) - 1  # 4095

# 位移（从低位到高位排列：随机数 → 序列号 → 机器ID → 时间戳）
_SEQUENCE_SHIFT: int = _RANDOM_BITS  # 65
_MACHINE_ID_SHIFT: int = _RANDOM_BITS + _SEQUENCE_BITS  # 77
_TIMESTAMP_SHIFT: int = _RANDOM_BITS + _SEQUENCE_BITS + _MACHINE_ID_BITS  # 87

# Base62 字母表：0-9 + A-Z + a-z（62 个字符）
_BASE62_ALPHABET: str = (
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)
_BASE62_LEN: int = len(_BASE62_ALPHABET)  # 62
# Base62 编码固定长度：128 位整数编码后最多 22 位字符
_BASE62_PAD_LEN: int = 22


def base62_encode(num: int) -> str:
    """将非负整数编码为 Base62 字符串。

    使用 0-9、A-Z、a-z 共 62 个字符表示，相比十进制更紧凑（同位数熵更高），
    相比 Base64 无 ``+``/``/`` 特殊字符，URL/文件名安全。

    Args:
        num: 非负整数。

    Returns:
        Base62 编码字符串，左填充 ``0`` 至 22 位固定长度。
    """
    if num == 0:
        return "0" * _BASE62_PAD_LEN
    chars: list[str] = []
    while num > 0:
        num, rem = divmod(num, _BASE62_LEN)
        chars.append(_BASE62_ALPHABET[rem])
    encoded = "".join(reversed(chars))
    # 左填充至固定长度，确保 ID 长度一致（便于存储与展示）
    if len(encoded) < _BASE62_PAD_LEN:
        encoded = "0" * (_BASE62_PAD_LEN - len(encoded)) + encoded
    return encoded


class SnowflakeGenerator:
    """雪花算法 ID 生成器（线程安全单例）。

    生成 128 位 ID 并经 Base62 编码为字母数字混合字符串。

    Attributes:
        machine_id: 机器标识（0-1023），多实例部署需唯一。
        epoch_ms: 自定义纪元（毫秒），ID 中时间戳基于此偏移。
    """

    def __init__(self, machine_id: int | None = None, epoch_ms: int = _EPOCH_MS) -> None:
        """初始化雪花算法生成器。

        Args:
            machine_id: 机器 ID（0-1023）。None 时从环境变量
                ``SNOWFLAKE_MACHINE_ID`` 读取，默认 1。
            epoch_ms: 自定义纪元（毫秒），默认 2024-01-01 UTC。

        Raises:
            ValueError: 机器 ID 超出范围时抛出。
        """
        if machine_id is None:
            machine_id = int(os.environ.get("SNOWFLAKE_MACHINE_ID", "1"))
        if not 0 <= machine_id <= _MAX_MACHINE_ID:
            raise ValueError(
                f"machine_id 必须在 0-{_MAX_MACHINE_ID} 范围内，当前: {machine_id}"
            )

        self.machine_id: int = machine_id
        self.epoch_ms: int = epoch_ms
        self._sequence: int = 0
        self._last_timestamp: int = -1
        self._lock: threading.Lock = threading.Lock()

    def next_id(self) -> int:
        """生成下一个唯一 ID（线程安全）。

        组合时间戳、机器 ID、序列号与密码学随机数，生成 128 位整数。
        同一毫秒内通过序列号递增 + 随机数保证唯一；跨毫秒序列号归零。
        时钟回拨时等待追上，短回拨由随机数兜底防碰撞。

        Returns:
            128 位唯一整数 ID。

        Raises:
            RuntimeError: 时钟回拨超过 5 秒（系统时钟严重异常）时抛出。
        """
        with self._lock:
            now = self._current_ms()

            if now < self._last_timestamp:
                # 时钟回拨
                offset = self._last_timestamp - now
                if offset > 5000:
                    raise RuntimeError(
                        f"时钟回拨超过 5 秒（{offset}ms），拒绝生成 ID "
                        "请检查系统时间同步"
                    )
                # 短回拨：等待追上
                time.sleep(offset / 1000.0)
                now = self._current_ms()

            if now == self._last_timestamp:
                # 同毫秒内序列号递增
                self._sequence = (self._sequence + 1) & _MAX_SEQUENCE
                if self._sequence == 0:
                    # 序列号耗尽，等待下一毫秒
                    now = self._wait_next_ms(self._last_timestamp)
            else:
                # 新毫秒，序列号归零
                self._sequence = 0

            self._last_timestamp = now

            # 65 bit 密码学随机数：即使序列号相同也保证全局唯一，
            # 同时增加 ID 长度与熵，降低碰撞概率至 2^-65 量级
            random_part: int = secrets.randbits(_RANDOM_BITS)

            return (
                (now - self.epoch_ms) << _TIMESTAMP_SHIFT
                | (self.machine_id << _MACHINE_ID_SHIFT)
                | (self._sequence << _SEQUENCE_SHIFT)
                | random_part
            )

    def generate_id(self) -> int:
        """便捷方法：生成 128 位雪花 ID（整数）。

        Returns:
            128 位唯一整数 ID。
        """
        return self.next_id()

    def generate_id_str(self) -> str:
        """便捷方法：生成 Base62 编码的字母数字混合 ID 字符串。

        Returns:
            22 位 Base62 字符串（含 0-9, A-Z, a-z）。
        """
        return base62_encode(self.next_id())

    @staticmethod
    def _current_ms() -> int:
        """返回当前时间戳（毫秒）。"""
        return int(time.time() * 1000)

    def _wait_next_ms(self, last_timestamp: int) -> int:
        """自旋等待到下一毫秒。

        Args:
            last_timestamp: 上次生成 ID 的时间戳。

        Returns:
            新的毫秒时间戳。
        """
        now = self._current_ms()
        while now <= last_timestamp:
            now = self._current_ms()
        return now


# 模块级单例：进程内共享一个生成器
# 机器 ID 从环境变量 SNOWFLAKE_MACHINE_ID 读取（默认 1）
snowflake_generator: SnowflakeGenerator = SnowflakeGenerator()


def generate_id() -> int:
    """便捷函数：生成 128 位雪花 ID。

    Returns:
        128 位唯一整数 ID。
    """
    return snowflake_generator.next_id()


def generate_id_str() -> str:
    """便捷函数：生成 Base62 编码的字母数字混合 ID 字符串。

    Returns:
        22 位 Base62 字符串（含 0-9, A-Z, a-z）。
    """
    return base62_encode(snowflake_generator.next_id())
