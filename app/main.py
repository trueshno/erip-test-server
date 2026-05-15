# app/main.py
from fastapi import FastAPI, File, UploadFile, Request, Depends, HTTPException
from fastapi.responses import Response
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from defusedxml.ElementTree import fromstring
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import logging, uuid, time, xml.sax.saxutils
from typing import Optional

from .logging_config import setup_logging
from .db_config import get_db, engine
from .models import Account, Transaction
from .xml_utils import build_service_info_xml, build_error_response_xml

# ==========================================
# НАСТРОЙКА
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("🚀 ERIP Billing Service started")
    yield
    logger.info("🛑 ERIP Billing Service stopped")

app = FastAPI(title="ERIP Billing Service", version="2.3.2", lifespan=lifespan)
logger = logging.getLogger(__name__)


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def fmt_erip(val) -> str:
    """Форматирует число для ЕРИП: 30.21 → 30,21"""
    if val is None:
        return "0,00"
    try:
        return f"{float(Decimal(str(val))):.2f}".replace(".", ",")
    except (InvalidOperation, ValueError, TypeError):
        return "0,00"

def mask_name(s: Optional[str]) -> str:
    """Маскирует ФИО: Иванов → И***в"""
    if not s:
        return ""
    s = s.strip()
    return s if len(s) <= 2 else f"{s[0]}***{s[-1]}"

def mask_address(s: Optional[str]) -> str:
    """Маскирует адрес: Минск → М***к"""
    return mask_name(s)

def _xml_safe(text: Optional[str]) -> str:
    """Экранирует спецсимволы для XML"""
    if not text:
        return ""
    return xml.sax.saxutils.escape(str(text).strip())


# ==========================================
# ОСНОВНОЙ ЭНДПОИНТ
# ==========================================

