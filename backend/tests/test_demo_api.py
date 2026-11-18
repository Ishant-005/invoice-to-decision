from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.models import PurchaseOrder
from app.seed import seed_database


def test_reset_endpoint_restores_seed_state(session):
    seed_database(session)
    session.get(PurchaseOrder, "PO-2260").billed_to_date = Decimal(300000)
    session.commit()

    app.dependency_overrides[get_session] = lambda: session
    try:
        response = TestClient(app).post("/api/demo/reset")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "reset", "vendors": 5, "purchase_orders": 10,
                               "seeded_invoices": 2}
    session.expire_all()
    assert session.get(PurchaseOrder, "PO-2260").billed_to_date == Decimal(100000)
