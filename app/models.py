# app/models.py
"""
Модели данных для сервиса ЕРИП.

Определяет структуры таблиц базы данных:
- Account: счета плательщиков
- Transaction: журнал транзакций
- TransactionInfoLine: строки информации о транзакции
- TransactionError: ошибки транзакций
"""
from sqlalchemy import (
    Column, Integer, String, Numeric, Text, DateTime, 
    ForeignKey, Sequence, Index, func
)
from sqlalchemy.orm import declarative_base
from .db_config import Base  # Импортируем Base из db_config.py


# ==========================================
# 1. СЧЕТА ПЛАТЕЛЬЩИКОВ (для ServiceInfo)
# ==========================================
class Account(Base):
    """
    Модель счёта плательщика.
    
    Хранит информацию о лицевых счетах абонентов,
    включая данные для отображения в ServiceInfo.
    """
    __tablename__ = "accounts"
    
    account_number = Column(String(32), primary_key=True, comment="Лицевой счёт")
    status = Column(String(20), default="active", comment="Статус счёта (active/blocked)")
    
    # Финансовые данные
    debt_amount = Column(Numeric(12, 2), default=0, comment="Сумма задолженности")
    editable_flag = Column(String(1), default="N", comment="Флаг редактирования суммы (Y/N)")
    min_amount = Column(Numeric(12, 2), default=0, comment="Минимальная сумма платежа")
    max_amount = Column(Numeric(12, 2), default=100000, comment="Максимальная сумма платежа")
    
    # Данные абонента (маскируются перед отправкой)
    holder_surname = Column(String(30), comment="Фамилия владельца")
    holder_firstname = Column(String(30), comment="Имя владельца")
    holder_patronymic = Column(String(30), comment="Отчество владельца")
    city = Column(String(30), comment="Город")
    street = Column(String(30), comment="Улица")
    house = Column(String(10), comment="Дом")
    building = Column(String(10), comment="Корпус/строение")
    apartment = Column(String(10), comment="Квартира/офис")
    
    currency = Column(String(3), default="933", comment="Код валюты (BYN=933)")
    service_no = Column(Integer, default=1, comment="Код услуги")
    created_at = Column(DateTime(timezone=True), server_default=func.systimestamp(), comment="Дата создания")

    def __repr__(self):
        return f"<Account(acc='{self.account_number}', debt={self.debt_amount})>"


# ==========================================
# 2. ЖУРНАЛ ТРАНЗАКЦИЙ 
# ==========================================
class Transaction(Base):
    """
    Модель транзакции ЕРИП.
    
    Журналирует все входящие запросы от ЕРИП
    для обеспечения идемпотентности и аудита.
    """
    __tablename__ = "transactions"
    
    id = Column(Integer, Sequence('transactions_seq'), primary_key=True, comment="Внутренний ID")
    erip_request_id = Column(String(64), nullable=False, unique=True, index=True, comment="ID запроса ЕРИП (идемпотентность)")
    request_type = Column(String(20), comment="Тип запроса (ServiceInfo/TransactionStart)")
    
    # Внешние идентификаторы
    erip_transaction_id = Column(String(32), index=True, comment="ID транзакции от ЕРИП")
    service_trx_id = Column(String(12), unique=True, index=True, comment="Внутренний номер операции")
    personal_account = Column(String(32), nullable=False, index=True, comment="Лицевой счёт")
    
    # Финансы и каналы
    amount = Column(Numeric(12, 2), default=0, comment="Сумма операции")
    currency = Column(String(3), default="933", comment="Код валюты")
    terminal_id = Column(String(30), comment="ID терминала")
    terminal_type = Column(Integer, comment="Тип терминала")
    agent_code = Column(Integer, comment="Код агента")
    auth_type = Column(String(10), comment="Тип авторизации")
    
    status = Column(String(20), default="pending", comment="Статус (pending/success/failed/storned)")
    created_at = Column(DateTime(timezone=True), server_default=func.systimestamp(), comment="Время создания")
    processed_at = Column(DateTime(timezone=True), comment="Время обработки")
    
    metadata_json = Column(Text, comment="JSON/XML ответ")

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
    """
    Строка информационного сообщения транзакции.
    
    Дополнительные текстовые сообщения,
    возвращаемые в ответе ЕРИП.
    """
    __tablename__ = "transaction_info_lines"
    
    id = Column(Integer, Sequence('tx_info_lines_seq'), primary_key=True, comment="ID строки")
    transaction_id = Column(Integer, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, comment="ID транзакции")
    line_text = Column(String(1000), nullable=False, comment="Текст сообщения")
    line_order = Column(Integer, default=1, comment="Порядок отображения")
    created_at = Column(DateTime(timezone=True), server_default=func.systimestamp(), comment="Время создания")

    __table_args__ = (Index("idx_info_lines_tx", "transaction_id"),)

    def __repr__(self):
        return f"<InfoLine(tx={self.transaction_id}, text='{self.line_text[:30]}...')>"


# ==========================================
# ОШИБКИ ТРАНЗАКЦИЙ
# ==========================================
class TransactionError(Base):
    """
    Модель ошибок транзакций.
    
    Журналирует ошибки, возникшие при обработке
    запросов ЕРИП.
    """
    __tablename__ = "transaction_errors"
    
    id = Column(Integer, Sequence('tx_errors_seq'), primary_key=True, comment="ID записи")
    transaction_id = Column(Integer, ForeignKey("transactions.id", ondelete="SET NULL"), comment="ID транзакции")
    error_stage = Column(String(20), nullable=False, comment="Этап ошибки (ServiceInfo/TransactionStart)")
    error_code = Column(Integer, comment="Код ошибки")
    error_text = Column(Text, comment="Текст ошибки")
    created_at = Column(DateTime(timezone=True), server_default=func.systimestamp(), comment="Время создания")

    __table_args__ = (Index("idx_errors_tx", "transaction_id"),)

    def __repr__(self):
        return f"<Error(tx={self.transaction_id}, code={self.error_code})>"