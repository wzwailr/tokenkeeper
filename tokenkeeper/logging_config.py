"""tokenkeeper 结构化日志模块。

提供 JSON 格式日志 + 级别控制，生产环境友好。

用法::

    from tokenkeeper.logging import setup_logging
    setup_logging(level="INFO", json_format=True)

环境变量::

    TOKENKEEPER_LOG_LEVEL=DEBUG
    TOKENKEEPER_LOG_JSON=1
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional


class JSONFormatter(logging.Formatter):
    """JSON 格式日志（便于 ELK / Loki 采集）。"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    log_file: Optional[str] = None,
) -> None:
    """配置 tokenkeeper 全局日志。

    Args:
        level: 日志级别（DEBUG / INFO / WARNING / ERROR）
        json_format: 是否输出 JSON 格式（默认 False = 纯文本）
        log_file: 日志文件路径（None = stdout）
    """
    # 环境变量覆盖
    level = os.environ.get("TOKENKEEPER_LOG_LEVEL", level).upper()
    json_format = json_format or os.environ.get("TOKENKEEPER_LOG_JSON", "") == "1"

    root = logging.getLogger("tokenkeeper")
    root.setLevel(getattr(logging, level, logging.INFO))
    root.handlers.clear()

    handler: logging.Handler
    if log_file:
        handler = logging.FileHandler(log_file, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stdout)

    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """获取 tokenkeeper 子模块 logger。"""
    return logging.getLogger(f"tokenkeeper.{name}")
