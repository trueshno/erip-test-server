# app/handlers.py
"""
Обработчики запросов ЕРИП: ServiceInfo и TransactionStart.
"""
from sqlalchemy.orm import Session
from sqlalchemy import select
from fastapi.responses import Response
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import logging
from typing import Optional, cast

from .models import Transaction, Account, TransactionInfoLine
from .xml_utils import build_service_info_xml, build_transaction_start_xml

logger = logging.getLogger(__name__)


def handle_service_info_request(
    db: Session,
    request_id: str,
    account: Optional[str],
    erip_request_id: Optional[str],
    start_time: float,
    terminal: Optional[str],
    terminal_type: Optional[str]
) -> Response:
    """
    Обрабатывает запрос ServiceInfo - информация о счёте абонента.
    
    Args:
        db: Сессия базы данных
        request_id: ID запроса для логирования
        account: Лицевой счёт абонента
        erip_request_id: Уникальный ID запроса ЕРИП
        start_time: Время начала обработки
        terminal: ID терминала
        terminal_type: Тип терминала
    
    Returns:
        XML-ответ с информацией о счёте
    
    Raises:
        ValueError: Если счёт не указан или не найден
    """
    if not account:
        raise ValueError("Не указан лицевой счёт (PersonalAccount)")

    # Поиск счёта в базе
    result = db.execute(
        select(Account).where(Account.account_number == account)
    )
    acc = result.scalar_one_or_none()
    
    if not acc or cast(Optional[str], acc.status) != "active":
        raise ValueError(f"Лицевой счёт {account} не найден или заблокирован")

    # Формирование XML-ответа
    xml_response = build_service_info_xml(acc)

    # Сохранение транзакции
    transaction = Transaction(
        erip_request_id=erip_request_id,
        request_type="ServiceInfo",
        personal_account=account,
        currency="933",
        terminal_id=terminal,
        terminal_type=_parse_int(terminal_type),
        status="success",
        processed_at=datetime.now(timezone.utc),
        metadata_json=xml_response
    )
    db.add(transaction)
    db.commit()

    return Response(
        content=xml_response.encode("cp1251"),
        media_type="text/xml; charset=windows-1251",
        status_code=200
    )


def handle_transaction_start_request(
    db: Session,
    request_id: str,
    account: str,
    amount_str: str,
    erip_transaction_id: str,
    agent: str,
    auth_type: str,
    terminal: str,
    terminal_type: str,
    erip_request_id: str,
    currency: str,
    datetime_str: str,
    start_time: float
) -> Response:
    """
    Обрабатывает запрос TransactionStart - начало транзакции оплаты.
    
    Args:
        db: Сессия базы данных
        request_id: ID запроса для логирования
        account: Лицевой счёт абонента
        amount_str: Сумма транзакции (строка)
        erip_transaction_id: ID транзакции от ЕРИП
        agent: Код агента
        auth_type: Тип авторизации
        terminal: ID терминала
        terminal_type: Тип терминала
        erip_request_id: Уникальный ID запроса ЕРИП
        currency: Код валюты
        datetime_str: Дата и время операции
        start_time: Время начала обработки
    
    Returns:
        XML-ответ с ID транзакции
    
    Raises:
        ValueError: Если параметры некорректны
    """
    if not account:
        raise ValueError("Не указан лицевой счёт")
    if not amount_str:
        raise ValueError("Не указана сумма операции")

    # Валидация суммы
    try:
        amount = Decimal(amount_str)
        if amount <= 0:
            raise ValueError("Сумма должна быть больше 0")
    except InvalidOperation:
        raise ValueError("Неверный формат суммы")

    # Проверка счёта
    result = db.execute(
        select(Account).where(Account.account_number == account)
    )
    acc = result.scalar_one_or_none()
    if not acc or cast(Optional[str], acc.status) != "active":
        raise ValueError(f"Лицевой счёт {account} не найден")

    # Создание транзакции
    transaction = Transaction(
        erip_request_id=erip_request_id,
        request_type="TransactionStart",
        erip_transaction_id=erip_transaction_id,
        personal_account=account,
        amount=float(amount),
        currency=currency,
        terminal_id=terminal if terminal else None,
        terminal_type=_parse_int(terminal_type),
        agent_code=_parse_int(agent),
        auth_type=auth_type if auth_type else None,
        status="success",
        processed_at=datetime.now(timezone.utc)
    )
    db.add(transaction)
    db.flush()

    # Генерация ID транзакции сервиса
    service_trx_id = f"{cast(int, transaction.id):08d}"
    transaction.service_trx_id = service_trx_id  # type: ignore[assignment]

    # Добавление строки информации
    info_text = f"Номер операции: {service_trx_id}"
    db.add(TransactionInfoLine(
        transaction_id=cast(int, transaction.id),
        line_text=info_text,
        line_order=1
    ))

    # Формирование XML-ответа
    xml_response = build_transaction_start_xml(service_trx_id, info_text)
    transaction.metadata_json = xml_response  # type: ignore[assignment]
    db.commit()

    return Response(
        content=xml_response.encode("cp1251"),
        media_type="text/xml; charset=windows-1251",
        status_code=200
    )


def _parse_int(value: Optional[str]) -> Optional[int]:
    """Безопасное преобразование строки в целое число."""
    if value and value.isdigit():
        return int(value)
    return None