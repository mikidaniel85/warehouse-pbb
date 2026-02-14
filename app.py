import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import json

# הגדרות תצוגה
st.set_page_config(page_title="ניהול מלאי שרוולים", layout="centered")

# --- 1. התחברות ל-Firebase (החלק המתוקן) ---
if not firebase_admin._apps:
    try:
        # בדיקה אם אנחנו בענן (Streamlit Cloud)
        if "firebase" in st.secrets:
            key_dict = dict(st.secrets["firebase"])
            # תיקון ירידות שורה במפתח
            if "private_key" in key_dict:
                key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(key_dict)
        else:
            # אנחנו במחשב מקומי
            cred = credentials.Certificate("serviceAccountKey.json")
            
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"שגיאה בהתחברות ל-Firebase: {e}")

# --- חשוב מאוד: השורה הזו חייבת להיות כאן, מחוץ ל-if ---
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
        "user": st.session_state['user_email'],
        "role": st.session_state['user_role'],
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

def get_pending_requests_count():
    try:
        return len(list(db.collection("Requests").where("status", "==", "pending").stream()))
    except:
        return 0

def get_pending_users_count():
    try:
        return len(list(db.collection("Users").where("approved", "==", False).stream()))
    except:
        return 0

# --- מסך כניסה ---
if not st.session_state['logged_in']:
    st.title("📦 מערכת מלאי גשרי עליה")
    tab1, tab2 = st.tabs(["כניסה", "הרשמה"])
    with tab1:
        email = st.text_input("אימייל", key="login_email")
        pw = st.text_input("סיסמה", type="password", key="login_pw")
        if st.button("התחבר", use_container_width=True):
            # כאן הייתה השגיאה שלך - עכשיו db בטוח קיים
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

