# app/main.py
from fastapi import FastAPI, File, UploadFile, Request, Depends
from fastapi.responses import Response
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from datetime import datetime, timezone
from defusedxml.ElementTree import fromstring
import logging
import time
import uuid
from decimal import Decimal
from typing import Optional, cast

from .logging_config import setup_logging
from .db_config import get_db
from .models import Transaction, Account, TransactionInfoLine

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("🚀 ERIP Billing Service started")
    yield
    logger.info("🛑 ERIP Billing Service stopped")

app = FastAPI(title="ERIP Billing Service", version="2.3.1", lifespan=lifespan)
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
        raw_bytes = await xml.read()
        xml_str = raw_bytes.decode("cp1251", errors="replace")
        root = fromstring(xml_str)

        request_type = root.findtext("RequestType")
        personal_acc = root.findtext("PersonalAccount")
        erip_request_id = root.findtext("RequestId")
        currency = root.findtext("Currency", "933")
        
        terminal_elem = root.find(".//Terminal")
        terminal = terminal_elem.text if terminal_elem is not None else None
        terminal_type = terminal_elem.get("Type") if terminal_elem is not None else None
        
        service_no = root.findtext("ServiceNo")
        dt = root.findtext("DateTime")

        # Идемпотентность
        if erip_request_id:
            res = await db.execute(
                select(Transaction).where(Transaction.erip_request_id == erip_request_id)
            )
            existing = res.scalar_one_or_none()
            # 🔧 cast: явно говорим Pylance, что existing — это Transaction или None
            if existing and cast(Optional[str], existing.metadata_json):
                logger.info(f"🔁 Idempotent hit: {erip_request_id}")
                return Response(
                    content=cast(str, existing.metadata_json).encode("cp1251"),
                    media_type="text/xml; charset=windows-1251",
                    status_code=200
                )

        if request_type == "ServiceInfo":
            return await handle_service_info(
                db=db, req_id=req_id, account=personal_acc,
                erip_req_id=erip_request_id, start_time=start_time,
                terminal=terminal, terminal_type=terminal_type
            )
        elif request_type == "TransactionStart":
            amount_str = root.findtext("TransactionStart/Amount")
            erip_trx_id = root.findtext("TransactionStart/TransactionId")
            agent = root.findtext("TransactionStart/Agent")
            auth_type = root.findtext("TransactionStart/AuthorizationType")
            
            return await handle_transaction_start(
                db=db, req_id=req_id,
                account=personal_acc or "",
                amount_str=amount_str or "",
                erip_trx_id=erip_trx_id or "",
                agent=agent or "",
                auth_type=auth_type or "",
                terminal=terminal or "",
                terminal_type=terminal_type or "",
                erip_req_id=erip_request_id or "",
                currency=currency or "933",
                dt=dt or "",
                start_time=start_time
            )
        else:
            raise ValueError(f"Unsupported RequestType: {request_type}")

    except ValueError as ve:
        logger.warning(f"Validation error: {ve}", extra={"request_id": req_id})
        return Response(
            content=build_error_xml(str(ve)).encode("cp1251"),
            media_type="text/xml; charset=windows-1251",
            status_code=200
        )
    except Exception as e:
        logger.error(f"Critical error: {e}", extra={"request_id": req_id}, exc_info=True)
        return Response(
            content=build_error_xml("Внутренняя ошибка сервера").encode("cp1251"),
            media_type="text/xml; charset=windows-1251",
            status_code=200
        )


