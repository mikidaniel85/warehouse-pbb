import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import json

# הגדרות תצוגה
st.set_page_config(page_title="ניהול מלאי שרוולים", layout="centered")

# --- 1. התחברות ל-Firebase ---
if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            key_dict = dict(st.secrets["firebase"])
            if "private_key" in key_dict:
                key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
        else:
            cred = credentials.Certificate("serviceAccountKey.json")
            firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"❌ שגיאה בהתחברות ל-Firebase: {e}")
        st.stop()

db = firestore.client()

# --- זיכרון משתמש ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'user_email' not in st.session_state:
    st.session_state['user_email'] = ""
if 'user_role' not in st.session_state:
    st.session_state['user_role'] = ""
if 'edit_item_id' not in st.session_state:
    st.session_state['edit_item_id'] = None
if 'active_action' not in st.session_state:
    st.session_state['active_action'] = None

# --- פונקציית לוגים ---
def log_action(action, details):
    db.collection("Logs").add({
        "timestamp": datetime.now(),
        "user": st.session_state.get('user_email', 'Guest'),
        "role": st.session_state.get('user_role', 'None'),
        "action": action,
        "details": details
    })

# --- פונקציות עזר ---
def logout():
    st.session_state['logged_in'] = False
    st.session_state['user_email'] = ""
    st.session_state['user_role'] = ""
    st.session_state['edit_item_id'] = None
    st.session_state['active_action'] = None
    st.rerun()

def get_counts():
    try:
        reqs = len(list(db.collection("Requests").where("status", "==", "pending").stream()))
        users_pending = 0
        all_users = db.collection("Users").stream()
        for u in all_users:
            ud = u.to_dict()
            if not ud.get('approved', False) or ud.get('reset_requested', False):
                users_pending += 1
        return reqs, users_pending
    except:
        return 0, 0

# --- מסך כניסה ---
if not st.session_state['logged_in']:
    st.title("📦 מערכת מלאי גשרי עליה")
    tab1, tab2, tab3 = st.tabs(["כניסה", "הרשמה", "שכחתי סיסמה"])
    
    with tab1:
        email = st.text_input("אימייל", key="login_email")
        pw = st.text_input("סיסמה", type="password", key="login_pw")
        if st.button("התחבר", use_container_width=True):
            user_doc = db.collection("Users").document(email).get()
            if user_doc.exists:
                u_data = user_doc.to_dict()
                if u_data.get('password') == pw and u_data.get('approved', False):
                    st.session_state['logged_in'] = True
                    st.session_state['user_email'] = email
                    st.session_state['user_role'] = u_data.get('role', 'יוזר מושך')
                    log_action("התחברות", "כניסה למערכת")
                    st.rerun()
                elif not u_data.get('approved', False):
                    st.error("ממתין לאישור מנהל.")
                else:
                    st.error("סיסמה שגויה.")
            else:
                st.error("משתמש לא נמצא.")
    
    with tab2:
        reg_email = st.text_input("אימייל חדש")
        reg_pw = st.text_input("סיסמה חדשה", type="password")
        role = st.radio("תפקיד", ["יוזר מושך", "מנהל מלאי"])
        if st.button("הירשם"):
            db.collection("Users").document(reg_email).set({"email": reg_email, "password": reg_pw, "role": role, "approved": False})
            st.warning("נשלח לאישור.")

    with tab3:
        reset_email = st.text_input("אימייל לשחזור")
        if st.button("שלח בקשת איפוס"):
            doc_ref = db.collection("Users").document(reset_email)
            if doc_ref.get().exists:
                doc_ref.update({"reset_requested": True})
                st.success("הבקשה נשלחה למנהל.")
            else:
                st.error("המייל לא קיים.")

