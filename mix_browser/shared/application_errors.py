from __future__ import annotations


# @arch mix-browser.application-error utility | en: Carries stable application error codes across adapters | zh: 在不同适配器间传递稳定的应用错误代码
class ApplicationApiError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
