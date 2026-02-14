import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import json
import numpy as np
from PIL import Image

# --- הגדרות תצוגה ---
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
if 'last_scan' not in st.session_state:
    st.session_state['last_scan'] = ""

# --- פונקציות עזר ---
def log_action(action, details):
    db.collection("Logs").add({
        "timestamp": datetime.now(),
        "user": st.session_state.get('user_email', 'Guest'),
        "role": st.session_state.get('user_role', 'None'),
        "action": action,
        "details": details
    })

def logout():
    st.session_state['logged_in'] = False
    st.session_state['user_email'] = ""
    st.session_state['user_role'] = ""
    st.session_state['edit_item_id'] = None
    st.session_state['active_action'] = None
    st.session_state['last_scan'] = ""
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

def preprocess_image(image_pil):
    try:
        import cv2
        img = np.array(image_pil)
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        else:
            gray = img
        processed = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        return processed
    except:
        return np.array(image_pil)

# --- לוגיקה לעיבוד וסריקה (משותפת לשני סוגי המצלמות) ---
def process_scan(img_file):
    try:
        import easyocr
        with st.spinner('מפענח טקסט (פיקוס חכם)...'):
            orig_image = Image.open(img_file)
            processed_img = preprocess_image(orig_image)
            reader = easyocr.Reader(['en'])
            result = reader.readtext(processed_img, detail=0)
            if result:
                raw_text = " ".join(result).upper()
                st.session_state['last_scan'] = raw_text
                st.success("הסריקה נקלטה!")
                return True
            else:
                st.warning("לא זוהה טקסט.")
                return False
    except Exception as e:
        st.error(f"שגיאה: {e}")
        return False

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
    st.sidebar.caption(f"תפקיד: {st.session_state['user_role']}")
    
    with st.sidebar.expander("🔐 שינוי סיסמה"):
        new_pass_1 = st.text_input("סיסמה חדשה", type="password", key="np1")
        if st.button("עדכן סיסמה"):
            if len(new_pass_1) > 3:
                db.collection("Users").document(st.session_state['user_email']).update({
                    "password": new_pass_1, "reset_requested": False
                })
                st.success("הסיסמה שונתה!")
                log_action("שינוי סיסמה", "בוצע שינוי עצמי")
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
    # 1. חיפוש חכם (עם שתי אופציות צילום)
    # ==========================================
    if choice_key == "search":
        
        # --- אזור סריקה משודרג ---
        with st.expander("📸 סריקת תגית (בחר שיטה)", expanded=True):
            scan_method = st.radio("בחר שיטת צילום:", ["מצלמה מהירה (בתוך האתר)", "מצלמה איכותית (דרך הטלפון)"], horizontal=True)
            
            img_file = None
            
            # אופציה 1: מצלמה מהירה (סטרים-ליט)
            if scan_method == "מצלמה מהירה (בתוך האתר)":
                img_file = st.camera_input("צלם תגית")
            
            # אופציה 2: מצלמה איכותית (העלאת קובץ)
            else:
                st.info("💡 בנייד: לחץ למטה ואז בחר ב-'Camera'/'מצלמה'. זה יאפשר לך זום ופוקוס!")
                img_file = st.file_uploader("צלם תמונה איכותית", type=['jpg', 'png', 'jpeg'])

            # אם התקבלה תמונה (לא משנה מאיזו שיטה) -> שלח לפענוח
            if img_file:
                 # מנגנון למניעת פענוח כפול של אותה תמונה
                 file_id = f"{img_file.name}-{img_file.size}"
                 if 'processed_file' not in st.session_state or st.session_state['processed_file'] != file_id:
                     if process_scan(img_file):
                         st.session_state['processed_file'] = file_id
                     else:
                         st.session_state['processed_file'] = None

        # --- מנוע החיפוש ---
        default_val = st.session_state['last_scan']
        search_q = st.text_input("🔍 חפש פריט", value=default_val)
        
        inv_stream = list(db.collection("Inventory").stream())
        found_items = []
        
        if search_q:
            search_tokens = search_q.upper().replace("(", " ").replace(")", " ").split()
            search_tokens = [t for t in search_tokens if len(t) > 2]

            for doc in inv_stream:
                d = doc.to_dict()
                item_name_upper = str(d.get('item_name', '')).upper()
                is_match = False
                
                if search_q.upper() in item_name_upper:
                    is_match = True
                
                if not is_match:
                    db_item_tokens = item_name_upper.replace("(", " ").replace(")", " ").split()
                    for db_token in db_item_tokens:
                        if len(db_token) > 3:
                            for scan_token in search_tokens:
                                if db_token in scan_token: 
                                    is_match = True
                                    break
                
                if is_match:
                    found_items.append(doc)
        
        if found_items:
            st.success(f"נמצאו {len(found_items)} פריטים!")
            for doc in found_items:
                d = doc.to_dict()
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    c1.markdown(f"**{d['item_name']}**")
                    c1.caption(f"📍 {d['warehouse']} | כמות: **{d['quantity']}**")
                    if c2.button("📤 משוך", key=f"p_{doc.id}"):
                        st.session_state['active_action'] = {'type': 'pull', 'id': doc.id, 'name': d['item_name']}
                        st.rerun()
                    if st.session_state['user_role'] == "מנהל מלאי":
                        if c2.button("🚚 הזז", key=f"m_{doc.id}"):
                            st.session_state['active_action'] = {'type': 'move', 'id': doc.id, 'name': d['item_name']}
                            st.rerun()
        elif search_q:
            st.warning("לא נמצאו תוצאות.")

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
                            "quantity": qty, "reason": reason, "status": "pending", "timestamp": datetime.now()
                        })
                        log_action("בקשת משיכה", f"{qty} יח' של {action['name']}")
                        st.success("הבקשה נשלחה!")
                        st.session_state['active_action'] = None
                        st.rerun()

            elif action['type'] == 'move':
                with st.form("act_move"):
                    whs_list = [w.to_dict()['name'] for w in db.collection("Warehouses").stream()]
                    new_wh = st.selectbox("לאן להעביר?", whs_list)
                    c1, c2, c3 = st.columns(3)
                    nr, nc, nf = c1.text_input("שורה"), c2.text_input("עמ'"), c3.text_input("קומה")
                    if st.form_submit_button("בצע העברה"):
                        db.collection("Inventory").document(action['id']).update({
                            "warehouse": new_wh, "row": nr, "column": nc, "floor": nf
                        })
                        log_action("העברת פריט", f"{action['name']} -> {new_wh}")
                        st.success("הפריט הועבר!")
                        st.session_state['active_action'] = None
                        st.rerun()
            
            if st.button("ביטול פעולה"):
                st.session_state['active_action'] = None
                st.rerun()

    # (שאר החלקים נשארים אותו דבר כמו בגרסאות הקודמות - approve, stock_in, pull וכו')
    # למען הקיצור לא העתקתי את כולם שוב, אבל חשוב להשאיר אותם בקובץ המלא שלך!
    # ==========================================
    # המשך הקוד זהה לגרסה 11 (משיכה, קליטה, ניהול פריטים...)
    # ==========================================
    elif choice_key == "approve":
         # ... (אותו קוד כמו מקודם) ...
         reqs = db.collection("Requests").where("status", "==", "pending").stream()
         found = False
         for req in reqs:
             found = True
             r = req.to_dict()
             with st.container(border=True):
                 st.write(f"**{r['user_email']}**: {r['quantity']} X {r['item_name']}")
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
        # ... (אותו קוד) ...
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
        # ... (אותו קוד) ...
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
        # ... (אותו קוד) ...
        with st.form("nwh"):
            if st.form_submit_button("הוסף מחסן"):
                db.collection("Warehouses").add({"name": st.text_input("שם")})
                st.rerun()
        for w in db.collection("Warehouses").stream():
            c1, c2 = st.columns([4,1])
            c1.info(w.to_dict()['name'])
            if c2.button("🗑️", key=w.id): db.collection("Warehouses").document(w.id).delete(); st.rerun()

    elif choice_key == "items":
        # ... (אותו קוד) ...
        with st.expander("הוסף פריט"):
            d, r, y = st.text_input("תיאור"), st.text_input("מק\"ט רשות"), st.text_input("יצרן")
            if st.button("שמור"): db.collection("Items").add({"description": d, "internal_sku": r, "manufacturer_sku": y}); st.rerun()
        for i in db.collection("Items").stream():
            st.write(f"🔹 {i.to_dict()['description']}")
            if st.button("מחק", key=i.id): db.collection("Items").document(i.id).delete(); st.rerun()

    elif choice_key == "users":
        # ... (אותו קוד) ...
        for u in db.collection("Users").stream():
            d = u.to_dict()
            with st.expander(f"{d['email']} ({'ממתין' if not d.get('approved') else 'פעיל'})"):
                if not d.get('approved'): 
                    if st.button("אשר", key=f"a_{u.id}"): db.collection("Users").document(u.id).update({"approved": True}); st.rerun()
                if d.get('reset_requested'):
                    if st.button("אפס", key=f"r_{u.id}"): db.collection("Users").document(u.id).update({"password": "123456", "reset_requested": False}); st.rerun()

    elif choice_key == "logs":
        # ... (אותו קוד) ...
        st.dataframe([l.to_dict() for l in db.collection("Logs").order_by("timestamp", direction="DESCENDING").limit(20).stream()])