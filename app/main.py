# app/main.py
"""
ERIP Billing Service - основной модуль обработки запросов.
Версия: 2.3.1
"""
from fastapi import FastAPI, File, UploadFile, Request, Depends, HTTPException
from fastapi.responses import Response
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from defusedxml.ElementTree import fromstring
import logging
import time
import uuid
from decimal import Decimal, InvalidOperation
from typing import Optional, cast

from .logging_config import setup_logging
from .db_config import get_db
from .models import Transaction, Account, TransactionInfoLine
from .handlers import handle_service_info_request, handle_transaction_start_request
from .xml_utils import build_error_response_xml

# ==========================================
# НАСТРОЙКА ПРИЛОЖЕНИЯ
# ==========================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("🚀 ERIP Billing Service started")
    yield
    logger.info("🛑 ERIP Billing Service stopped")


app = FastAPI(
    title="ERIP Billing Service",
    version="2.3.1",
    description="Сервис обработки запросов ЕРИП (ServiceInfo, TransactionStart)",
    lifespan=lifespan
)
logger = logging.getLogger(__name__)


# ==========================================
# ОСНОВНОЙ ЭНДПОИНТ
# ==========================================

@app.post("/erip/refund", tags=["ERIP"])
async def handle_erip_request(
    request: Request,
    xml: UploadFile = File(..., description="XML-запрос от ЕРИП"),
    db: AsyncSession = Depends(get_db)
):
    """
    Обрабатывает входящие запросы от ЕРИП.
    
    Поддерживаемые типы запросов:
    - ServiceInfo: информация о счёте абонента
    - TransactionStart: начало транзакции оплаты
    
    Возвращает XML-ответ в кодировке Windows-1251.
    """
    req_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
    start_time = time.time()

    try:
        # Чтение и парсинг XML
        raw_bytes = await xml.read()
        xml_str = raw_bytes.decode("cp1251", errors="replace")
        root = fromstring(xml_str)

        # Извлечение основных полей
        request_type = root.findtext("RequestType")
        personal_acc = root.findtext("PersonalAccount")
        erip_request_id = root.findtext("RequestId")
        currency = root.findtext("Currency", "933")
        
        # Данные терминала
        terminal_elem = root.find(".//Terminal")
        terminal = terminal_elem.text if terminal_elem is not None else None
        terminal_type = terminal_elem.get("Type") if terminal_elem is not None else None
        
        service_no = root.findtext("ServiceNo")
        dt = root.findtext("DateTime")

        # Проверка идемпотентности
        if erip_request_id:
            existing_transaction = await _check_idempotency(db, erip_request_id)
            if existing_transaction:
                logger.info(f"🔁 Idempotent hit: {erip_request_id}")
                return Response(
                    content=cast(str, existing_transaction.metadata_json).encode("cp1251"),
                    media_type="text/xml; charset=windows-1251",
                    status_code=200
                )

        # Маршрутизация по типу запроса
        if request_type == "ServiceInfo":
            return await handle_service_info_request(
                db=db,
                request_id=req_id,
                account=personal_acc,
                erip_request_id=erip_request_id,
                start_time=start_time,
                terminal=terminal,
                terminal_type=terminal_type
            )
        elif request_type == "TransactionStart":
            trx_start = root.find("TransactionStart")
            if trx_start is None:
                raise ValueError("Отсутствует элемент TransactionStart")
                
            return await handle_transaction_start_request(
                db=db,
                request_id=req_id,
                account=personal_acc or "",
                amount_str=trx_start.findtext("Amount") or "",
                erip_transaction_id=trx_start.findtext("TransactionId") or "",
                agent=trx_start.findtext("Agent") or "",
                auth_type=trx_start.findtext("AuthorizationType") or "",
                terminal=terminal or "",
                terminal_type=terminal_type or "",
                erip_request_id=erip_request_id or "",
                currency=currency or "933",
                datetime_str=dt or "",
                start_time=start_time
            )
        else:
            raise ValueError(f"Неподдерживаемый тип запроса: {request_type}")

    except ValueError as ve:
        logger.warning(f"Validation error: {ve}", extra={"request_id": req_id})
        return Response(
            content=build_error_response_xml(str(ve)),
            media_type="text/xml; charset=windows-1251",
            status_code=200
        )
    except Exception as e:
        logger.error(f"Critical error: {e}", extra={"request_id": req_id}, exc_info=True)
        return Response(
            content=build_error_response_xml("Внутренняя ошибка сервера"),
            media_type="text/xml; charset=windows-1251",
            status_code=200
        )


async def _check_idempotency(db: AsyncSession, erip_request_id: str) -> Optional[Transaction]:
    """
    Проверяет наличие ранее обработанного запроса с таким же ID.
    
    Args:
        db: Сессия базы данных
        erip_request_id: Уникальный идентификатор запроса ЕРИП
    
    Returns:
        Существующую транзакцию или None
    """
    result = await db.execute(
        select(Transaction).where(Transaction.erip_request_id == erip_request_id)
    )
    transaction = result.scalar_one_or_none()
    
    if transaction and cast(Optional[str], transaction.metadata_json):
        return transaction
    return None