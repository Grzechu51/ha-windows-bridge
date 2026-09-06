"""Scoped COM ownership for synchronous Windows provider calls.

Only plain Python values leave a query. COM proxies are released in the calling
apartment before its balanced CoUninitialize; no proxy is cached across threads.
"""
from contextlib import contextmanager
from types import SimpleNamespace

import pythoncom


class ProviderUnavailable(RuntimeError):
    """A provider failed, as distinct from a successful empty enumeration."""


@contextmanager
def com_apartment():
    owned = False
    try:
        try:
            pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
            owned = True
        except pythoncom.com_error as exc:
            # Qt/audio may already own an STA on this thread. Borrow that
            # apartment without changing it or balancing someone else's init.
            if exc.hresult != -2147417850:  # RPC_E_CHANGED_MODE
                raise ProviderUnavailable("COM initialization failed") from exc
        yield
    finally:
        if owned:
            pythoncom.CoUninitialize()


def query_wmi(namespace: str, query: str) -> list[SimpleNamespace]:
    """Materialize explicitly selected scalar fields inside the apartment."""
    import win32com.client

    fields = query.split(" FROM ", 1)[0].removeprefix("SELECT ").split(",")
    with com_apartment():
        service = rows = item = None
        try:
            service = win32com.client.GetObject(namespace)
            rows = service.ExecQuery(query)
            result = []
            for item in rows:
                values = {field: getattr(item, field, None) for field in fields}
                if any(value is not None and not isinstance(value, (str, int, float, bool))
                       for value in values.values()):
                    raise TypeError("WMI returned a non-scalar field")
                result.append(SimpleNamespace(**values))
            return result
        except Exception as exc:
            raise ProviderUnavailable(f"WMI query failed: {query}") from exc
        finally:
            item = rows = service = None
