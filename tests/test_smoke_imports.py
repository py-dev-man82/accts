import pytest

HANDLER_MODULES = [
    "handlers.customers",
    "handlers.stores",
    "handlers.partners",
    "handlers.sales",
    "handlers.payments",
    "handlers.payouts",
    "handlers.stockin",
    "handlers.reports",
    "handlers.export_excel",
    "handlers.export_pdf",
]

@pytest.mark.parametrize("module", HANDLER_MODULES)
def test_import_module(module):
    __import__(module)