import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import json
import numpy as np
from PIL import Image

# --- הגדרות תצוגה ---
st.set_page_config(page_title="ניהול מלאי שרוולים", layout="centered")

# --- 1. התחברות ל-Firebase (מנגנון יציב) ---
if not firebase_admin._apps:
    try:
        # בדיקה אם אנחנו בענן (Streamlit Cloud)
        if "firebase" in st.secrets:
            key_dict = dict(st.secrets["firebase"])
            # תיקון ירידות שורה במפתח הפרטי
            if "private_key" in key_dict:
                key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
        # בדיקה אם אנחנו במחשב מקומי
        else:
            cred = credentials.Certificate("serviceAccountKey.json")
            firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"❌ שגיאה בהתחברות ל-Firebase: {e}")
        st.stop()

db = firestore.client()

# --- זיכרון משתמש (Session State) ---
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
# משתנה לשמירת תוצאת הסריקה האחרונה
if 'last_scan' not in st.session_state:
    st.session_state['last_scan'] = ""

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

# --- פונקציה לשיפור תמונה (Image Preprocessing) ---
def preprocess_image(image_pil):
    try:
        import cv2
        # המרה מ-PIL ל-NumPy (ש-CV2 מבין)
        img = np.array(image_pil)
        
        # המרה לשחור לבן
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        else:
            gray = img
            
        # שיפור ניגודיות חכם (Adaptive Threshold) - מעולה למדבקות מבריקות
        # הופך הכל לשחור מוחלט או לבן מוחלט
        processed = cv2.adaptiveThreshold(
            gray, 255, 
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, 11, 2
        )
        return processed
    except Exception as e:
        st.warning(f"עיבוד תמונה נכשל, משתמש בתמונה המקורית: {e}")
        return np.array(image_pil)

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

    # תפריט לפי הרשאות
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
    # 1. חיפוש חכם (הלב של המערכת)
    # ==========================================
    if choice_key == "search":
        
        # --- אזור סריקה ---
        with st.expander("📸 סריקת ברקוד/תגית (בטא)", expanded=True):
            img_file = st.camera_input("צלם את התגית (מומלץ ממרחק 15 ס\"מ)")
            
            if img_file:
                try:
                    # ייבוא כאן כדי לא להכביד אם לא משתמשים
                    import easyocr
                    
                    with st.spinner('מפענח טקסט ומשפר תמונה...'):
                        # 1. פתיחת תמונה ושיפור (Preprocessing)
                        orig_image = Image.open(img_file)
                        processed_img = preprocess_image(orig_image)
                        
                        # 2. קריאת טקסט
                        reader = easyocr.Reader(['en']) # קורא אנגלית ומספרים
                        result = reader.readtext(processed_img, detail=0)
                        
                        if result:
                            # ניקוי הטקסט לפורמט אחיד
                            raw_text = " ".join(result).upper()
                            # שמירה בזיכרון
                            st.session_state['last_scan'] = raw_text
                            st.success("הסריקה נקלטה! בודק התאמות...")
                        else:
                            st.warning("לא זוהה טקסט. נסה לקרב או לנקות את העדשה.")

                except Exception as e:
                    st.error(f"שגיאה ברכיב הסריקה: {e}")

        # --- מנוע החיפוש ---
        # תיבת החיפוש מקבלת אוטומטית את הטקסט שנסרק (או מה שהמשתמש הקליד קודם)
        default_val = st.session_state['last_scan']
        search_q = st.text_input("🔍 חפש פריט (טקסט חופשי או סריקה)", value=default_val)
        
        # שליפת מלאי
        inv_stream = list(db.collection("Inventory").stream())
        found_items = []
        
        if search_q:
            # פירוק החיפוש למילים (Tokens) כדי להתגבר על רעש
            search_tokens = search_q.upper().replace("(", " ").replace(")", " ").split()
            # סינון מילים קצרות מדי (פחות מ-2 אותיות זה רעש)
            search_tokens = [t for t in search_tokens if len(t) > 2]

            for doc in inv_stream:
                d = doc.to_dict()
                item_name_upper = str(d.get('item_name', '')).upper()
                item_id_upper = str(d.get('item_id', '')).upper()
                
                is_match = False
                
                # בדיקה 1: חיפוש רגיל (טקסט בתוך שם)
                if search_q.upper() in item_name_upper:
                    is_match = True
                
                # בדיקה 2: חיפוש הפוך חכם (האם המק"ט מהמלאי מסתתר בתוך הסריקה?)
                # דוגמה: במלאי יש "R530", בסריקה יצא "BLAH_R530_BLAH". זה ימצא את זה!
                if not is_match:
                    # מפרקים גם את שם הפריט במלאי למילים
                    db_item_tokens = item_name_upper.replace("(", " ").replace(")", " ").split()
                    for db_token in db_item_tokens:
                        # אם מילה משמעותית מהמלאי (כמו מק"ט) נמצאת בתוך הסריקה
                        if len(db_token) > 3: # רק למילים ארוכות
                            for scan_token in search_tokens:
                                if db_token in scan_token: 
                                    is_match = True
                                    break
                
                if is_match:
                    found_items.append(doc)
        
        # --- הצגת תוצאות ---
        if found_items:
            st.success(f"נמצאו {len(found_items)} פריטים!")
            for doc in found_items:
                d = doc.to_dict()
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    c1.markdown(f"**{d['item_name']}**")
                    c1.caption(f"📍 {d['warehouse']} | שורה: {d.get('row')} | כמות: **{d['quantity']}**")
                    
                    if c2.button("📤 משוך", key=f"p_{doc.id}"):
                        st.session_state['active_action'] = {'type': 'pull', 'id': doc.id, 'name': d['item_name']}
                        st.rerun()
                    
                    if st.session_state['user_role'] == "מנהל מלאי":
                        if c2.button("🚚 הזז", key=f"m_{doc.id}"):
                            st.session_state['active_action'] = {'type': 'move', 'id': doc.id, 'name': d['item_name']}
                            st.rerun()
        elif search_q:
            st.warning("לא נמצאו תוצאות. נסה לחפש ידנית חלק מהמק\"ט.")

        # --- אזור פעולות אקטיביות (משיכה/הזזה) ---
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

    # ==========================================
    # 2. אישור משיכות (מנהל בלבד)
    # ==========================================
    elif choice_key == "approve":
        reqs = db.collection("Requests").where("status", "==", "pending").stream()
        found = False
        for req in reqs:
            found = True
            r = req.to_dict()
            with st.container(border=True):
                st.markdown(f"**{r['user_email']}** מבקש **{r['quantity']}** מתוך **{r['item_name']}**")
                st.caption(f"סיבה: {r['reason']}")
                col_ok, col_rej = st.columns(2)
                if col_ok.button("✅ אשר", key=f"ok_{req.id}", use_container_width=True):
                    inv_ref = db.collection("Inventory").document(r['location_id'])
                    snap = inv_ref.get()
                    if snap.exists:
                        curr = snap.to_dict()['quantity']
                        inv_ref.update({"quantity": max(0, curr - r['quantity'])})
                        db.collection("Requests").document(req.id).update({"status": "approved"})
                        log_action("אישור משיכה", f"אושר ל-{r['user_email']} ({r['item_name']})")
                        st.rerun()
                    else:
                        st.error("פריט לא נמצא")
                if col_rej.button("❌ דחה", key=f"rj_{req.id}", use_container_width=True):
                    db.collection("Requests").document(req.id).update({"status": "rejected"})
                    log_action("דחיית משיכה", f"נדחה ל-{r['user_email']}")
                    st.rerun()
        if not found: st.info("אין בקשות ממתינות.")

    # ==========================================
    # 3. קליטת מלאי (מנהל בלבד)
    # ==========================================
    elif choice_key == "stock_in":
        items_map = {i.to_dict()['description']: i.id for i in db.collection("Items").stream()}
        whs_list = [w.to_dict()['name'] for w in db.collection("Warehouses").stream()]
        
        if items_map and whs_list:
            sel_item = st.selectbox("בחר פריט (הקלד לחיפוש)", list(items_map.keys()))
            exist = list(db.collection("Inventory").where("item_name", "==", sel_item).limit(1).stream())
            def_w_idx, def_r, def_c, def_f = 0, "", "", ""
            if exist:
                d = exist[0].to_dict()
                if d['warehouse'] in whs_list:
                    def_w_idx = whs_list.index(d['warehouse'])
                def_r, def_c, def_f = d.get('row', ''), d.get('column', ''), d.get('floor', '')
                st.info(f"💡 מיקום קיים: {d['warehouse']} (שורה {def_r})")

            with st.form("in_form"):
                sel_wh = st.selectbox("מחסן", whs_list, index=def_w_idx)
                c1, c2, c3 = st.columns(3)
                r, c, f = c1.text_input("שורה", value=def_r), c2.text_input("עמ'", value=def_c), c3.text_input("קומה", value=def_f)
                qty = st.number_input("כמות", min_value=1)
                
                if st.form_submit_button("קלוט מלאי"):
                    item_id = items_map[sel_item]
                    loc_id = f"{sel_wh}_{r}_{c}_{f}_{item_id}"
                    ref = db.collection("Inventory").document(loc_id)
                    snap = ref.get()
                    if snap.exists:
                        ref.update({"quantity": snap.to_dict()['quantity'] + qty})
                    else:
                        ref.set({
                            "item_name": sel_item, "warehouse": sel_wh, "row": r, "column": c, "floor": f,
                            "quantity": qty, "item_id": item_id
                        })
                    log_action("קליטת מלאי", f"{qty} יח' של {sel_item}")
                    st.success("נקלט בהצלחה!")

    # ==========================================
    # 4. משיכת מלאי (ידנית)
    # ==========================================
    elif choice_key == "pull":
        inv = db.collection("Inventory").where("quantity", ">", 0).stream()
        opts = {f"{d.to_dict()['item_name']} | {d.to_dict()['warehouse']}": d.id for d in inv}
        if opts:
            sel_key = st.selectbox("חפש פריט", list(opts.keys()))
            with st.form("pull_f"):
                q = st.number_input("כמות", min_value=1)
                reason = st.text_input("סיבה")
                if st.form_submit_button("שלח לאישור"):
                    clean_name = sel_key.split("|")[0].strip()
                    db.collection("Requests").add({
                        "user_email": st.session_state['user_email'],
                        "item_name": clean_name, "location_id": opts[sel_key],
                        "quantity": q, "reason": reason, "status": "pending", "timestamp": datetime.now()
                    })
                    log_action("בקשת משיכה", f"{q} של {clean_name}")
                    st.success("נשלח!")
        else:
            st.warning("המחסן ריק.")

    # ==========================================
    # 5. ניהול מחסנים
    # ==========================================
    elif choice_key == "warehouses":
        with st.form("new_wh"):
            n = st.text_input("שם מחסן")
            if st.form_submit_button("הוסף"):
                db.collection("Warehouses").add({"name": n})
                log_action("הוספת מחסן", n)
                st.rerun()
        st.divider()
        for w in db.collection("Warehouses").stream():
            c1, c2 = st.columns([4, 1])
            c1.info(w.to_dict()['name'])
            if c2.button("מחק", key=w.id):
                st.session_state[f"del_wh_{w.id}"] = True
            
            if st.session_state.get(f"del_wh_{w.id}"):
                st.error("למחוק? פריטים יועברו למחסן זמני.")
                if st.button("כן, מחק", key=f"yes_{w.id}"):
                    for i in db.collection("Inventory").where("warehouse", "==", w.to_dict()['name']).stream():
                        db.collection("Inventory").document(i.id).update({"warehouse": "מחסן זמני"})
                    db.collection("Warehouses").document(w.id).delete()
                    log_action("מחיקת מחסן", w.to_dict()['name'])
                    st.rerun()

    # ==========================================
    # 6. ניהול פריטים
    # ==========================================
    elif choice_key == "items":
        with st.expander("➕ הוסף פריט חדש"):
            d, r, y = st.text_input("תיאור"), st.text_input("מק\"ט רשות"), st.text_input("מק\"ט יצרן")
            if st.button("שמור"):
                db.collection("Items").add({"description": d, "internal_sku": r, "manufacturer_sku": y})
                log_action("הוספת פריט", d)
                st.rerun()
        st.divider()
        
        # אזור עריכה
        if st.session_state['edit_item_id']:
            doc = db.collection("Items").document(st.session_state['edit_item_id']).get()
            if doc.exists:
                data = doc.to_dict()
                st.info(f"עורך את: {data['description']}")
                with st.form("edit_item"):
                    nd = st.text_input("תיאור", data['description'])
                    ni = st.text_input("מק\"ט רשות", data['internal_sku'])
                    nm = st.text_input("מק\"ט יצרן", data['manufacturer_sku'])
                    if st.form_submit_button("שמור"):
                        db.collection("Items").document(st.session_state['edit_item_id']).update(
                            {"description": nd, "internal_sku": ni, "manufacturer_sku": nm}
                        )
                        # עדכון שמות במלאי הקיים
                        for i in db.collection("Inventory").where("item_id", "==", st.session_state['edit_item_id']).stream():
                             db.collection("Inventory").document(i.id).update({"item_name": nd})
                        
                        log_action("עריכת פריט", nd)
                        st.session_state['edit_item_id'] = None
                        st.rerun()
                if st.button("ביטול"): st.session_state['edit_item_id'] = None; st.rerun()

        else:
            for i in db.collection("Items").stream():
                it = i.to_dict()
                cols = st.columns([4, 1, 1])
                cols[0].write(f"🔹 {it['description']}")
                if cols[1].button("🗑️", key=f"d_{i.id}"): 
                    db.collection("Items").document(i.id).delete()
                    log_action("מחיקת פריט", it['description'])
                    st.rerun()
                if cols[2].button("✏️", key=f"e_{i.id}"): 
                    st.session_state['edit_item_id'] = i.id
                    st.rerun()

    # ==========================================
    # 7. ניהול משתמשים
    # ==========================================
    elif choice_key == "users":
        st.subheader("👥 ניהול צוות")
        users = list(db.collection("Users").stream())
        
        # בקשות איפוס
        resets = [u for u in users if u.to_dict().get('reset_requested')]
        if resets:
            st.warning("🔒 בקשות איפוס סיסמה")
            for u in resets:
                with st.container(border=True):
                    st.write(u.to_dict()['email'])
                    if st.button("אפס ל-123456", key=f"rst_{u.id}"):
                        db.collection("Users").document(u.id).update({"password": "123456", "reset_requested": False})
                        log_action("איפוס סיסמה", u.id)
                        st.rerun()

        # משתמשים ממתינים
        pending = [u for u in users if not u.to_dict().get('approved')]
        if pending:
            st.error("⏳ ממתינים לאישור")
            for u in pending:
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.write(u.to_dict()['email'])
                if c2.button("אשר", key=f"ap_{u.id}"): 
                    db.collection("Users").document(u.id).update({"approved": True})
                    log_action("אישור משתמש", u.id)
                    st.rerun()
                if c3.button("מחק", key=f"dl_{u.id}"): 
                    db.collection("Users").document(u.id).delete()
                    st.rerun()

        # משתמשים פעילים
        st.divider()
        st.write("✅ משתמשים פעילים")
        approved = [u for u in users if u.to_dict().get('approved')]
        for u in approved:
            d = u.to_dict()
            with st.expander(f"{d['email']} ({d.get('role')})"):
                nr = st.selectbox("תפקיד", ["יוזר מושך", "מנהל מלאי"], index=0 if d.get('role')=="יוזר מושך" else 1, key=f"r_{u.id}")
                if st.button("עדכן", key=f"u_{u.id}"):
                    db.collection("Users").document(u.id).update({"role": nr})
                    log_action("שינוי תפקיד", f"{u.id} -> {nr}")
                    st.rerun()

    # ==========================================
    # 8. לוגים
    # ==========================================
    elif choice_key == "logs":
        st.subheader("📜 יומן פעילות")
        logs = db.collection("Logs").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(50).stream()
        st.dataframe([l.to_dict() for l in logs])