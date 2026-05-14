# app/main.py — ВРЕМЕННАЯ ЗАГЛУШКА ДЛЯ ТЕСТА
from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import Response
from defusedxml.ElementTree import fromstring
import logging

app = FastAPI(title="ERIP Test", version="0.0.1")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.post("/erip/refund")
async def handle_erip_request(request: Request, xml: UploadFile = File(...)):
    req_id = request.headers.get("X-Request-ID", "test")
    logger.info(f"📥 [{req_id}] Получен запрос")
    
    try:
        raw = await xml.read()
        xml_str = raw.decode("cp1251", errors="replace")
        logger.info(f"🔍 Распарсено: {xml_str[:100]}...")
        
        root = fromstring(xml_str)
        req_type = root.findtext("RequestType")
        logger.info(f"📋 Тип запроса: {req_type}")
        
        # ✅ Простой ответ без БД
        response_xml = f"""<?xml version="1.0" encoding="windows-1251"?>
<ServiceProvider_Response>
    <ServiceInfo>
        <Amount Editable="N" MinAmount="0,00" MaxAmount="1000,00">
            <Debt>30,21</Debt>
        </Amount>
        <Name>
            <Surname>Т***т</Surname>
            <FirstName>Е***т</FirstName>
            <Patronymic>С***т</Patronymic>
        </Name>
        <Address>
            <City>М***к</City>
            <Street>ул. Т***ая</Street>
            <House>1</House>
            <Apartment>1</Apartment>
        </Address>
    </ServiceInfo>
</ServiceProvider_Response>"""
        
        logger.info(f"✅ [{req_id}] Отправляем ответ")
        return Response(
            content=response_xml.encode("cp1251"),
            headers={"Content-Type": "text/xml; charset=windows-1251"},
            status_code=200
        )
        
    except Exception as e:
        logger.error(f"❌ [{req_id}] Ошибка: {e}", exc_info=True)
        error_xml = """<?xml version="1.0" encoding="windows-1251"?>
<ServiceProvider_Response>
    <Error><ErrorLine>Тестовая ошибка</ErrorLine></Error>
</ServiceProvider_Response>"""
        return Response(
            content=error_xml.encode("cp1251"),
            headers={"Content-Type": "text/xml; charset=windows-1251"},
            status_code=200
        )