from tinydb import TinyDB

db = TinyDB("data/plain.json")
db.insert({"foo": "bar"})
print(db.all())
db.close()
