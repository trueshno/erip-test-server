# app/main.py
from fastapi import FastAPI, File, UploadFile, Request, Depends
from fastapi.responses import Response
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from defusedxml.ElementTree import fromstring
import logging
import time
import uuid
from decimal import Decimal, ROUND_HALF_UP

from .logging_config import setup_logging
from .db_config import get_db
from .models import Transaction, Account, TransactionInfoLine, TransactionError
from typing import Optional

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("🚀 ERIP Billing Service started")
    yield
    logger.info("🛑 ERIP Billing Service stopped")

app = FastAPI(title="ERIP Billing Service", version="2.3.0", lifespan=lifespan)
logger = logging.getLogger(__name__)

@app.post("/erip/refund")
async def handle_erip_request(
    request: Request,
    xml: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    req_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
    start_time = time.time()

    try:
        # 1. Безопасный парсинг XML
        raw_bytes = await xml.read()
        xml_str = raw_bytes.decode("cp1251", errors="replace")
        root = fromstring(xml_str)

        request_type = root.findtext("RequestType")
        personal_acc = root.findtext("PersonalAccount")
        erip_request_id = root.findtext("RequestId")
        currency = root.findtext("Currency", "933")
        terminal = root.findtext("Terminal")
        terminal_type = root.find(".//Terminal").get("Type") if root.find(".//Terminal") is not None else None
        service_no = root.findtext("ServiceNo")
        dt = root.findtext("DateTime")

        # 2. Идемпотентность: если RequestId уже обработан, возвращаем сохранённый ответ
        if erip_request_id:
            res = await db.execute(select(Transaction).where(Transaction.erip_request_id == erip_request_id))
            existing = res.scalar_one_or_none()
            if existing and existing.metadata_json:
                logger.info(f"🔁 Idempotent hit: {erip_request_id}")
                return Response(
                    content=existing.metadata_json.encode("cp1251"),
                    media_type="text/xml; charset=windows-1251",
                    status_code=200
                )

        # 3. Маршрутизация по типу запроса
        if request_type == "ServiceInfo":
            return await handle_service_info(db, req_id, personal_acc, erip_request_id, start_time)
        elif request_type == "TransactionStart":
            amount_str = root.findtext("TransactionStart/Amount")
            erip_trx_id = root.findtext("TransactionStart/TransactionId")
            agent = root.findtext("TransactionStart/Agent")
            auth_type = root.findtext("TransactionStart/AuthorizationType")
            return await handle_transaction_start(
                db, req_id, personal_acc, amount_str, erip_trx_id, 
                agent, auth_type, terminal, terminal_type, 
                erip_request_id, currency, dt, start_time
            )
        else:
            raise ValueError(f"Unsupported RequestType: {request_type}")

    except ValueError as ve:
        logger.warning(f"Validation error: {ve}", extra={"request_id": req_id})
        return Response(content=build_error_xml(str(ve)).encode("cp1251"), media_type="text/xml; charset=windows-1251", status_code=200)
    except Exception as e:
        logger.error(f"Critical error: {e}", extra={"request_id": req_id}, exc_info=True)
        return Response(content=build_error_xml("Внутренняя ошибка сервера").encode("cp1251"), media_type="text/xml; charset=windows-1251", status_code=200)


async def handle_service_info(
    db: AsyncSession, 
    req_id: str, 
    account: Optional[str],
    agent: Optional[str], 
    service_no: Optional[str], 
    erip_req_id: Optional[str], 
    start_time: float
):
    if not account:
        raise ValueError("Не указан лицевой счёт (PersonalAccount)")

    res = await db.execute(select(Account).where(Account.account_number == account))
    acc = res.scalar_one_or_none()
    if not acc or acc.status != "active":
        raise ValueError(f"Лицевой счёт {account} не найден или заблокирован")

    # Маскирование ФИО (Иванов -> И***в)
    def mask(s: str) -> str:
        if not s: return ""
        return f"{s[0]}***{s[-1]}" if len(s) > 2 else s

    # Форматирование чисел с запятой (F12,2)
    def fmt(val) -> str:
        return str(val).replace(".", ",")

    xml_resp = f"""<?xml version="1.0" encoding="windows-1251"?>
<ServiceProvider_Response>
    <ServiceInfo>
        <Amount Editable="{acc.editable_flag}" MinAmount="{fmt(acc.min_amount)}" MaxAmount="{fmt(acc.max_amount)}">
            <Debt>{fmt(acc.debt_amount)}</Debt>
        </Amount>
        <Name>
            <Surname>{mask(acc.holder_surname)}</Surname>
            <FirstName>{mask(acc.holder_firstname)}</FirstName>
            <Patronymic>{mask(acc.holder_patronymic)}</Patronymic>
        </Name>
        <Address>
            <City>{acc.city or ""}</City>
            <Street>{acc.street or ""}</Street>
            <House>{acc.house or ""}</House>
            <Apartment>{acc.apartment or ""}</Apartment>
        </Address>
        <Info>
            <InfoLine>Задолженность по оплате</InfoLine>
            <InfoLine>Составляет: {fmt(acc.debt_amount)}</InfoLine>
        </Info>
    </ServiceInfo>
</ServiceProvider_Response>"""

    # Сохраняем для идемпотентности
    new_tx = Transaction(
        erip_request_id=erip_req_id,
        request_type="ServiceInfo",
        personal_account=account,
        currency="933",
        terminal_id=terminal,
        terminal_type=int(terminal_type) if terminal_type else None,
        status="success",
        processed_at=datetime.now(timezone.utc),
        metadata_json=xml_resp
    )
    db.add(new_tx)
    await db.commit()

    return Response(content=xml_resp.encode("cp1251"), media_type="text/xml; charset=windows-1251", status_code=200)


async def handle_transaction_start(db: AsyncSession, req_id: str, account: str, amount_str: str, 
                                   erip_trx_id: str, agent: str, auth_type: str, 
                                   terminal: str, terminal_type: str, erip_req_id: str, 
                                   currency: str, dt: str, start_time: float):
    if not account: raise ValueError("Не указан лицевой счёт")
    if not amount_str: raise ValueError("Не указана сумма операции")

    try:
        amount = Decimal(amount_str)
        if amount <= 0: raise ValueError("Сумма должна быть больше 0")
    except Exception:
        raise ValueError("Неверный формат суммы")

    res = await db.execute(select(Account).where(Account.account_number == account))
    acc = res.scalar_one_or_none()
    if not acc or acc.status != "active":
        raise ValueError(f"Лицевой счёт {account} не найден")

    # Создаём транзакцию
    new_tx = Transaction(
        erip_request_id=erip_req_id,
        request_type="TransactionStart",
        erip_transaction_id=erip_trx_id,
        personal_account=account,
        amount=amount,  # Decimal сохраняется в Numeric без потерь
        currency=currency,
        terminal_id=terminal,
        terminal_type=int(terminal_type) if terminal_type else None,
        agent_code=int(agent) if agent else None,
        auth_type=auth_type,
        status="success",
        processed_at=datetime.now(timezone.utc)
    )
    db.add(new_tx)
    await db.flush()  # Получаем new_tx.id из sequence Oracle

    # Генерируем ServiceProvider_TrxId (8 цифр)
    service_trx_id = f"{new_tx.id:08d}"
    new_tx.service_trx_id = service_trx_id

    # Сохраняем InfoLine
    info_text = f"Номер операции: {service_trx_id}"
    db.add(TransactionInfoLine(
        transaction_id=new_tx.id,
        line_text=info_text,
        line_order=1
    ))

    # Формируем ответ
    xml_resp = f"""<?xml version="1.0" encoding="windows-1251"?>
<ServiceProvider_Response>
    <TransactionStart>
        <ServiceProvider_TrxId>{service_trx_id}</ServiceProvider_TrxId>
        <Info>
            <InfoLine>{info_text}</InfoLine>
        </Info>
    </TransactionStart>
</ServiceProvider_Response>"""

    new_tx.metadata_json = xml_resp  # Кэшируем для идемпотентности
    await db.commit()

    return Response(content=xml_resp.encode("cp1251"), media_type="text/xml; charset=windows-1251", status_code=200)


def build_error_xml(error_text: str) -> str:
    safe = error_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<?xml version="1.0" encoding="windows-1251"?>
<ServiceProvider_Response>
    <Error>
        <ErrorLine>{safe}</ErrorLine>
    </Error>
</ServiceProvider_Response>"""