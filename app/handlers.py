# app/handlers.py
ORDERS = {
    "ORDER-123": {"amount": 100.00, "refunded": False},
    "ORDER-456": {"amount": 500.00, "refunded": False},
}

# Кэш для идемпотентности: {RefundRequestId: response_xml}
_idempotency_cache = {}


def process_refund(data: dict) -> dict:
    # 1. Проверяем идемпотентность (повторный запрос с тем же ID)
    req_id = data.get('RefundRequestId')
    if req_id in _idempotency_cache:
        return _idempotency_cache[req_id]

    # 2. Валидация входных данных
    order_id = data.get('OrderId')
    amount_str = data.get('Amount')

    if not order_id or not amount_str:
        result = {"code": 4, "message": "Не указаны обязательные поля"}
        if req_id: _idempotency_cache[req_id] = result
        return result

    try:
        amount = float(amount_str)
    except (ValueError, TypeError):
        result = {"code": 4, "message": "Некорректная сумма возврата"}
        if req_id: _idempotency_cache[req_id] = result
        return result

    if amount <= 0:
        result = {"code": 4, "message": "Сумма возврата должна быть больше нуля"}
        if req_id: _idempotency_cache[req_id] = result
        return result

    # 3. Поиск заказа
    if order_id not in ORDERS:
        result = {"code": 1, "message": "Заказ не найден"}
        if req_id: _idempotency_cache[req_id] = result
        return result

    order = ORDERS[order_id]

    # 4. Проверка: уже возвращён?
    if order["refunded"]:
        result = {"code": 2, "message": "Возврат по этому заказу уже выполнен"}
        if req_id: _idempotency_cache[req_id] = result
        return result

    # 5. Проверка суммы
    if amount > order["amount"]:
        result = {"code": 3, "message": "Сумма возврата превышает сумму заказа"}
        if req_id: _idempotency_cache[req_id] = result
        return result

    # 6. Успех: помечаем заказ как возвращённый
    order["refunded"] = True
    result = {"code": 0, "message": "Возврат успешно обработан"}

    # Сохраняем в кэш идемпотентности
    if req_id:
        _idempotency_cache[req_id] = result

    return result