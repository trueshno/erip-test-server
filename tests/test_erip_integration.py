# tests/test_erip_integration.py
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db_config import async_session_maker
from app.models import Account, Transaction
from sqlalchemy import delete
import xml.etree.ElementTree as ET
import asyncio

client = TestClient(app)

@pytest.fixture
def test_db():
    """Фикстура для тестовой БД"""
    async def setup():
        async with async_session_maker() as session:
            # Очищаем старые данные
            await session.execute(delete(Transaction))
            await session.execute(delete(Account).where(Account.account_number == "TEST001"))
            
            # Создаем тестовый аккаунт
            test_account = Account(
                account_number="TEST001",
                status="active",
                debt_amount=100.50,
                editable_flag="Y",
                min_amount=10,
                max_amount=1000,
                holder_surname="Иванов",
                holder_firstname="Иван",
                holder_patronymic="Иванович",
                city="Минск",
                street="Ленина",
                house="10",
                apartment="5"
            )
            session.add(test_account)
            await session.commit()
            return session
    
    async def cleanup():
        async with async_session_maker() as session:
            await session.execute(delete(Transaction))
            await session.execute(delete(Account).where(Account.account_number == "TEST001"))
            await session.commit()
    
    # Запускаем setup
    session = asyncio.run(setup())
    yield session
    # Запускаем cleanup
    asyncio.run(cleanup())

def test_service_info(test_db):
    """Тест запроса ServiceInfo"""
    xml_request = '''<?xml version="1.0" encoding="windows-1251"?>
    <Request>
        <RequestType>ServiceInfo</RequestType>
        <PersonalAccount>TEST001</PersonalAccount>
        <RequestId>test-req-001</RequestId>
        <ServiceNo>1</ServiceNo>
    </Request>'''
    
    response = client.post(
        "/erip/refund",
        files={"xml": ("request.xml", xml_request.encode("cp1251"), "text/xml")}
    )
    
    assert response.status_code == 200
    assert "windows-1251" in response.headers["content-type"]
    
    # Парсим ответ
    root = ET.fromstring(response.content.decode("cp1251"))
    debt = root.find(".//Debt")
    assert debt is not None
    assert debt.text == "100,50"

def test_transaction_start(test_db):
    """Тест запроса TransactionStart"""
    xml_request = '''<?xml version="1.0" encoding="windows-1251"?>
    <Request>
        <RequestType>TransactionStart</RequestType>
        <PersonalAccount>TEST001</PersonalAccount>
        <RequestId>test-req-002</RequestId>
        <TransactionStart>
            <Amount>150.00</Amount>
            <TransactionId>TRX-001</TransactionId>
            <Agent>001</Agent>
            <AuthorizationType>PIN</AuthorizationType>
        </TransactionStart>
        <Terminal Type="1">TERM001</Terminal>
        <Currency>933</Currency>
    </Request>'''
    
    response = client.post(
        "/erip/refund",
        files={"xml": ("request.xml", xml_request.encode("cp1251"), "text/xml")}
    )
    
    assert response.status_code == 200
    root = ET.fromstring(response.content.decode("cp1251"))
    service_trx_id = root.findtext(".//ServiceProvider_TrxId")
    assert service_trx_id is not None
    assert len(service_trx_id) == 8

def test_idempotency(test_db):
    """Тест идемпотентности"""
    xml_request = '''<?xml version="1.0" encoding="windows-1251"?>
    <Request>
        <RequestType>ServiceInfo</RequestType>
        <PersonalAccount>TEST001</PersonalAccount>
        <RequestId>test-req-idempotent</RequestId>
    </Request>'''
    
    # Первый запрос
    response1 = client.post(
        "/erip/refund",
        files={"xml": ("request.xml", xml_request.encode("cp1251"), "text/xml")}
    )
    
    # Второй запрос с тем же RequestId
    response2 = client.post(
        "/erip/refund",
        files={"xml": ("request.xml", xml_request.encode("cp1251"), "text/xml")}
    )
    
    assert response1.content == response2.content

def test_account_not_found(test_db):
    """Тест несуществующего аккаунта"""
    xml_request = '''<?xml version="1.0" encoding="windows-1251"?>
    <Request>
        <RequestType>ServiceInfo</RequestType>
        <PersonalAccount>NOTEXIST</PersonalAccount>
        <RequestId>test-req-404</RequestId>
    </Request>'''
    
    response = client.post(
        "/erip/refund",
        files={"xml": ("request.xml", xml_request.encode("cp1251"), "text/xml")}
    )
    
    root = ET.fromstring(response.content.decode("cp1251"))
    error = root.findtext(".//ErrorLine")
    assert error is not None
    assert "не найден" in error