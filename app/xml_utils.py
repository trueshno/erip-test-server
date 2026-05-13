# app/xml_utils.py
import xml.etree.ElementTree as ET
from xml.dom import minidom


def parse_erip_request(xml_string: str) -> dict:
    """
    Парсит входящий XML от ЕРИП.
    Ожидает структуру:
    <PS_TP_O>
        <RefundRequestId>...</RefundRequestId>
        <OrderId>...</OrderId>
        <Amount>...</Amount>
    </PS_TP_O>
    """
    # Убираем BOM, если есть, и декодируем
    if xml_string.startswith('\ufeff'):
        xml_string = xml_string[1:]

    root = ET.fromstring(xml_string)

    data = {}
    for child in root:
        data[child.tag] = child.text.strip() if child.text else None

    return data


def build_erip_response(code: int, message: str, lang: str = "ru") -> str:
    """
    Формирует ответ в формате ЕРИП (XML, кодировка будет применена при encode('cp1251'))
    """
    # Создаём структуру вручную для полного контроля над форматом
    xml_parts = [
        '<?xml version="1.0" encoding="cp1251"?>',
        '<PS_TP_O>',
        f'    <ErrorCode>{code}</ErrorCode>',
        f'    <ErrorText>{message}</ErrorText>',
        f'    <Lang>{lang}</Lang>',
        '</PS_TP_O>'
    ]
    return '\n'.join(xml_parts)