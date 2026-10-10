from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar('matchledger_request_id', default=None)


def request_id():
    return request_id_var.get()
