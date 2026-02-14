import firebase_admin
from firebase_admin import credentials, firestore

# 1. חיבור ל-Firebase
# וודא שהקובץ JSON נמצא באותה תיקייה עם הקוד
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# 2. פקודה ליצירת המחסן הראשון שלך
def create_first_warehouse():
    doc_ref = db.collection("Warehouses").document("makhsan_1")
    doc_ref.set({
        "name": "מחסן שרוולים ראשי",
        "location": "חצר בזק"
    })
    print("החיבור הצליח! המחסן הראשון נוצר ב-Firebase.")

create_first_warehouse()