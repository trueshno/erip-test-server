# app/xml_utils.py
"""
Утилиты для работы с XML в сервисе ЕРИП.
Формирование и парсинг XML-сообщений.
"""
import xml.etree.ElementTree as ET
from typing import Optional, cast
from .models import Account


def parse_erip_request(xml_string: str) -> dict:
    """
    Парсит входящий XML от ЕРИП.
    
    Ожидаемая структура:
    <PS_TP_O>
        <RefundRequestId>...</RefundRequestId>
        <OrderId>...</OrderId>
        <Amount>...</Amount>
    </PS_TP_O>
    
    Args:
        xml_string: Строка XML
        
    Returns:
        Словарь с данными запроса
    """
    # Убираем BOM, если есть
    if xml_string.startswith('\ufeff'):
        xml_string = xml_string[1:]

    root = ET.fromstring(xml_string)

    data = {}
    for child in root:
        data[child.tag] = child.text.strip() if child.text else None

    return data


def build_service_info_xml(account: Account) -> str:
    """
    Формирует XML-ответ для запроса ServiceInfo.
    
    Args:
        account: Объект счёта абонента
        
    Returns:
        XML-строка в кодировке Windows-1251
    """
    def mask(value: Optional[str]) -> str:
        """Маскирует ФИО (первая и последняя буквы)."""
        if not value:
            return ""
        return f"{value[0]}***{value[-1]}" if len(value) > 2 else value

    def format_decimal(value) -> str:
        """Форматирует десятичное число для XML (замена точки на запятую)."""
        if value is None:
            return "0,00"
        return str(value).replace(".", ",")

    # Безопасное извлечение полей
    surname = cast(Optional[str], account.holder_surname)
    firstname = cast(Optional[str], account.holder_firstname)
    patronymic = cast(Optional[str], account.holder_patronymic)
    city = cast(Optional[str], account.city)
    street = cast(Optional[str], account.street)
    house = cast(Optional[str], account.house)
    apartment = cast(Optional[str], account.apartment)
    editable = cast(Optional[str], account.editable_flag)

    xml_parts = [
        '<?xml version="1.0" encoding="windows-1251"?>',
        '<ServiceProvider_Response>',
        '    <ServiceInfo>',
        f'        <Amount Editable="{editable or "N"}" MinAmount="{format_decimal(account.min_amount)}" MaxAmount="{format_decimal(account.max_amount)}">',
        f'            <Debt>{format_decimal(account.debt_amount)}</Debt>',
        '        </Amount>',
        '        <Name>',
        f'            <Surname>{mask(surname)}</Surname>',
        f'            <FirstName>{mask(firstname)}</FirstName>',
        f'            <Patronymic>{mask(patronymic)}</Patronymic>',
        '        </Name>',
        '        <Address>',
        f'            <City>{city or ""}</City>',
        f'            <Street>{street or ""}</Street>',
        f'            <House>{house or ""}</House>',
        f'            <Apartment>{apartment or ""}</Apartment>',
        '        </Address>',
        '        <Info>',
        '            <InfoLine>Задолженность по оплате</InfoLine>',
        f'            <InfoLine>Составляет: {format_decimal(account.debt_amount)}</InfoLine>',
        '        </Info>',
        '    </ServiceInfo>',
        '</ServiceProvider_Response>'
    ]
    return '\n'.join(xml_parts)


def build_transaction_start_xml(service_trx_id: str, info_text: str) -> str:
    """
    Формирует XML-ответ для запроса TransactionStart.
    
    Args:
        service_trx_id: Внутренний ID транзакции сервиса
        info_text: Текст информационного сообщения
        
    Returns:
        XML-строка в кодировке Windows-1251
    """
    xml_parts = [
        '<?xml version="1.0" encoding="windows-1251"?>',
        '<ServiceProvider_Response>',
        '    <TransactionStart>',
        f'        <ServiceProvider_TrxId>{service_trx_id}</ServiceProvider_TrxId>',
        '        <Info>',
        f'            <InfoLine>{info_text}</InfoLine>',
        '        </Info>',
        '    </TransactionStart>',
        '</ServiceProvider_Response>'
    ]
    return '\n'.join(xml_parts)


def build_error_response_xml(error_text: str) -> bytes:
    """
    Формирует XML-ответ с ошибкой.
    
    Args:
        error_text: Текст ошибки
        
    Returns:
        Закодированная XML-строка (Windows-1251)
    """
    # Экранирование специальных символов XML
    safe_text = (
        error_text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    
    xml_parts = [
        '<?xml version="1.0" encoding="windows-1251"?>',
        '<ServiceProvider_Response>',
        '    <Error>',
        f'        <ErrorLine>{safe_text}</ErrorLine>',
        '    </Error>',
        '</ServiceProvider_Response>'
    ]
    return '\n'.join(xml_parts).encode("cp1251")