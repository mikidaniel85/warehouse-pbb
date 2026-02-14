import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import json
import pandas as pd # ספרייה לטיפול באקסל

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
    # 1. חיפוש ופעולות
    # ==========================================
    if choice_key == "search":
        search_q = st.text_input("🔍 חפש פריט (שם או מק\"ט)")
        
        inv_stream = list(db.collection("Inventory").stream())
        found_items = []
        
        if search_q:
            for doc in inv_stream:
                d = doc.to_dict()
                if (search_q.lower() in d['item_name'].lower()) or (search_q in str(d.get('item_id', ''))):
                    found_items.append(doc)
        
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
            st.warning("לא נמצאו תוצאות.")

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

    # ==========================================
    # 2. אישור משיכות
    # ==========================================
    elif choice_key == "approve":
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

    # ==========================================
    # 3. קליטת מלאי
    # ==========================================
    elif choice_key == "stock_in":
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

    # ==========================================
    # 4. משיכת מלאי (ידנית)
    # ==========================================
    elif choice_key == "pull":
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
        for w in db.collection("Warehouses").stream():
            c1, c2 = st.columns([4,1])
            c1.info(w.to_dict()['name'])
            if c2.button("🗑️", key=w.id): db.collection("Warehouses").document(w.id).delete(); st.rerun()

    # ==========================================
    # 6. ניהול פריטים (עם ייבוא חכם)
    # ==========================================
    elif choice_key == "items":
        
        # --- אזור ייבוא מאקסל (משודרג) ---
        with st.expander("📂 ייבוא פריטים מאקסל/CSV"):
            st.info("""
            **הוראות להכנת הקובץ:**
            הקובץ חייב להכיל כותרות באנגלית בשורה הראשונה בדיוק כך:
            `description` | `internal_sku` | `manufacturer_sku`
            
            * המערכת תבדוק כפילויות לפי **מק"ט רשותי (internal_sku)**.
            * פריט שכבר קיים - המערכת **תדלג** עליו ולא תדרוס אותו.
            """)
            
            uploaded_file = st.file_uploader("גרור לכאן קובץ", type=['csv', 'xlsx'])
            
            if uploaded_file and st.button("התחל טעינה"):
                try:
                    # טעינת הקובץ
                    if uploaded_file.name.endswith('.csv'):
                        df = pd.read_csv(uploaded_file)
                    else:
                        df = pd.read_excel(uploaded_file)
                    
                    # בדיקת עמודות
                    req_cols = ['description', 'internal_sku']
                    if not all(col in df.columns for col in req_cols):
                        st.error("❌ הקובץ לא תקין. חסרות עמודות חובה: description, internal_sku")
                    else:
                        # שליפת כל המק"טים הקיימים כדי למנוע כפילויות (יעיל יותר משאילתה בודדת)
                        existing_skus = {doc.to_dict().get('internal_sku') for doc in db.collection("Items").stream()}
                        
                        added_count = 0
                        skipped_count = 0
                        
                        progress_bar = st.progress(0)
                        total_rows = len(df)
                        
                        for index, row in df.iterrows():
                            # עדכון מד התקדמות
                            progress_bar.progress((index + 1) / total_rows)
                            
                            desc = str(row['description']).strip()
                            int_sku = str(row['internal_sku']).strip()
                            man_sku = str(row.get('manufacturer_sku', '')).strip()
                            if man_sku == 'nan': man_sku = ""
                            
                            # דילוג אם המק"ט כבר קיים
                            if int_sku in existing_skus:
                                skipped_count += 1
                                continue
                            
                            # הוספה למסד הנתונים
                            db.collection("Items").add({
                                "description": desc,
                                "internal_sku": int_sku,
                                "manufacturer_sku": man_sku
                            })
                            # הוספה לסט המקומי כדי למנוע כפילויות בתוך הקובץ עצמו
                            existing_skus.add(int_sku)
                            added_count += 1
                        
                        st.success(f"✅ הסתיים! נוספו: {added_count} | דולגו (כפולים): {skipped_count}")
                        log_action("ייבוא קובץ", f"נוספו {added_count}, דולגו {skipped_count}")
                        if added_count > 0:
                            st.balloons()
                            
                except Exception as e:
                    st.error(f"שגיאה בטעינת הקובץ: {e}")

        # --- הוספה ידנית ---
        with st.expander("➕ הוסף פריט בודד"):
            d, r, y = st.text_input("תיאור"), st.text_input("מק\"ט רשות"), st.text_input("יצרן")
            if st.button("שמור חדש"):
                # בדיקת כפילות ידנית
                exist = list(db.collection("Items").where("internal_sku", "==", r).stream())
                if exist:
                    st.error("מק\"ט זה כבר קיים במערכת!")
                else:
                    db.collection("Items").add({"description": d, "internal_sku": r, "manufacturer_sku": y})
                    log_action("הוספת פריט", d)
                    st.rerun()
        
        st.divider()

        # --- רשימת הפריטים ---
        if st.session_state['edit_item_id']:
            doc = db.collection("Items").document(st.session_state['edit_item_id']).get()
            if doc.exists:
                data = doc.to_dict()
                st.info(f"עורך את: {data['description']}")
                with st.form("edit_item"):
                    nd = st.text_input("תיאור", data['description'])
                    ni = st.text_input("מק\"ט רשות", data['internal_sku'])
                    nm = st.text_input("מק\"ט יצרן", data.get('manufacturer_sku', ''))
                    if st.form_submit_button("שמור"):
                        db.collection("Items").document(st.session_state['edit_item_id']).update(
                            {"description": nd, "internal_sku": ni, "manufacturer_sku": nm}
                        )
                        # עדכון שמות במלאי
                        for i in db.collection("Inventory").where("item_id", "==", st.session_state['edit_item_id']).stream():
                             db.collection("Inventory").document(i.id).update({"item_name": nd})
                        
                        log_action("עריכת פריט", nd)
                        st.session_state['edit_item_id'] = None
                        st.rerun()
                if st.button("ביטול"): st.session_state['edit_item_id'] = None; st.rerun()
        else:
            items_stream = db.collection("Items").stream()
            for i in items_stream:
                it = i.to_dict()
                cols = st.columns([4, 1, 1])
                cols[0].write(f"🔹 {it['description']} ({it['internal_sku']})")
                if cols[1].button("🗑️", key=f"del_{i.id}"):
                    db.collection("Items").document(i.id).delete()
                    log_action("מחיקת פריט", it['description'])
                    st.rerun()
                if cols[2].button("✏️", key=f"edit_{i.id}"):
                    st.session_state['edit_item_id'] = i.id
                    st.rerun()

    # ==========================================
    # 7. ניהול משתמשים
    # ==========================================
    elif choice_key == "users":
        for u in db.collection("Users").stream():
            d = u.to_dict()
            with st.expander(f"{d['email']} ({'ממתין' if not d.get('approved') else 'פעיל'})"):
                if not d.get('approved'): 
                    if st.button("אשר", key=f"a_{u.id}"): db.collection("Users").document(u.id).update({"approved": True}); st.rerun()
                if d.get('reset_requested'):
                    if st.button("אפס", key=f"r_{u.id}"): db.collection("Users").document(u.id).update({"password": "123456", "reset_requested": False}); st.rerun()

    # ==========================================
    # 8. לוגים
    # ==========================================
    elif choice_key == "logs":
        st.dataframe([l.to_dict() for l in db.collection("Logs").order_by("timestamp", direction="DESCENDING").limit(20).stream()])