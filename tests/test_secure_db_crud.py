from datetime import datetime

def test_db_crud(db):
    # insert and retrieve one record in each table
    for table in ["customers", "stores", "partners"]:
        db.insert(table, {"foo": "bar", "ts": datetime.utcnow().isoformat()})
        results = db.all(table)
        assert any(r.get("foo") == "bar" for r in results)