"""Ошибки бизнес-правил: сервисы бросают их, API превращает в ответ 400/404/409 с текстом на русском."""


class DomainError(Exception):
    status = 400

    def __init__(self, message: str, status: int | None = None, data: dict | None = None):
        super().__init__(message)
        self.message = message
        if status:
            self.status = status
        self.data = data or {}


class NotFound(DomainError):
    status = 404


class Conflict(DomainError):
    status = 409
