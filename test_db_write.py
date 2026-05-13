# test_db_write.py (исправленная версия)
import asyncio
import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

# Добавляем корень проекта в PATH
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# Импортируем через абсолютный путь
from app.db_config import async_session_maker
from app.models import Transaction  # ← теперь Pylance должен видеть

load_dotenv()

async def test_write():
    async with async_session_maker() as db:
        try:
            test_tx = Transaction(
                erip_request_id="TEST-DB-CHECK",
                personal_account="999999",
                amount=1.00,
                service_trx_id="11111111",
                status="test_write",
                processed_at=datetime.now(timezone.utc)
            )
            db.add(test_tx)
            await db.commit()
            print(f"✅ Запись успешна! ID: {test_tx.id}")
            return True
        except Exception as e:
            await db.rollback()
            print(f"❌ Ошибка записи: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    result = asyncio.run(test_write())
    sys.exit(0 if result else 1)