async def handle_service_info(
    db: AsyncSession,
    req_id: str,
    account: Optional[str],
    erip_req_id: Optional[str],
    start_time: float,
    terminal: Optional[str],
    terminal_type: Optional[str]
):
    if not account:
        raise ValueError("Не указан лицевой счёт (PersonalAccount)")

    res = await db.execute(select(Account).where(Account.account_number == account))
    acc = res.scalar_one_or_none()
    
    if not acc or cast(Optional[str], acc.status) != "active":  # 🔧 cast для status
        raise ValueError(f"Лицевой счёт {account} не найден или заблокирован")

    def mask(s: Optional[str]) -> str:
        if not s:
            return ""
        return f"{s[0]}***{s[-1]}" if len(s) > 2 else s

    def fmt(val) -> str:
        if val is None:
            return "0,00"
        return str(val).replace(".", ",")

    # 🔧 cast: явно приводим поля Account к str | None для Pylance
    surname = cast(Optional[str], acc.holder_surname)
    firstname = cast(Optional[str], acc.holder_firstname)
    patronymic = cast(Optional[str], acc.holder_patronymic)
    city = cast(Optional[str], acc.city)
    street = cast(Optional[str], acc.street)
    house = cast(Optional[str], acc.house)
    apartment = cast(Optional[str], acc.apartment)
    editable = cast(Optional[str], acc.editable_flag)
    min_amt = acc.min_amount
    max_amt = acc.max_amount
    debt = acc.debt_amount

    xml_resp = f"""<?xml version="1.0" encoding="windows-1251"?>
<ServiceProvider_Response>
    <ServiceInfo>
        <Amount Editable="{editable or 'N'}" MinAmount="{fmt(min_amt)}" MaxAmount="{fmt(max_amt)}">
            <Debt>{fmt(debt)}</Debt>
        </Amount>
        <Name>
            <Surname>{mask(surname)}</Surname>
            <FirstName>{mask(firstname)}</FirstName>
            <Patronymic>{mask(patronymic)}</Patronymic>
        </Name>
        <Address>
            <City>{city or ""}</City>
            <Street>{street or ""}</Street>
            <House>{house or ""}</House>
            <Apartment>{apartment or ""}</Apartment>
        </Address>
        <Info>
            <InfoLine>Задолженность по оплате</InfoLine>
            <InfoLine>Составляет: {fmt(debt)}</InfoLine>
        </Info>
    </ServiceInfo>
</ServiceProvider_Response>"""

    new_tx = Transaction(
        erip_request_id=erip_req_id,
        request_type="ServiceInfo",
        personal_account=account,
        currency="933",
        terminal_id=terminal,
        terminal_type=int(terminal_type) if terminal_type and terminal_type.isdigit() else None,
        status="success",
        processed_at=datetime.now(timezone.utc),
        metadata_json=xml_resp
    )
    db.add(new_tx)
    await db.commit()

    return Response(
        content=xml_resp.encode("cp1251"),
        media_type="text/xml; charset=windows-1251",
        status_code=200
    )


async def handle_transaction_start(
    db: AsyncSession,
    req_id: str,
    account: str,
    amount_str: str,
    erip_trx_id: str,
    agent: str,
    auth_type: str,
    terminal: str,
    terminal_type: str,
    erip_req_id: str,
    currency: str,
    dt: str,
    start_time: float
):
    if not account:
        raise ValueError("Не указан лицевой счёт")
    if not amount_str:
        raise ValueError("Не указана сумма операции")

    try:
        amount = Decimal(amount_str)
        if amount <= 0:
            raise ValueError("Сумма должна быть больше 0")
    except Exception:
        raise ValueError("Неверный формат суммы")

    res = await db.execute(select(Account).where(Account.account_number == account))
    acc = res.scalar_one_or_none()
    if not acc or cast(Optional[str], acc.status) != "active":
        raise ValueError(f"Лицевой счёт {account} не найден")

    new_tx = Transaction(
        erip_request_id=erip_req_id,
        request_type="TransactionStart",
        erip_transaction_id=erip_trx_id,
        personal_account=account,
        amount=float(amount),
        currency=currency,
        terminal_id=terminal if terminal else None,
        terminal_type=int(terminal_type) if terminal_type and terminal_type.isdigit() else None,
        agent_code=int(agent) if agent and agent.isdigit() else None,
        auth_type=auth_type if auth_type else None,
        status="success",
        processed_at=datetime.now(timezone.utc)
    )
    db.add(new_tx)
    await db.flush()

    service_trx_id = f"{cast(int, new_tx.id):08d}"
    new_tx.service_trx_id = service_trx_id  # type: ignore[assignment]

    info_text = f"Номер операции: {service_trx_id}"
    db.add(TransactionInfoLine(
        transaction_id=cast(int, new_tx.id),
        line_text=info_text,
        line_order=1
    ))

    xml_resp = f"""<?xml version="1.0" encoding="windows-1251"?>
<ServiceProvider_Response>
    <TransactionStart>
        <ServiceProvider_TrxId>{service_trx_id}</ServiceProvider_TrxId>
        <Info>
            <InfoLine>{info_text}</InfoLine>
        </Info>
    </TransactionStart>
</ServiceProvider_Response>"""

    new_tx.metadata_json = xml_resp  # type: ignore[assignment]
    await db.commit()

    return Response(
        content=xml_resp.encode("cp1251"),
        media_type="text/xml; charset=windows-1251",
        status_code=200
    )


def build_error_xml(error_text: str) -> str:
    safe = error_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<?xml version="1.0" encoding="windows-1251"?>
<ServiceProvider_Response>
    <Error>
        <ErrorLine>{safe}</ErrorLine>
    </Error>
</ServiceProvider_Response>"""