@app.post("/erip/refund")
async def handle_erip_request(
    request: Request,
    xml: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    req_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
    start_time = time.time()

    try:
        # 1. Чтение и парсинг XML
        raw_bytes = await xml.read()
        xml_str = raw_bytes.decode("cp1251", errors="replace")
        root = fromstring(xml_str)

        # 2. Извлечение полей
        request_type = (root.findtext("RequestType") or "").strip()
        personal_acc = (root.findtext("PersonalAccount") or "").strip()
        erip_request_id = (root.findtext("RequestId") or "").strip()
        currency = root.findtext("Currency", "933")
        
        terminal_elem = root.find(".//Terminal")
        terminal = terminal_elem.text if terminal_elem is not None else None
        terminal_type = terminal_elem.get("Type") if terminal_elem is not None else None

        logger.debug(f"🔍 Parsed: type='{request_type}', account='{personal_acc}', req_id='{erip_request_id}'")

        # 3. Идемпотентность (с учётом типа запроса!)
        if erip_request_id:
            res = await db.execute(
                select(Transaction).where(
                    Transaction.erip_request_id == erip_request_id,
                    Transaction.request_type == request_type  # ✅ Ключевое исправление
                )
            )
            existing = res.scalar_one_or_none()
            if existing and getattr(existing, "metadata_json", None):
                logger.info(f"🔁 Idempotent hit: {erip_request_id} ({request_type})")
                return Response(
                    content=getattr(existing, "metadata_json").encode("cp1251"),
                    headers={"Content-Type": "text/xml; charset=windows-1251"},
                    status_code=200
                )

        # 4. Маршрутизация
        if request_type == "ServiceInfo":
            return await _handle_service_info(
                db=db,
                request_id=req_id,
                account=personal_acc,
                erip_request_id=erip_request_id,
                start_time=start_time,
                terminal=terminal,
                terminal_type=terminal_type
            )
        else:
            # Для остальных типов — заглушка с понятной ошибкой
            logger.warning(f"⚠️ Unsupported RequestType: '{request_type}'")
            raise ValueError(f"Неподдерживаемый тип запроса: {request_type}")

    except ValueError as ve:
        logger.warning(f"Validation error: {ve}", extra={"request_id": req_id})
        return Response(
            content=build_error_response_xml(str(ve)).encode("cp1251"),
            headers={"Content-Type": "text/xml; charset=windows-1251"},
            status_code=200
        )
    except Exception as e:
        logger.error(f"Critical error: {e}", extra={"request_id": req_id}, exc_info=True)
        return Response(
            content=build_error_response_xml("Внутренняя ошибка сервера").encode("cp1251"),
            headers={"Content-Type": "text/xml; charset=windows-1251"},
            status_code=200
        )


# ==========================================
# ОБРАБОТЧИК ServiceInfo
# ==========================================

async def _handle_service_info(
    db: AsyncSession,
    request_id: str,
    account: Optional[str],
    erip_request_id: Optional[str],
    start_time: float,
    terminal: Optional[str],
    terminal_type: Optional[str]
) -> Response:
    """Обработчик запроса ServiceInfo с чтением из БД"""
    
    # 1. Валидация
    if not account:
        raise ValueError("Не указан лицевой счёт (PersonalAccount)")
    
    # 2. Поиск счёта в БД
    result = await db.execute(
        select(Account).where(Account.account_number == account)
    )
    acc = result.scalar_one_or_none()
    
    if not acc:
        raise ValueError(f"Лицевой счёт {account} не найден")
    
    if getattr(acc, "status", "active") != "active":
        raise ValueError(f"Лицевой счёт {account} заблокирован")
    
    # 3. Формирование ответа через xml_utils (или напрямую)
    # Вариант А: через билдер из xml_utils (рекомендую)
    # xml_response = build_service_info_xml(acc)
    
    # Вариант Б: напрямую здесь (для полного контроля)
    editable = (getattr(acc, "editable_flag", "N") or "N").upper()
    if editable not in ("Y", "N"):
        editable = "N"
    
    min_amt = fmt_erip(getattr(acc, "min_amount", 0))
    max_amt = fmt_erip(getattr(acc, "max_amount", 100000))
    debt = fmt_erip(getattr(acc, "debt_amount", 0))
    
    surname = _xml_safe(mask_name(getattr(acc, "holder_surname", "")))
    firstname = _xml_safe(mask_name(getattr(acc, "holder_firstname", "")))
    patronymic = _xml_safe(mask_name(getattr(acc, "holder_patronymic", "")))
    city = _xml_safe(mask_address(getattr(acc, "city", "")))
    street = _xml_safe(mask_address(getattr(acc, "street", "")))
    house = _xml_safe(getattr(acc, "house", ""))
    apartment = _xml_safe(getattr(acc, "apartment", ""))
    
    xml_response = f"""<?xml version="1.0" encoding="windows-1251"?>
<ServiceProvider_Response>
    <ServiceInfo>
        <Amount Editable="{editable}" MinAmount="{min_amt}" MaxAmount="{max_amt}">
            <Debt>{debt}</Debt>
        </Amount>
        <Name>
            <Surname>{surname}</Surname>
            <FirstName>{firstname}</FirstName>
            <Patronymic>{patronymic}</Patronymic>
        </Name>
        <Address>
            <City>{city}</City>
            <Street>{street}</Street>
            <House>{house}</House>
            <Apartment>{apartment}</Apartment>
        </Address>
        <Info>
            <InfoLine>Задолженность по оплате</InfoLine>
            <InfoLine>Составляет: {debt}</InfoLine>
        </Info>
    </ServiceInfo>
</ServiceProvider_Response>"""
    
    # 4. Сохранение для идемпотентности
    if erip_request_id:
        new_tx = Transaction(
            erip_request_id=erip_request_id,
            request_type="ServiceInfo",
            personal_account=account,
            currency="933",
            terminal_id=terminal,
            terminal_type=int(terminal_type) if terminal_type and terminal_type.isdigit() else None,
            status="success",
            processed_at=datetime.now(timezone.utc),
            metadata_json=xml_response
        )
        db.add(new_tx)
        await db.commit()
    
    elapsed = time.time() - start_time
    logger.info(f"✅ ServiceInfo для {account} обработан за {elapsed:.3f}с", extra={"request_id": request_id})
    
    # 5. Возврат ответа
    return Response(
        content=xml_response.encode("cp1251"),
        headers={"Content-Type": "text/xml; charset=windows-1251"},
        status_code=200
    )


# ==========================================
# HEALTH CHECK (для мониторинга)
# ==========================================

@app.get("/health")
async def health_check():
    try:
        async with engine.connect() as conn:
            await conn.execute(select(1))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "error", "db": "disconnected"}, 503