# --- אפליקציה ראשית ---
else:
    req_c, usr_c = get_counts()
    req_alert = f"🔴 ({req_c})" if req_c > 0 else ""
    usr_alert = f"🔴 ({usr_c})" if usr_c > 0 else ""
    
    st.sidebar.write(f"מחובר: **{st.session_state['user_email']}**")
    
    with st.sidebar.expander("🔐 שינוי סיסמה"):
        new_pass_1 = st.text_input("סיסמה חדשה", type="password", key="np1")
        if st.button("עדכן סיסמה"):
            if len(new_pass_1) > 3:
                db.collection("Users").document(st.session_state['user_email']).update({
                    "password": new_pass_1, "reset_requested": False
                })
                st.success("הסיסמה שונתה!")
            else:
                st.error("סיסמה קצרה מדי")

    if st.sidebar.button("התנתק"): logout()

    # תפריט
    if st.session_state['user_role'] == "מנהל מלאי":
        menu = {
            "search": "חיפוש ופעולות",
            "stock_in": "קליטת מלאי (קבלה)",
            "pull": "משיכת מלאי (יציאה)",
            "approve": f"אישור משיכות {req_alert}",
            "items": "ניהול פריטים (קטלוג)",
            "warehouses": "ניהול מחסנים",
            "users": f"ניהול משתמשים {usr_alert}",
            "logs": "יומן פעילות"
        }
    else:
        menu = {"search": "חיפוש ופעולות", "pull": "משיכת מלאי"}
    
    choice_key = st.sidebar.radio("תפריט", list(menu.keys()), format_func=lambda x: menu[x])
    st.title(f"📦 {menu[choice_key]}")

    # ==========================================
    # 1. חיפוש ופעולות (עם מצלמה!)
    # ==========================================
    if choice_key == "search":
        # --- אזור סריקה (מוסתר כברירת מחדל) ---
        scanned_text = ""
        with st.expander("📸 סריקת ברקוד/תגית (בטא)"):
            img_file = st.camera_input("צלם את התגית")
            if img_file:
                try:
                    # ייבוא EasyOCR רק כשצריך (כדי לא להקריס את המחשב המקומי אם אין דרייבר)
                    import easyocr
                    import numpy as np
                    from PIL import Image
                    
                    with st.spinner('מפענח טקסט...'):
                        image = Image.open(img_file)
                        reader = easyocr.Reader(['en']) # זיהוי אנגלית/מספרים
                        result = reader.readtext(np.array(image), detail=0)
                        if result:
                            scanned_text = " ".join(result)
                            st.success(f"זוהה: {scanned_text}")
                        else:
                            st.warning("לא זוהה טקסט ברור")
                except Exception as e:
                    st.error("רכיב הסריקה לא נתמך במכשיר זה (עובד בנייד/ענן).")

        # --- אזור החיפוש ---
        # אם הסריקה הצליחה, היא נכנסת אוטומטית לתיבת החיפוש
        default_search = scanned_text if scanned_text else ""
        search_q = st.text_input("🔍 חפש פריט (טקסט או סריקה)", value=default_search)
        
        # --- אזור פעולות אקטיביות ---
        if st.session_state['active_action']:
            action = st.session_state['active_action']
            st.divider()
            st.info(f"מבצע פעולה על: **{action['name']}**")
            
            if action['type'] == 'pull':
                with st.form("act_pull"):
                    qty = st.number_input("כמות למשיכה", min_value=1, value=1)
                    reason = st.text_input("סיבה / שרוול")
                    if st.form_submit_button("שלח בקשה"):
                        db.collection("Requests").add({
                            "user_email": st.session_state['user_email'],
                            "item_name": action['name'], "location_id": action['id'],
                            "quantity": qty, "reason": reason,
                            "status": "pending", "timestamp": datetime.now()
                        })
                        log_action("בקשת משיכה", f"{qty} יח' של {action['name']}")
                        st.success("נשלח!")
                        st.session_state['active_action'] = None
                        st.rerun()

            elif action['type'] == 'move':
                with st.form("act_move"):
                    whs_list = [w.to_dict()['name'] for w in db.collection("Warehouses").stream()]
                    new_wh = st.selectbox("לאן?", whs_list)
                    c1, c2, c3 = st.columns(3)
                    nr, nc, nf = c1.text_input("שורה"), c2.text_input("עמ'"), c3.text_input("קומה")
                    if st.form_submit_button("העבר"):
                        db.collection("Inventory").document(action['id']).update({
                            "warehouse": new_wh, "row": nr, "column": nc, "floor": nf
                        })
                        log_action("העברה", f"{action['name']} -> {new_wh}")
                        st.success("הועבר!")
                        st.session_state['active_action'] = None
                        st.rerun()
            
            if st.button("ביטול"):
                st.session_state['active_action'] = None
                st.rerun()

        # --- תוצאות חיפוש ---
        inv_stream = db.collection("Inventory").stream()
        found_any = False
        for doc in inv_stream:
            d = doc.to_dict()
            # חיפוש חכם: בודק אם הטקסט קיים בשם, ב-ID או בטקסט שנסרק
            if search_q and (search_q.lower() not in d['item_name'].lower() and search_q not in str(d.get('item_id', ''))):
                continue
            
            found_any = True
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                c1.markdown(f"**{d['item_name']}**")
                c1.caption(f"📍 {d['warehouse']} | שורה: {d.get('row')} | כמות: {d['quantity']}")
                
                if c2.button("📤", key=f"p_{doc.id}", help="משוך"):
                    st.session_state['active_action'] = {'type': 'pull', 'id': doc.id, 'name': d['item_name']}
                    st.rerun()
                
                if st.session_state['user_role'] == "מנהל מלאי":
                    if c2.button("🚚", key=f"m_{doc.id}", help="הזז"):
                        st.session_state['active_action'] = {'type': 'move', 'id': doc.id, 'name': d['item_name']}
                        st.rerun()

        if not found_any and search_q:
            st.warning("לא נמצאו תוצאות.")

    # ==========================================
    # שאר החלקים נשארו ללא שינוי (רק הוסתרו כדי לקצר, אבל הם בקוד המלא)
    # ==========================================
    elif choice_key == "approve":
        reqs = db.collection("Requests").where("status", "==", "pending").stream()
        found = False
        for req in reqs:
            found = True
            r = req.to_dict()
            with st.container(border=True):
                st.write(f"**{r['user_email']}**: {r['quantity']} X {r['item_name']} ({r['reason']})")
                c1, c2 = st.columns(2)
                if c1.button("✅", key=f"ok_{req.id}"):
                    inv_ref = db.collection("Inventory").document(r['location_id'])
                    s = inv_ref.get()
                    if s.exists:
                        inv_ref.update({"quantity": max(0, s.to_dict()['quantity'] - r['quantity'])})
                        db.collection("Requests").document(req.id).update({"status": "approved"})
                        st.rerun()
                if c2.button("❌", key=f"rj_{req.id}"):
                    db.collection("Requests").document(req.id).update({"status": "rejected"})
                    st.rerun()
        if not found: st.info("אין בקשות.")

    elif choice_key == "stock_in":
        # קוד קליטת מלאי (זהה לגרסה 10)
        items = {i.to_dict()['description']: i.id for i in db.collection("Items").stream()}
        whs = [w.to_dict()['name'] for w in db.collection("Warehouses").stream()]
        if items and whs:
            si = st.selectbox("פריט", list(items.keys()))
            with st.form("sin"):
                wh = st.selectbox("מחסן", whs)
                c1, c2, c3 = st.columns(3)
                r, c, f = c1.text_input("שורה"), c2.text_input("עמ'"), c3.text_input("קומה")
                q = st.number_input("כמות", 1)
                if st.form_submit_button("קלוט"):
                    loc = f"{wh}_{r}_{c}_{f}_{items[si]}"
                    ref = db.collection("Inventory").document(loc)
                    if ref.get().exists: ref.update({"quantity": ref.get().to_dict()['quantity'] + q})
                    else: ref.set({"item_name": si, "warehouse": wh, "row": r, "column": c, "floor": f, "quantity": q, "item_id": items[si]})
                    log_action("קליטה", f"{q} {si}")
                    st.success("נקלט!")

    elif choice_key == "pull":
        # קוד משיכה (זהה לגרסה 10)
        inv = db.collection("Inventory").where("quantity", ">", 0).stream()
        opts = {f"{d.to_dict()['item_name']} ({d.to_dict()['warehouse']})": d.id for d in inv}
        if opts:
            k = st.selectbox("פריט", list(opts.keys()))
            with st.form("pf"):
                q = st.number_input("כמות", 1)
                rs = st.text_input("סיבה")
                if st.form_submit_button("שלח"):
                    db.collection("Requests").add({"user_email": st.session_state['user_email'], "item_name": k.split('(')[0], "location_id": opts[k], "quantity": q, "reason": rs, "status": "pending", "timestamp": datetime.now()})
                    st.success("נשלח!")

    elif choice_key == "warehouses":
        # קוד מחסנים (זהה לגרסה 10)
        with st.form("nwh"):
            if st.form_submit_button("הוסף מחסן"):
                db.collection("Warehouses").add({"name": st.text_input("שם")})
                st.rerun()
        for w in db.collection("Warehouses").stream():
            c1, c2 = st.columns([4,1])
            c1.info(w.to_dict()['name'])
            if c2.button("🗑️", key=w.id): db.collection("Warehouses").document(w.id).delete(); st.rerun()

    elif choice_key == "items":
        # קוד פריטים (זהה לגרסה 10)
        with st.expander("הוסף פריט"):
            d, r, y = st.text_input("תיאור"), st.text_input("מק\"ט רשות"), st.text_input("יצרן")
            if st.button("שמור"): db.collection("Items").add({"description": d, "internal_sku": r, "manufacturer_sku": y}); st.rerun()
        for i in db.collection("Items").stream():
            st.write(f"🔹 {i.to_dict()['description']}")
            if st.button("מחק", key=i.id): db.collection("Items").document(i.id).delete(); st.rerun()

    elif choice_key == "users":
        # קוד משתמשים (זהה לגרסה 10)
        st.write("ניהול משתמשים")
        for u in db.collection("Users").stream():
            d = u.to_dict()
            with st.expander(f"{d['email']} ({'ממתין' if not d.get('approved') else 'פעיל'})"):
                if not d.get('approved'): 
                    if st.button("אשר", key=f"a_{u.id}"): db.collection("Users").document(u.id).update({"approved": True}); st.rerun()
                if d.get('reset_requested'):
                    st.warning("ביקש איפוס!")
                    if st.button("אפס ל-123456", key=f"r_{u.id}"): db.collection("Users").document(u.id).update({"password": "123456", "reset_requested": False}); st.rerun()

    elif choice_key == "logs":
        # קוד לוגים (זהה לגרסה 10)
        st.dataframe([l.to_dict() for l in db.collection("Logs").order_by("timestamp", direction="DESCENDING").limit(20).stream()])