import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import json
import pandas as pd

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
    keys_to_del = [k for k in st.session_state.keys() if k.startswith('del_')]
    for k in keys_to_del: del st.session_state[k]
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
    # 1. חיפוש ופעולות (פריסה מתוקנת + כפתורי קליטה לחדשים)
    # ==========================================
    if choice_key == "search":
        search_q = st.text_input("🔍 חפש פריט (שם או מק\"ט)")
        
        all_items_catalog = {doc.id: doc.to_dict() for doc in db.collection("Items").stream()}
        inv_stream = list(db.collection("Inventory").stream())
        
        found_inventory = []
        found_item_ids_in_inv = set()
        
        if search_q:
            for doc in inv_stream:
                d = doc.to_dict()
                item_id = d.get('item_id')
                catalog_data = all_items_catalog.get(item_id, {})
                sku = catalog_data.get('internal_sku', '')
                
                if (search_q.lower() in d['item_name'].lower()) or (search_q in str(sku)):
                    d['display_sku'] = sku
                    d['man_sku'] = catalog_data.get('manufacturer_sku', '')
                    found_inventory.append(doc)
                    found_item_ids_in_inv.add(item_id)

            found_catalog_only = []
            for item_id, data in all_items_catalog.items():
                if item_id not in found_item_ids_in_inv: 
                    if (search_q.lower() in data['description'].lower()) or (search_q in str(data['internal_sku'])):
                        found_catalog_only.append((item_id, data))

            # --- הצגת תוצאות: מלאי קיים ---
            if found_inventory:
                st.success(f"נמצאו {len(found_inventory)} פריטים במלאי")
                for doc in found_inventory:
                    d = doc.to_dict()
                    sku_display = d.get('display_sku', '')
                    man_sku_display = d.get('man_sku', '')
                    
                    with st.container(border=True):
                        # שינוי יחס עמודות: יותר מקום לכפתורים (2) כדי שלא יישברו שורה
                        c_info, c_actions = st.columns([3, 2])
                        
                        with c_info:
                            st.markdown(f"**{d['item_name']}**")
                            skus_text = ""
                            if sku_display: skus_text += f"🆔 {sku_display} "
                            if man_sku_display: skus_text += f"🏭 {man_sku_display}"
                            if skus_text: st.caption(skus_text)
                            
                            location_str = f"📍 {d['warehouse']} | שורה: {d.get('row', '-')} | עמ': {d.get('column', '-')} | קומה: {d.get('floor', '-')}"
                            st.caption(f"{location_str} | כמות: **{d['quantity']}**")
                        
                        with c_actions:
                            is_manager = st.session_state['user_role'] == "מנהל מלאי"
                            if is_manager:
                                # שימוש ב-3 עמודות פנימיות כדי להכריח אותם להיות בשורה
                                b1, b2, b3 = st.columns(3)
                                with b1:
                                    if st.button("📤", key=f"pull_{doc.id}", help="משיכה"):
                                        st.session_state['active_action'] = {'type': 'pull', 'id': doc.id, 'name': d['item_name']}
                                        st.rerun()
                                with b2:
                                    if st.button("🚚", key=f"move_{doc.id}", help="העברה"):
                                        st.session_state['active_action'] = {'type': 'move', 'id': doc.id, 'name': d['item_name']}
                                        st.rerun()
                                with b3:
                                    if st.button("📥", key=f"add_{doc.id}", help="הוספת כמות (קליטה)"):
                                        st.session_state['active_action'] = {'type': 'add_existing', 'id': doc.id, 'name': d['item_name']}
                                        st.rerun()
                            else:
                                if st.button("📤", key=f"pull_{doc.id}", help="משיכה", use_container_width=True):
                                    st.session_state['active_action'] = {'type': 'pull', 'id': doc.id, 'name': d['item_name']}
                                    st.rerun()

                    # טפסים (Inline) לפריטים קיימים
                    if st.session_state['active_action'] and st.session_state['active_action']['id'] == doc.id:
                        action = st.session_state['active_action']
                        with st.container(border=True):
                            if st.button("✖️ סגור", key=f"close_{doc.id}"):
                                st.session_state['active_action'] = None
                                st.rerun()

                            if action['type'] == 'pull':
                                st.markdown(f"**משיכה:** {action['name']}")
                                with st.form(f"form_pull_{doc.id}"):
                                    qty = st.number_input("כמות", min_value=1, step=1, value=1)
                                    reason = st.text_input("סיבה / שרוול")
                                    if st.form_submit_button("שלח בקשה"):
                                        db.collection("Requests").add({
                                            "user_email": st.session_state['user_email'],
                                            "item_name": action['name'], "location_id": action['id'],
                                            "quantity": int(qty), "reason": reason, "status": "pending", "timestamp": datetime.now()
                                        })
                                        log_action("בקשת משיכה", f"{qty} יח' של {action['name']}")
                                        st.success("הבקשה נשלחה!")
                                        st.session_state['active_action'] = None
                                        st.rerun()

                            elif action['type'] == 'move':
                                st.markdown(f"**העברה:** {action['name']}")
                                with st.form(f"form_move_{doc.id}"):
                                    whs_list = [w.to_dict()['name'] for w in db.collection("Warehouses").stream()]
                                    new_wh = st.selectbox("מחסן יעד", whs_list)
                                    c1, c2, c3 = st.columns(3)
                                    nr = c1.number_input("שורה", min_value=1, step=1, value=1)
                                    nc = c2.text_input("עמודה")
                                    nf = c3.number_input("קומה", min_value=1, step=1, value=1)
                                    if st.form_submit_button("בצע העברה"):
                                        db.collection("Inventory").document(action['id']).update({
                                            "warehouse": new_wh, "row": str(nr), "column": nc, "floor": str(nf)
                                        })
                                        log_action("העברת פריט", f"{action['name']} -> {new_wh}")
                                        st.success("המיקום עודכן!")
                                        st.session_state['active_action'] = None
                                        st.rerun()

                            elif action['type'] == 'add_existing':
                                st.markdown(f"**הוספת מלאי לאותו מיקום:** {action['name']}")
                                with st.form(f"form_add_{doc.id}"):
                                    qty_add = st.number_input("כמות להוספה", min_value=1, step=1, value=1)
                                    if st.form_submit_button("עדכן מלאי"):
                                        ref = db.collection("Inventory").document(action['id'])
                                        curr_qty = ref.get().to_dict()['quantity']
                                        ref.update({"quantity": curr_qty + qty_add})
                                        log_action("קליטה מהירה", f"נוספו {qty_add} ל-{action['name']}")
                                        st.success("המלאי עודכן!")
                                        st.session_state['active_action'] = None
                                        st.rerun()

            # --- הצגת תוצאות: רק בקטלוג (פריטים חדשים) ---
            if found_catalog_only:
                st.info(f"נמצאו {len(found_catalog_only)} פריטים בקטלוג (ללא מיקום מוגדר)")
                for item_id, data in found_catalog_only:
                    with st.container(border=True):
                        c_info, c_actions = st.columns([3, 2])
                        
                        with c_info:
                            st.markdown(f"**{data['description']}**")
                            skus_text = f"🆔 {data['internal_sku']}"
                            if data.get('manufacturer_sku'): skus_text += f" | 🏭 {data['manufacturer_sku']}"
                            st.caption(skus_text)
                            st.caption("⚠️ טרם שויך למחסן")
                        
                        with c_actions:
                            is_manager = st.session_state['user_role'] == "מנהל מלאי"
                            if is_manager:
                                # כפתור קליטה (הוספה) בלבד
                                if st.button("📥 שייך למחסן", key=f"new_{item_id}", help="קליטה ראשונית למלאי"):
                                    st.session_state['active_action'] = {'type': 'add_new', 'id': item_id, 'name': data['description']}
                                    st.rerun()

                    # טופס קליטה לפריט חדש (Inline)
                    if st.session_state['active_action'] and st.session_state['active_action']['id'] == item_id:
                        action = st.session_state['active_action']
                        with st.container(border=True):
                            if st.button("✖️ סגור", key=f"close_new_{item_id}"):
                                st.session_state['active_action'] = None
                                st.rerun()

                            if action['type'] == 'add_new':
                                st.markdown(f"**קליטה ראשונית:** {action['name']}")
                                whs_list = [w.to_dict()['name'] for w in db.collection("Warehouses").stream()]
                                
                                if not whs_list:
                                    st.error("חובה להגדיר מחסנים קודם!")
                                else:
                                    with st.form(f"form_new_{item_id}"):
                                        wh = st.selectbox("בחר מחסן", whs_list)
                                        c1, c2, c3 = st.columns(3)
                                        r = c1.number_input("שורה", min_value=1, step=1, value=1)
                                        c = c2.text_input("עמודה")
                                        f = c3.number_input("קומה", min_value=1, step=1, value=1)
                                        qty = st.number_input("כמות התחלתית", min_value=1, step=1, value=1)
                                        
                                        if st.form_submit_button("צור מיקום וקלוט מלאי"):
                                            str_r, str_f = str(r), str(f)
                                            # יצירת מזהה ייחודי למיקום
                                            loc_id = f"{wh}_{str_r}_{c}_{str_f}_{item_id}"
                                            
                                            db.collection("Inventory").document(loc_id).set({
                                                "item_name": action['name'], 
                                                "warehouse": wh, 
                                                "row": str_r, "column": c, "floor": str_f, 
                                                "quantity": int(qty), 
                                                "item_id": item_id
                                            })
                                            log_action("קליטה ראשונית", f"{qty} יח' של {action['name']} ל-{wh}")
                                            st.success("הפריט שויך ונקלט בהצלחה!")
                                            st.session_state['active_action'] = None
                                            st.rerun()

            if not found_inventory and not found_catalog_only:
                 st.warning("לא נמצאו תוצאות.")

        elif not search_q:
             st.info("הקלד לחיפוש...")

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
                 st.write(f"**{r['user_email']}** מבקש **{r['quantity']}** יח' של **{r['item_name']}**")
                 if r.get('reason'):
                     st.info(f"📝 סיבה: {r['reason']}")
                 else:
                     st.caption("ללא סיבה")
                 
                 c1, c2 = st.columns(2)
                 if c1.button("✅ אשר", key=f"ok_{req.id}"):
                     inv_ref = db.collection("Inventory").document(r['location_id'])
                     s = inv_ref.get()
                     if s.exists:
                         inv_ref.update({"quantity": max(0, s.to_dict()['quantity'] - r['quantity'])})
                         db.collection("Requests").document(req.id).update({"status": "approved"})
                         log_action("אישור משיכה", f"אושר ל-{r['user_email']} למשוך {r['item_name']}")
                         st.rerun()
                     else:
                         st.error("הפריט כבר לא קיים במלאי")
                 
                 if c2.button("❌ דחה", key=f"rj_{req.id}"):
                     db.collection("Requests").document(req.id).update({"status": "rejected"})
                     log_action("דחיית משיכה", f"נדחה ל-{r['user_email']} עבור {r['item_name']}")
                     st.rerun()
         if not found: st.info("אין בקשות.")

    # ==========================================
    # 3. קליטת מלאי
    # ==========================================
    elif choice_key == "stock_in":
        items = {i.to_dict()['description']: i.id for i in db.collection("Items").stream()}
        whs = [w.to_dict()['name'] for w in db.collection("Warehouses").stream()]
        
        if items and whs:
            st.write("🔽 **שלב 1: חיפוש פריט**")
            search_item_text = st.text_input("הקלד כאן כדי לסנן את הרשימה", key="si_search")
            
            filtered_items = list(items.keys())
            if search_item_text:
                filtered_items = [k for k in filtered_items if search_item_text.lower() in k.lower()]
            
            if filtered_items:
                si = st.selectbox("בחר פריט", filtered_items, key="si_select")
                
                with st.form("sin"):
                    wh = st.selectbox("מחסן", whs)
                    st.caption("מיקום:")
                    c1, c2, c3 = st.columns(3)
                    r = c1.number_input("שורה", min_value=1, step=1, value=1)
                    c = c2.text_input("עמודה")
                    f = c3.number_input("קומה", min_value=1, step=1, value=1)
                    q = st.number_input("כמות לקליטה", min_value=1, step=1, value=1)
                    
                    if st.form_submit_button("קלוט מלאי"):
                        str_r, str_f = str(r), str(f)
                        loc = f"{wh}_{str_r}_{c}_{str_f}_{items[si]}"
                        ref = db.collection("Inventory").document(loc)
                        if ref.get().exists: 
                            ref.update({"quantity": ref.get().to_dict()['quantity'] + q})
                        else: 
                            ref.set({
                                "item_name": si, "warehouse": wh, 
                                "row": str_r, "column": c, "floor": str_f, 
                                "quantity": int(q), "item_id": items[si]
                            })
                        log_action("קליטה", f"{q} {si}")
                        st.success("נקלט בהצלחה!")
            else:
                st.warning("לא נמצאו פריטים.")

    # ==========================================
    # 4. משיכת מלאי
    # ==========================================
    elif choice_key == "pull":
        inv = db.collection("Inventory").where("quantity", ">", 0).stream()
        opts = {}
        for d in inv:
            data = d.to_dict()
            label = f"{data['item_name']} | {data['warehouse']} (שורה {data.get('row','-')} עמ' {data.get('column','-')}) | כמות: {data['quantity']}"
            opts[label] = d.id

        if opts:
            st.write("🔽 **שלב 1: חיפוש במלאי**")
            search_pull_text = st.text_input("הקלד כאן לסינון", key="pull_search")
            
            filtered_opts = list(opts.keys())
            if search_pull_text:
                filtered_opts = [k for k in filtered_opts if search_pull_text.lower() in k.lower()]
            
            if filtered_opts:
                k = st.selectbox("בחר פריט למשיכה", filtered_opts, key="pull_select")
                
                with st.form("pf"):
                    q = st.number_input("כמות", min_value=1, step=1, value=1)
                    rs = st.text_input("סיבה / שרוול")
                    if st.form_submit_button("שלח בקשה"):
                        item_clean_name = k.split('|')[0].strip()
                        db.collection("Requests").add({
                            "user_email": st.session_state['user_email'], 
                            "item_name": item_clean_name, 
                            "location_id": opts[k], 
                            "quantity": int(q), "reason": rs, "status": "pending", "timestamp": datetime.now()
                        })
                        st.success("נשלח!")
            else:
                st.warning("לא נמצאו פריטים.")
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
            c1, c2 = st.columns([4,1])
            c1.info(w.to_dict()['name'])
            
            if c2.button("🗑️", key=f"btn_del_wh_{w.id}"):
                st.session_state[f"del_wh_{w.id}"] = True
                st.rerun()
            
            if st.session_state.get(f"del_wh_{w.id}", False):
                st.error(f"למחוק את {w.to_dict()['name']}?")
                col_yes, col_no = st.columns(2)
                if col_yes.button("✅", key=f"yes_wh_{w.id}"):
                    for i in db.collection("Inventory").where("warehouse", "==", w.to_dict()['name']).stream():
                        db.collection("Inventory").document(i.id).update({"warehouse": "מחסן זמני"})
                    db.collection("Warehouses").document(w.id).delete()
                    log_action("מחיקת מחסן", w.to_dict()['name'])
                    del st.session_state[f"del_wh_{w.id}"]
                    st.rerun()
                if col_no.button("❌", key=f"no_wh_{w.id}"):
                    del st.session_state[f"del_wh_{w.id}"]
                    st.rerun()

    # ==========================================
    # 6. ניהול פריטים
    # ==========================================
    elif choice_key == "items":
        with st.expander("📂 ייבוא פריטים מאקסל/CSV"):
            st.info("כותרות נתמכות: description (תיאור), internal_sku (מק\"ט), manufacturer_sku (יצרן)")
            uploaded_file = st.file_uploader("גרור לכאן קובץ", type=['csv', 'xlsx'])
            
            if uploaded_file and st.button("התחל טעינה"):
                try:
                    if uploaded_file.name.endswith('.csv'):
                        try:
                            df = pd.read_csv(uploaded_file, encoding='utf-8')
                        except UnicodeDecodeError:
                            uploaded_file.seek(0)
                            df = pd.read_csv(uploaded_file, encoding='windows-1255')
                    else:
                        df = pd.read_excel(uploaded_file)

                    df.columns = [c.strip().lower() for c in df.columns]
                    column_map = {
                        'תיאור': 'description', 'שם פריט': 'description',
                        'מקט': 'internal_sku', 'מק"ט': 'internal_sku', 'מק\"ט': 'internal_sku', 'מקט רשות': 'internal_sku',
                        'יצרן': 'manufacturer_sku', 'מקט יצרן': 'manufacturer_sku'
                    }
                    df.rename(columns=column_map, inplace=True)

                    if 'description' not in df.columns or 'internal_sku' not in df.columns:
                        st.error(f"שגיאה בכותרות הקובץ! זוהה: {list(df.columns)}")
                        st.stop()

                    existing_skus = {doc.to_dict().get('internal_sku') for doc in db.collection("Items").stream()}
                    added, skipped = 0, 0
                    progress_bar = st.progress(0)
                    total_rows = len(df)

                    for index, row in df.iterrows():
                        desc = str(row['description']).strip()
                        int_sku = str(row['internal_sku']).strip()
                        man_sku = ""
                        if 'manufacturer_sku' in row:
                            val = str(row['manufacturer_sku']).strip()
                            if val.lower() != 'nan' and val.lower() != 'none': man_sku = val
                        
                        if int_sku in existing_skus or not int_sku or int_sku == 'nan':
                            skipped += 1
                            continue
                        
                        db.collection("Items").add({"description": desc, "internal_sku": int_sku, "manufacturer_sku": man_sku})
                        existing_skus.add(int_sku)
                        added += 1
                        progress_bar.progress((index + 1) / total_rows)
                    
                    st.success(f"✅ טעינה הסתיימה: {added} נוספו | {skipped} דולגו")
                except Exception as e:
                    st.error(f"שגיאה בקריאת הקובץ: {e}")

        st.divider()
        manage_search = st.text_input("🔍 חפש ברשימה", placeholder="שם או מק\"ט")
        
        with st.expander("➕ הוסף ידנית"):
            d, r, y = st.text_input("תיאור"), st.text_input("מק\"ט רשות"), st.text_input("יצרן")
            if st.button("שמור חדש"):
                if list(db.collection("Items").where("internal_sku", "==", r).stream()): 
                    st.error("מק\"ט קיים!")
                else: 
                    db.collection("Items").add({"description": d, "internal_sku": r, "manufacturer_sku": y})
                    st.success("נוסף!")
                    st.rerun()
        
        st.write("---")

        if st.session_state['edit_item_id']:
            doc = db.collection("Items").document(st.session_state['edit_item_id']).get()
            if doc.exists:
                data = doc.to_dict()
                with st.form("edit_item"):
                    nd = st.text_input("תיאור", data['description'])
                    ni = st.text_input("מק\"ט רשות", data['internal_sku'])
                    nm = st.text_input("מק\"ט יצרן", data.get('manufacturer_sku', ''))
                    if st.form_submit_button("שמור"):
                        db.collection("Items").document(st.session_state['edit_item_id']).update({"description": nd, "internal_sku": ni, "manufacturer_sku": nm})
                        for i in db.collection("Inventory").where("item_id", "==", st.session_state['edit_item_id']).stream():
                             db.collection("Inventory").document(i.id).update({"item_name": nd})
                        st.session_state['edit_item_id'] = None
                        st.rerun()
                if st.button("ביטול"): st.session_state['edit_item_id'] = None; st.rerun()
        else:
            items_stream = list(db.collection("Items").stream())
            filtered = [i for i in items_stream if not manage_search or (manage_search.lower() in i.to_dict()['description'].lower() or manage_search in str(i.to_dict()['internal_sku']))]
            
            for i in filtered:
                it = i.to_dict()
                cols = st.columns([4, 1, 1])
                cols[0].write(f"🔹 {it['description']} ({it['internal_sku']})")
                
                if cols[1].button("🗑️", key=f"btn_del_it_{i.id}"):
                    st.session_state[f"del_it_{i.id}"] = True
                    st.rerun()
                
                if st.session_state.get(f"del_it_{i.id}", False):
                    st.error(f"למחוק את {it['description']}?")
                    cy, cn = st.columns(2)
                    if cy.button("כן", key=f"yes_it_{i.id}"):
                        db.collection("Items").document(i.id).delete()
                        log_action("מחיקת פריט", it['description'])
                        del st.session_state[f"del_it_{i.id}"]
                        st.rerun()
                    if cn.button("ביטול", key=f"no_it_{i.id}"):
                        del st.session_state[f"del_it_{i.id}"]
                        st.rerun()

                if cols[2].button("✏️", key=f"e_{i.id}"): st.session_state['edit_item_id'] = i.id; st.rerun()

    # ==========================================
    # 7. ניהול משתמשים
    # ==========================================
    elif choice_key == "users":
        st.subheader("👥 ניהול צוות")
        
        users_stream = list(db.collection("Users").stream())
        pending = [u for u in users_stream if not u.to_dict().get('approved')]
        reset_reqs = [u for u in users_stream if u.to_dict().get('reset_requested')]
        approved = [u for u in users_stream if u.to_dict().get('approved')]
        
        if reset_reqs:
            st.warning(f"🔒 {len(reset_reqs)} בקשות איפוס")
            for u in reset_reqs:
                data = u.to_dict()
                with st.container(border=True):
                    st.write(f"{data['email']} מבקש איפוס")
                    if st.button("אפס ל-123456", key=f"rst_{u.id}"):
                        db.collection("Users").document(u.id).update({"password": "123456", "reset_requested": False})
                        st.rerun()

        if pending:
            st.error(f"⏳ {len(pending)} ממתינים")
            for u in pending:
                data = u.to_dict()
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.write(f"**{data['email']}** ({data.get('role')})")
                    if c2.button("אשר", key=f"ap_{u.id}"):
                        db.collection("Users").document(u.id).update({"approved": True})
                        st.rerun()
                    if c3.button("מחק", key=f"dl_{u.id}"):
                        db.collection("Users").document(u.id).delete()
                        st.rerun()

        st.divider()
        st.write("✅ משתמשים פעילים")
        for u in approved:
            data = u.to_dict()
            with st.expander(f"{data['email']} ({data.get('role')})"):
                c1, c2 = st.columns(2)
                curr_role = data.get('role', 'יוזר מושך')
                idx = 1 if curr_role == "מנהל מלאי" else 0
                new_role = c1.selectbox("תפקיד", ["יוזר מושך", "מנהל מלאי"], index=idx, key=f"r_{u.id}")
                
                if c1.button("עדכן תפקיד", key=f"upd_{u.id}"):
                    db.collection("Users").document(u.id).update({"role": new_role})
                    st.success("עודכן")
                    st.rerun()
                
                if c2.button("מחק משתמש", key=f"btn_del_u_{u.id}"):
                    st.session_state[f"del_u_{u.id}"] = True
                    st.rerun()
                
                if st.session_state.get(f"del_u_{u.id}", False):
                    st.error("למחוק משתמש זה?")
                    uy, un = st.columns(2)
                    if uy.button("כן", key=f"yes_u_{u.id}"):
                        db.collection("Users").document(u.id).delete()
                        log_action("מחיקת משתמש", u.id)
                        del st.session_state[f"del_u_{u.id}"]
                        st.rerun()
                    if un.button("ביטול", key=f"no_u_{u.id}"):
                        del st.session_state[f"del_u_{u.id}"]
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
                ts = l.get('timestamp')
                time_str = ts.strftime("%d/%m %H:%M") if ts else "?"
                data.append({
                    "זמן": time_str,
                    "משתמש": l.get('user', '?'),
                    "פעולה": l.get('action', '?'),
                    "פרטים": l.get('details', '?')
                })
            if data:
                st.table(data)
            else:
                st.info("היומן ריק")
        except Exception as e:
            st.error(f"לא ניתן לטעון לוגים: {e}")