# --- אפליקציה ראשית ---
else:
    req_count = get_pending_requests_count()
    usr_count = get_pending_users_count()
    
    req_alert = f"🔴 ({req_count})" if req_count > 0 else ""
    usr_alert = f"🔴 ({usr_count})" if usr_count > 0 else ""
    
    st.sidebar.write(f"מחובר: **{st.session_state['user_email']}**")
    st.sidebar.caption(f"תפקיד: {st.session_state['user_role']}")
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
        menu = {
            "search": "חיפוש ופעולות",
            "pull": "משיכת מלאי (יציאה)"
        }
    
    choice_key = st.sidebar.radio("תפריט", list(menu.keys()), format_func=lambda x: menu[x])
    st.title(f"📦 {menu[choice_key]}")

    # ==========================================
    # 1. חיפוש ופעולות
    # ==========================================
    if choice_key == "search":
        if st.session_state['active_action']:
            action = st.session_state['active_action']
            st.divider()
            st.info(f"מבצע פעולה על: **{action['name']}**")
            
            if action['type'] == 'pull':
                with st.form("act_pull"):
                    st.write("📤 **משיכה מהירה**")
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
                    st.write("🚚 **העברת מיקום**")
                    whs_list = [w.to_dict()['name'] for w in db.collection("Warehouses").stream()]
                    new_wh = st.selectbox("לאן להעביר?", whs_list)
                    c1, c2, c3 = st.columns(3)
                    nr = c1.text_input("שורה חדשה")
                    nc = c2.text_input("עמודה חדשה")
                    nf = c3.text_input("קומה חדשה")
                    if st.form_submit_button("בצע העברה"):
                        db.collection("Inventory").document(action['id']).update({
                            "warehouse": new_wh, "row": nr, "column": nc, "floor": nf
                        })
                        log_action("העברת פריט", f"{action['name']} הועבר ל-{new_wh}")
                        st.success("הפריט הועבר!")
                        st.session_state['active_action'] = None
                        st.rerun()
            
            if st.button("ביטול פעולה"):
                st.session_state['active_action'] = None
                st.rerun()
            st.divider()

        search_q = st.text_input("🔍 חפש פריט (התחל להקליד שם או מק\"ט)")
        inv_stream = db.collection("Inventory").stream()
        found_any = False
        
        for doc in inv_stream:
            d = doc.to_dict()
            if search_q and (search_q.lower() not in d['item_name'].lower() and search_q not in str(d.get('item_id', ''))):
                continue
            
            found_any = True
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                c1.markdown(f"**{d['item_name']}**")
                c1.caption(f"📍 {d['warehouse']} | שורה: {d.get('row')} | כמות: {d['quantity']}")
                
                if c2.button("📤 משוך", key=f"p_{doc.id}"):
                    st.session_state['active_action'] = {'type': 'pull', 'id': doc.id, 'name': d['item_name']}
                    st.rerun()
                
                if st.session_state['user_role'] == "מנהל מלאי":
                    if c2.button("🚚 הזז", key=f"m_{doc.id}"):
                        st.session_state['active_action'] = {'type': 'move', 'id': doc.id, 'name': d['item_name']}
                        st.rerun()

        if not found_any and search_q:
            st.warning("לא נמצאו תוצאות.")

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
                        log_action("אישור משיכה", f"אושר ל-{r['user_email']} למשוך {r['item_name']}")
                        st.success("אושר!")
                        st.rerun()
                    else:
                        st.error("פריט לא נמצא")
                if col_rej.button("❌ דחה", key=f"rj_{req.id}", use_container_width=True):
                    db.collection("Requests").document(req.id).update({"status": "rejected"})
                    log_action("דחיית משיכה", f"נדחה ל-{r['user_email']} עבור {r['item_name']}")
                    st.warning("הבקשה נדחתה.")
                    st.rerun()
        if not found: st.info("אין בקשות ממתינות.")

    # ==========================================
    # 3. קליטת מלאי
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
                st.info(f"💡 זוהה מיקום קיים: {d['warehouse']} (שורה {def_r})")

            with st.form("in_form"):
                sel_wh = st.selectbox("מחסן", whs_list, index=def_w_idx)
                c1, c2, c3 = st.columns(3)
                r = c1.text_input("שורה", value=def_r)
                c = c2.text_input("עמודה", value=def_c)
                f = c3.text_input("קומה", value=def_f)
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
                    log_action("קליטת מלאי", f"נקלטו {qty} יח' של {sel_item}")
                    st.success("נקלט בהצלחה!")

    # ==========================================
    # 4. משיכת מלאי
    # ==========================================
    elif choice_key == "pull":
        inv = db.collection("Inventory").where("quantity", ">", 0).stream()
        opts = {f"{d.to_dict()['item_name']} | {d.to_dict()['warehouse']} (כמות: {d.to_dict()['quantity']})": d.id for d in inv}
        if not opts:
            st.warning("המחסן ריק.")
        else:
            sel_key = st.selectbox("חפש פריט למשיכה", list(opts.keys()))
            with st.form("pull_f"):
                q = st.number_input("כמות", min_value=1)
                reason = st.text_input("סיבה")
                if st.form_submit_button("שלח לאישור"):
                    clean_name = sel_key.split("|")[0].strip()
                    db.collection("Requests").add({
                        "user_email": st.session_state['user_email'],
                        "item_name": clean_name, "location_id": opts[sel_key],
                        "quantity": q, "reason": reason,
                        "status": "pending", "timestamp": datetime.now()
                    })
                    log_action("בקשת משיכה", f"בקשה ל-{q} יח' של {clean_name}")
                    st.success("נשלח!")

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
                st.error(f"למחוק את {w.to_dict()['name']}?")
                cy, cn = st.columns(2)
                if cy.button("כן", key=f"y_{w.id}"):
                    for i in db.collection("Inventory").where("warehouse", "==", w.to_dict()['name']).stream():
                        db.collection("Inventory").document(i.id).update({"warehouse": "מחסן זמני"})
                    db.collection("Warehouses").document(w.id).delete()
                    log_action("מחיקת מחסן", w.to_dict()['name'])
                    st.rerun()
                if cn.button("לא", key=f"n_{w.id}"):
                    del st.session_state[f"del_wh_{w.id}"]
                    st.rerun()

    # ==========================================
    # 6. ניהול פריטים
    # ==========================================
    elif choice_key == "items":
        with st.expander("➕ הוסף פריט חדש"):
            d = st.text_input("תיאור"); r = st.text_input("מק\"ט רשותי"); y = st.text_input("מק\"ט יצרן")
            if st.button("שמור חדש"):
                db.collection("Items").add({"description": d, "internal_sku": r, "manufacturer_sku": y})
                log_action("הוספת פריט", d)
                st.rerun()
        
        st.divider()

        if st.session_state['edit_item_id']:
            try:
                doc_ref = db.collection("Items").document(st.session_state['edit_item_id'])
                doc = doc_ref.get()
                if doc.exists:
                    data = doc.to_dict()
                    old_name = data['description']
                    
                    st.info(f"✏️ עורך את: {data['description']}")
                    with st.form("edit_item_form"):
                        new_desc = st.text_input("תיאור", value=data['description'])
                        new_internal = st.text_input("מק\"ט רשותי", value=data['internal_sku'])
                        new_manuf = st.text_input("מק\"ט יצרן", value=data['manufacturer_sku'])
                        
                        c_save, c_cancel = st.columns(2)
                        if c_save.form_submit_button("שמור"):
                            doc_ref.update({
                                "description": new_desc,
                                "internal_sku": new_internal,
                                "manufacturer_sku": new_manuf
                            })
                            
                            # עדכון מלאי
                            count_updated = 0
                            inv_by_id = db.collection("Inventory").where("item_id", "==", st.session_state['edit_item_id']).stream()
                            for inv_doc in inv_by_id:
                                db.collection("Inventory").document(inv_doc.id).update({"item_name": new_desc})
                                count_updated += 1
                                
                            if old_name != new_desc:
                                inv_by_name = db.collection("Inventory").where("item_name", "==", old_name).stream()
                                for inv_doc in inv_by_name:
                                    db.collection("Inventory").document(inv_doc.id).update({
                                        "item_name": new_desc,
                                        "item_id": st.session_state['edit_item_id']
                                    })
                                    count_updated += 1

                            log_action("עריכת פריט", f"{old_name} -> {new_desc}")
                            st.success(f"עודכן! ({count_updated} במלאי)")
                            st.session_state['edit_item_id'] = None
                            st.rerun()
                        
                        if c_cancel.form_submit_button("ביטול"):
                            st.session_state['edit_item_id'] = None
                            st.rerun()
            except Exception as e:
                st.error(f"שגיאה: {e}")
                st.session_state['edit_item_id'] = None

        else:
            for i in db.collection("Items").stream():
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
        st.subheader("👥 משתמשים במערכת")
        
        # הפרדה בין ממתינים למאושרים
        users_stream = list(db.collection("Users").stream())
        pending = [u for u in users_stream if not u.to_dict().get('approved')]
        approved = [u for u in users_stream if u.to_dict().get('approved')]
        
        if pending:
            st.error(f"יש {len(pending)} משתמשים ממתינים לאישור!")
            for u in pending:
                data = u.to_dict()
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.write(f"**{data['email']}** ({data.get('role')})")
                    if c2.button("אשר", key=f"ap_{u.id}", use_container_width=True):
                        db.collection("Users").document(u.id).update({"approved": True})
                        log_action("אישור משתמש", u.id)
                        st.rerun()
                    if c3.button("מחק", key=f"dl_{u.id}", use_container_width=True):
                        db.collection("Users").document(u.id).delete()
                        log_action("מחיקת בקשת משתמש", u.id)
                        st.rerun()
            st.divider()

        st.write("✅ משתמשים פעילים")
        for u in approved:
            data = u.to_dict()
            with st.expander(f"{data['email']} - {data.get('role')}"):
                c1, c2 = st.columns(2)
                
                new_role = c1.selectbox("שנה תפקיד", ["יוזר מושך", "מנהל מלאי"], index=0 if data.get('role') == "יוזר מושך" else 1, key=f"rol_{u.id}")
                if c1.button("עדכן תפקיד", key=f"upd_{u.id}"):
                    db.collection("Users").document(u.id).update({"role": new_role})
                    log_action("שינוי תפקיד", f"{u.id} -> {new_role}")
                    st.success("עודכן")
                    st.rerun()
                
                if c2.button("מחק משתמש", key=f"delu_{u.id}"):
                    db.collection("Users").document(u.id).delete()
                    log_action("מחיקת משתמש", u.id)
                    st.warning("המשתמש נמחק")
                    st.rerun()

    # ==========================================
    # 8. יומן פעילות
    # ==========================================
    elif choice_key == "logs":
        st.subheader("📜 יומן פעילות")
        try:
            logs = db.collection("Logs").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(50).stream()
            
            data = []
            for log in logs:
                l = log.to_dict()
                data.append({
                    "זמן": l['timestamp'].strftime("%d/%m %H:%M"),
                    "משתמש": l['user'],
                    "פעולה": l['action'],
                    "פרטים": l['details']
                })
            
            if data:
                st.table(data)
            else:
                st.info("היומן ריק")
        except Exception as e:
            st.error(f"לא ניתן לטעון לוגים (אולי חסר אינדקס ב-Firebase): {e}")