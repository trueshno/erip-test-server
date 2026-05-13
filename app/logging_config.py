# app/logging_config.py — минималистичная версия, без внешних зависимостей
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

def setup_logging(log_dir: str = "logs", level: str = "INFO"):
    """
    Профессиональное логирование для биллинга ЕРИП.
    - Уровни: INFO / WARNING / ERROR
    - Контекст: request_id, personal_account, trx_id, duration_ms
    - Ротация: 10 МБ, 5-10 архивов
    - Без внешних зависимостей
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Человекочитаемый формат с контекстом
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s | req_id=%(request_id)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # INFO: ротируемый файл (10 МБ, 5 архивов)
    info_handler = RotatingFileHandler(
        log_path / "info.log",
        maxBytes=10*1024*1024,  # 10 МБ
        backupCount=5,
        encoding='utf-8',
        delay=True
    )
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(formatter)
    info_handler.addFilter(lambda r: r.levelno < logging.ERROR)
    
    # ERROR: отдельный файл (храним дольше)
    error_handler = RotatingFileHandler(
        log_path / "error.log",
        maxBytes=10*1024*1024,
        backupCount=10,
        encoding='utf-8',
        delay=True
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    
    # Корневой логгер
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper()))
    root.addHandler(info_handler)
    root.addHandler(error_handler)
    
    # Отключаем шумные сторонние логи
    logging.getLogger('uvicorn.access').propagate = False
    logging.getLogger('multipart').setLevel(logging.WARNING)
    
    return root