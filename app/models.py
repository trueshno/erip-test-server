# app/models.py
from sqlalchemy import (
    Column, Integer, String, Numeric, Text, DateTime, 
    ForeignKey, Sequence, Index, func
)
from sqlalchemy.orm import declarative_base
from .db_config import Base  # Импортируем Base из твоего db_config.py

# ==========================================
# 1. СЧЕТА ПЛАТЕЛЬЩИКОВ (для ServiceInfo)
# ==========================================
class Account(Base):
    __tablename__ = "accounts"
    
    account_number = Column(String(32), primary_key=True)
    status = Column(String(20), default="active")
    
    # [БД] Данные для ServiceInfo
    debt_amount = Column(Numeric(12, 2), default=0)
    editable_flag = Column(String(1), default="N")  # Y/N
    min_amount = Column(Numeric(12, 2), default=0)
    max_amount = Column(Numeric(12, 2), default=100000)
    
    # [БД] ФИО и Адрес (хранятся полными, маскируются в коде перед ответом)
    holder_surname = Column(String(30))
    holder_firstname = Column(String(30))
    holder_patronymic = Column(String(30))
    city = Column(String(30))
    street = Column(String(30))
    house = Column(String(10))
    building = Column(String(10))
    apartment = Column(String(10))
    
    currency = Column(String(3), default="933")  # [явно] по умолчанию BYN
    service_no = Column(Integer, default=1)      # [явно] код услуги
    created_at = Column(DateTime(timezone=True), server_default=func.systimestamp())

    def __repr__(self):
        return f"<Account(acc='{self.account_number}', debt={self.debt_amount})>"


# ==========================================
# 2. ЖУРНАЛ ТРАНЗАКЦИЙ 
# ==========================================
class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, Sequence('transactions_seq'), primary_key=True)
    erip_request_id = Column(String(64), nullable=False, unique=True, index=True)  # 🔑 Идемпотентность
    request_type = Column(String(20))  # ServiceInfo / TransactionStart / ...
    
    # [БД] Внешние идентификаторы
    erip_transaction_id = Column(String(32), index=True)
    service_trx_id = Column(String(12), unique=True, index=True)  # Твой номер операции
    personal_account = Column(String(32), nullable=False, index=True)
    
    # [БД] Финансы и каналы
    amount = Column(Numeric(12, 2), default=0)
    currency = Column(String(3), default="933")
    terminal_id = Column(String(30))
    terminal_type = Column(Integer)
    agent_code = Column(Integer)
    auth_type = Column(String(10))
    
    status = Column(String(20), default="pending")  # pending/success/failed/storned
    created_at = Column(DateTime(timezone=True), server_default=func.systimestamp())
    processed_at = Column(DateTime(timezone=True))
    
    metadata_json = Column(Text)  

    __table_args__ = (
        Index("idx_erip_req", "erip_request_id"),
        Index("idx_service_trx", "service_trx_id"),
        Index("idx_personal_acc", "personal_account"),
    )

    def __repr__(self):
        return f"<Trx(id={self.id}, req='{self.erip_request_id}', status='{self.status}')>"


# ==========================================
# 3. СТРОКИ ОТВЕТА (InfoLine)
# ==========================================
class TransactionInfoLine(Base):
    __tablename__ = "transaction_info_lines"
    
    id = Column(Integer, Sequence('tx_info_lines_seq'), primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False)
    line_text = Column(String(1000), nullable=False)
    line_order = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.systimestamp())

    __table_args__ = (Index("idx_info_lines_tx", "transaction_id"),)

    def __repr__(self):
        return f"<InfoLine(tx={self.transaction_id}, text='{self.line_text[:30]}...')>"


# ==========================================
# ErrorLine
# ==========================================
class TransactionError(Base):
    __tablename__ = "transaction_errors"
    
    id = Column(Integer, Sequence('tx_errors_seq'), primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id", ondelete="SET NULL"))
    error_stage = Column(String(20), nullable=False)  # ServiceInfo / TransactionStart
    error_code = Column(Integer)
    error_text = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.systimestamp())

    __table_args__ = (Index("idx_errors_tx", "transaction_id"),)

    def __repr__(self):
        return f"<Error(tx={self.transaction_id}, code={self.error_code})>"