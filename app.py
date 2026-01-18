import streamlit as st
import pandas as pd
import requests
import time
import traceback
import math
from datetime import datetime, date

# ================= CONFIGURATION =================
try:
    NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
    CHALLONGE_API_KEY = st.secrets.get("CHALLONGE_API_KEY", "")
except FileNotFoundError:
    NOTION_TOKEN = "YOUR_TOKEN"
    CHALLONGE_API_KEY = ""

MEMBER_DB_ID = "271e6d24b97d80289175eef889a90a09" 
HISTORY_DB_ID = "2b1e6d24b97d803786c2ec7011c995ef" # ประวัติ Rank SS2 ปกติ
PROJECT_DB_ID = "26fe6d24b97d80e1bdb3c2452a31694c" 

# 🔥 [NEW] ใส่ ID ของ Database "สถิติการลง Rank Junior ทั้งหมด" ตรงนี้
JUNIOR_HISTORY_DB_ID = "2ece6d24b97d81c68562fae068f1483c" 

headers = {
    "Authorization": "Bearer " + NOTION_TOKEN,
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ================= HELPER FUNCTIONS =================

@st.cache_data(ttl=300) 
def fetch_all_members_data():
    url = f"https://api.notion.com/v1/databases/{MEMBER_DB_ID}/query"
    members_list = []
    has_more = True
    next_cursor = None
    
    while has_more:
        payload = {}
        if next_cursor: payload["start_cursor"] = next_cursor
        try:
            response = requests.post(url, json=payload, headers=headers)
            if response.status_code != 200: break
            data = response.json()
            for page in data.get("results", []):
                try:
                    name = f"Unknown-{page['id'][-4:]}"
                    if "ชื่อ" in page["properties"] and page["properties"]["ชื่อ"]["title"]:
                        name_val = page["properties"]["ชื่อ"]["title"][0]["text"]["content"].strip()
                        if name_val: name = name_val
                    
                    score = 0
                    score_prop = page["properties"].get("คะแนน Rank SS2") 
                    if score_prop:
                        if score_prop['type'] == 'number': score = score_prop['number'] or 0
                        elif score_prop['type'] == 'rollup': score = score_prop['rollup'].get('number', 0) or 0
                        elif score_prop['type'] == 'formula': score = score_prop['formula'].get('number', 0) or 0
                    
                    members_list.append({"id": page["id"], "name": name, "score": score})
                except: continue
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
        except: break
    return members_list

def find_member_smart(raw_text, members_list):
    if not isinstance(raw_text, str): return None, None
    sorted_members = sorted(members_list, key=lambda x: len(x['name']), reverse=True)
    for member in sorted_members:
        if member['name'] in raw_text:
            return member['name'], member
    return None, None

def get_project_info(project_name):
    url = f"https://api.notion.com/v1/databases/{PROJECT_DB_ID}/query"
    payload = {"filter": {"property": "ชื่อกิจกรรม", "title": {"contains": str(project_name).strip()}}}
    try:
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        if data.get('results'):
            page = data['results'][0]
            project_id = page['id']
            event_type = "ทั่วไป"
            props = page.get('properties', {})
            if 'ประเภทงาน' in props:
                prop = props['ประเภทงาน']
                if prop['type'] == 'select' and prop['select']: event_type = prop['select']['name']
                elif prop['type'] == 'multi_select' and prop['multi_select']: event_type = prop['multi_select'][0]['name']
            return {"id": project_id, "type": event_type}
        return None
    except: return None

@st.cache_data(ttl=300)
def get_all_projects_list():
    url = f"https://api.notion.com/v1/databases/{PROJECT_DB_ID}/query"
    projects = {} 
    has_more = True; next_cursor = None
    while has_more:
        payload = { "sorts": [ { "property": "วันที่จัดกิจกรรม", "direction": "descending" } ] }
        if next_cursor: payload["start_cursor"] = next_cursor
        try:
            res = requests.post(url, json=payload, headers=headers).json()
            for page in res.get("results", []):
                try:
                    title = page["properties"]["ชื่อกิจกรรม"]["title"][0]["text"]["content"]
                    event_type = "ทั่วไป"
                    props = page.get('properties', {})
                    if 'ประเภทงาน' in props:
                        pt = props['ประเภทงาน']
                        if pt['type'] == 'select' and pt['select']: event_type = pt['select']['name']
                        elif pt['type'] == 'multi_select' and pt['multi_select']: event_type = pt['multi_select'][0]['name']
                    projects[title] = { "id": page["id"], "type": event_type }
                except: pass
            has_more = res.get("has_more", False)
            next_cursor = res.get("next_cursor")
        except: break
    return projects

def calculate_score(row_index, is_minor_event):
    score = 0
    if row_index == 1: score = 25
    elif row_index == 2: score = 20
    elif row_index == 3: score = 16
    elif row_index == 4: score = 13
    elif 5 <= row_index <= 8: score = 10
    elif 9 <= row_index <= 16: score = 5
    else: score = 2
    
    if is_minor_event:
        score = math.ceil(score / 2)
    return score

# 🔥 UPDATED: เพิ่ม target_db_id เพื่อให้รองรับทั้ง Junior และ Normal
def check_history_exists(member_id, project_id, target_db_id, is_bonus=False):
    url = f"https://api.notion.com/v1/databases/{target_db_id}/query"
    
    # ⚠️ หมายเหตุ: ชื่อ Property Relation ใน Junior DB ต้องเป็น "สมาชิกแรงค์" และ "ชื่องานแข่ง" เหมือนกัน
    # ถ้าใน Junior ตั้งชื่อ column ต่างไป ต้องแก้โค้ดตรงนี้ตามจริงครับ
    filter_cond = {
        "and": [
            {"property": "สมาชิกแรงค์", "relation": {"contains": member_id}},
            {"property": "ชื่องานแข่ง", "relation": {"contains": project_id}}
        ]
    }
    
    if is_bonus: return False 

    payload = {"filter": filter_cond}
    try:
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        return len(data.get("results", [])) > 0
    except:
        return False

# 🔥 UPDATED: เพิ่ม target_db_id
def create_history_record(project_id, member_id, score, record_name, target_db_id):
    url = "https://api.notion.com/v1/pages"
    
    # ⚠️ หมายเหตุ: ชื่อ Property ใน Junior DB ต้องตรงกับด้านล่างนี้
    properties = {
        "Name": { "title": [{"text": {"content": str(record_name)}}] },
        "สมาชิกแรงค์": { "relation": [{"id": member_id}] },
        "ชื่องานแข่ง": { "relation": [{"id": project_id}] },
        "คะแนนที่บวก": { "number": float(score) }
    }
    payload = {"parent": {"database_id": target_db_id}, "properties": properties}
    requests.post(url, json=payload, headers=headers)
    return True

def get_season2_stats_data():
    target_start = date(2026, 1, 1)
    target_end = date(2026, 3, 31)
    url = f"https://api.notion.com/v1/databases/{PROJECT_DB_ID}/query"
    has_more = True; next_cursor = None
    target_event_ids = set()
    while has_more:
        payload = {}
        if next_cursor: payload["start_cursor"] = next_cursor
        res = requests.post(url, json=payload, headers=headers).json()
        for page in res.get("results", []):
            props = page.get('properties', {})
            event_type = "ทั่วไป"
            if 'ประเภทงาน' in props:
                pt = props['ประเภทงาน']
                if pt['type'] == 'select' and pt['select']: event_type = pt['select']['name']
                elif pt['type'] == 'multi_select' and pt['multi_select']: event_type = pt['multi_select'][0]['name']
            event_date_str = None
            date_prop = props.get("วันที่จัดกิจกรรม") or props.get("วันที่จัดงาน")
            if date_prop: 
                date_obj = date_prop.get("date")
                if date_obj: event_date_str = date_obj.get("start")
            if event_date_str:
                try:
                    e_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
                    if target_start <= e_date <= target_end and "งานย่อย" not in str(event_type):
                        target_event_ids.add(page['id'])
                except: pass
        has_more = res.get("has_more", False)
        next_cursor = res.get("next_cursor")
    
    attendance_map = {} 
    h_url = f"https://api.notion.com/v1/databases/{HISTORY_DB_ID}/query"
    has_more = True; next_cursor = None
    while has_more:
        payload = {}
        if next_cursor: payload["start_cursor"] = next_cursor
        h_res = requests.post(h_url, json=payload, headers=headers).json()
        for page in h_res.get("results", []):
            props = page.get("properties", {})
            mem_rels = props.get("สมาชิกแรงค์", {}).get("relation", [])
            if not mem_rels: continue
            mem_id = mem_rels[0]['id']
            proj_rels = props.get("ชื่องานแข่ง", {}).get("relation", [])
            if not proj_rels: continue
            proj_id = proj_rels[0]['id']
            if proj_id in target_event_ids:
                if mem_id not in attendance_map: attendance_map[mem_id] = set()
                attendance_map[mem_id].add(proj_id)
        has_more = h_res.get("has_more", False)
        next_cursor = h_res.get("next_cursor")
    return len(target_event_ids), attendance_map

def update_rank_and_stats_to_notion(page_id, rank_text, stats_text):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    properties = {
        "อันดับ Rank SS2": { "rich_text": [{"text": {"content": str(rank_text)}}] },
        "สถิติเข้าร่วม SS2": { "rich_text": [{"text": {"content": str(stats_text)}}] }
    }
    payload = {"properties": properties}
    try:
        res = requests.patch(url, json=payload, headers=headers)
        return res.status_code == 200
    except: return False

def get_challonge_full_data(tournament_id, api_key):
    custom_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    YOUR_USERNAME = "junpisa@gmail.com"
    try:
        p_url = f"https://api.challonge.com/v1/tournaments/{tournament_id}/participants.json"
        p_res = requests.get(p_url, headers=custom_headers, auth=(YOUR_USERNAME, api_key))
        if p_res.status_code != 200: return None, f"Error Participants: {p_res.text}"
        
        participants_map = {} 
        for p in p_res.json():
            p_data = p['participant']
            participants_map[p_data['id']] = {
                "name": p_data['name'],
                "final_rank": p_data.get('final_rank')
            }

        m_url = f"https://api.challonge.com/v1/tournaments/{tournament_id}/matches.json"
        m_res = requests.get(m_url, headers=custom_headers, auth=(YOUR_USERNAME, api_key))
        if m_res.status_code != 200: return None, f"Error Matches: {m_res.text}"
        
        matches = []
        for m in m_res.json():
            m_data = m['match']
            if m_data['state'] == 'complete' and m_data['winner_id']:
                matches.append({"winner_id": m_data['winner_id'], "loser_id": m_data['loser_id']})
                
        return {"participants": participants_map, "matches": matches}, None
    except Exception as e: return None, f"Connection Error: {str(e)}"

# ================= UI PART =================

st.set_page_config(page_title="Rank & Lomyak System", page_icon="⚔️", layout="wide")
st.title("⚔️ Rank & Giant Killing System")

# เพิ่ม Tab ที่ 4 สำหรับ Junior
tab1, tab2, tab3, tab4 = st.tabs(["⚡ อัปเดตจาก Challonge", "🏆 อัปเดตคะแนน (Excel)", "🏅 อัปเดตอันดับ & สถิติ", "👶 อัปเดตคะแนน Junior"])

# --- TAB 1: CHALLONGE ---
with tab1:
    st.header("⚡ อัปเดตจาก Challonge (Rank + Bonus)")
    st.info("💡 ระบบป้องกันการเบิ้ล: ถ้ามีชื่อคนนี้ในงานนี้อยู่แล้ว จะข้ามการให้คะแนนอันดับ")
    
    if not CHALLONGE_API_KEY:
        st.error("⚠️ ไม่พบ CHALLONGE_API_KEY")
    else:
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            challonge_id_score = st.text_input("Challonge ID", placeholder="Ex: lomyak01")
        with col_c2:
            with st.spinner("โหลดรายชื่อกิจกรรม..."):
                projects_map = get_all_projects_list()
            selected_project_name = st.selectbox("เลือกงานแข่ง (จาก Notion)", options=list(projects_map.keys()) if projects_map else [])

        if st.button("🚀 ประมวลผลและบันทึก", type="primary"):
            if not challonge_id_score or not selected_project_name:
                st.error("กรุณากรอกข้อมูลให้ครบถ้วน")
            else:
                proj_data = projects_map.get(selected_project_name)
                project_id = proj_data['id']
                is_minor = "งานย่อย" in str(proj_data['type'])
                
                status_box = st.empty()
                status_box.info("1/4 📥 ดึงข้อมูล Challonge...")
                chal_data, err = get_challonge_full_data(challonge_id_score, CHALLONGE_API_KEY)
                
                if err: st.error(err)
                elif not chal_data['participants']: st.warning("ไม่พบข้อมูลผู้แข่งขัน")
                else:
                    status_box.info("2/4 👥 ดึงข้อมูลสมาชิก Notion...")
                    fetch_all_members_data.clear()
                    all_members = fetch_all_members_data()
                    
                    rank_logs = []
                    gk_logs = []
                    
                    status_box.info("3/4 🧮 คำนวณคะแนนอันดับ...")
                    rank_prog = st.progress(0)
                    total_p = len(chal_data['participants'])
                    rank_success = 0
                    
                    p_items = list(chal_data['participants'].items())
                    for i, (p_id, p_info) in enumerate(p_items):
                        if p_info['final_rank']:
                            found_name, found_data = find_member_smart(p_info['name'], all_members)
                            if found_data:
                                # ใช้ HISTORY_DB_ID (Rank ปกติ)
                                if check_history_exists(found_data['id'], project_id, HISTORY_DB_ID, is_bonus=False):
                                    rank_logs.append(f"⚠️ {found_data['name']} มีคะแนนงานนี้แล้ว (ข้าม)")
                                else:
                                    score = calculate_score(p_info['final_rank'], is_minor)
                                    create_history_record(project_id, found_data['id'], score, selected_project_name, HISTORY_DB_ID)
                                    rank_logs.append(f"✅ {p_info['name']} (ที่ {p_info['final_rank']}) -> +{score}")
                                    rank_success += 1
                        rank_prog.progress((i + 1) / total_p)
                    
                    status_box.info("4/4 👹 เช็คโบนัสล้มยักษ์...")
                    gk_prog = st.progress(0)
                    total_m = len(chal_data['matches'])
                    gk_success = 0
                    
                    for i, m in enumerate(chal_data['matches']):
                        raw_win = chal_data['participants'][m['winner_id']]['name']
                        raw_lose = chal_data['participants'][m['loser_id']]['name']
                        w_name, w_data = find_member_smart(raw_win, all_members)
                        l_name, l_data = find_member_smart(raw_lose, all_members)
                        
                        if w_data and l_data:
                            if w_data['score'] <= 99 and l_data['score'] >= 100:
                                rec_name = f"Bonus: ล้มยักษ์ (ชนะ {l_name})"
                                create_history_record(project_id, w_data['id'], 5, rec_name, HISTORY_DB_ID)
                                gk_logs.append(f"🔥 {w_name} ({w_data['score']}) ชนะ {l_name} ({l_data['score']}) -> +5")
                                gk_success += 1
                        gk_prog.progress((i + 1) / total_m)
                    
                    status_box.empty()
                    st.success("🎉 ทำรายการเสร็จสิ้น!")
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown(f"### 🏆 คะแนนอันดับ (เพิ่มใหม่ {rank_success} คน)")
                        with st.container(height=200):
                            for l in rank_logs: st.caption(l)
                    with c2:
                        st.markdown(f"### 👹 โบนัสล้มยักษ์ ({gk_success} คู่)")
                        with st.container(height=200):
                            if gk_logs:
                                for l in gk_logs: st.caption(l)
                            else: st.info("ไม่พบการล้มยักษ์")

# --- TAB 2: EXCEL ---
with tab2:
    st.header("📥 นำเข้าคะแนนจาก Excel")
    st.info("💡 ระบบป้องกันการเบิ้ล: จะเช็คว่าคนนี้เคยได้คะแนนในงานนี้หรือยัง ก่อนบันทึก")
    uploaded_file = st.file_uploader("เลือกไฟล์ Excel (.xlsx)", type=['xlsx'])
    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file, header=None)
            project_name_raw = df.iloc[0, 0]
            st.info(f"📍 งานแข่ง: **{project_name_raw}**")
            
            if st.button("🚀 เริ่มคำนวณ", key="btn_excel"):
                status_box = st.empty()
                status_box.text("กำลังโหลดรายชื่อสมาชิก Notion ทั้งหมด...")
                fetch_all_members_data.clear() 
                all_members = fetch_all_members_data()
                if not all_members: st.error("❌ ไม่สามารถดึงรายชื่อสมาชิก"); st.stop()
                
                project_info = get_project_info(project_name_raw)
                if not project_info: st.error(f"❌ ไม่พบงานแข่ง '{project_name_raw}'")
                else:
                    project_id = project_info['id']
                    is_minor = "งานย่อย" in str(project_info['type'])
                    data_rows = df.iloc[1:]
                    total = len(data_rows)
                    count_success = 0
                    count_skip = 0
                    progress_bar = st.progress(0)
                    
                    for i, (index, row) in enumerate(data_rows.iterrows()):
                        raw_name = str(row[0]) 
                        if pd.isna(row[0]): continue
                        found_name, found_data = find_member_smart(raw_name, all_members)
                        
                        status_msg = f"({i+1}/{total}): {raw_name}"
                        if found_data:
                            # ใช้ HISTORY_DB_ID (Rank ปกติ)
                            if check_history_exists(found_data['id'], project_id, HISTORY_DB_ID):
                                status_msg += " ⚠️ มีคะแนนแล้ว (ข้าม)"
                                count_skip += 1
                            else:
                                score = calculate_score(index, is_minor)
                                create_history_record(project_id, found_data['id'], score, project_name_raw, HISTORY_DB_ID)
                                status_msg += f" ✅ บันทึก +{score}"
                                count_success += 1
                        else:
                            status_msg += " ❌ ไม่พบชื่อในระบบ"
                        
                        status_box.text(status_msg)
                        progress_bar.progress((i + 1) / total)
                        
                    status_box.empty()
                    st.success(f"🎉 เสร็จสิ้น! บันทึกใหม่ {count_success} | ข้าม (มีแล้ว) {count_skip}")
        except Exception as e: st.error(traceback.format_exc())

# --- TAB 3: UPDATE RANK & STATS (เหมือนเดิม) ---
with tab3:
    st.header("🏅 อัปเดตอันดับ & สถิติ SS2")
    st.write("1. เรียงลำดับ Rank (คะแนนมาก->น้อย, ชื่อ ก->ฮ)")
    st.write("2. คำนวณสถิติการเข้าร่วม (เฉพาะงานหลักในช่วง 1 ม.ค. - 31 มี.ค. 26)")
    if st.button("🔄 คำนวณและอัปเดตทั้งหมด"):
        fetch_all_members_data.clear() 
        status_rank = st.empty()
        status_rank.info("⏳ กำลังดึงข้อมูลสมาชิก...")
        all_members = fetch_all_members_data() 
        total_members = len(all_members)
        if total_members == 0: st.error("❌ ไม่พบข้อมูลสมาชิก")
        else:
            status_rank.info("⏳ กำลังดึงและคำนวณประวัติการเข้าร่วมงาน...")
            total_season_events, attendance_map = get_season2_stats_data()
            
            all_members.sort(key=lambda x: (-x['score'], x['name']))
            
            status_rank.info(f"✅ ข้อมูลพร้อม! งานหลัก SS2 ทั้งหมด: {total_season_events} งาน | เริ่มอัปเดตสมาชิก {total_members} คน...")
            progress_rank = st.progress(0)
            success_count = 0
            for i, member in enumerate(all_members):
                rank = i + 1; rank_str = f"{rank}/{total_members}" 
                attended_count = len(attendance_map.get(member['id'], set()))
                stats_str = f"{attended_count}/{total_season_events}"
                
                status_rank.text(f"Updating ({rank}/{total_members}): {member['name']} | Score: {member['score']} | Rank: {rank_str}")
                
                if update_rank_and_stats_to_notion(member['id'], rank_str, stats_str): success_count += 1
                progress_rank.progress((i + 1) / total_members)
                time.sleep(0.05) 
            status_rank.empty()
            st.success(f"🎉 อัปเดตเสร็จสิ้น! สำเร็จ {success_count}/{total_members} คน")

# --- 🔥 NEW TAB 4: JUNIOR UPDATE ---
with tab4:
    st.header("👶 อัปเดตคะแนน Junior (Excel)")
    
    if JUNIOR_HISTORY_DB_ID == "REPLACE_WITH_JUNIOR_DB_ID":
        st.error("🚨 กรุณาใส่ ID ของ Database 'สถิติการลง Rank Junior ทั้งหมด' ในโค้ดก่อนใช้งาน")
    else:
        st.info("💡 หมายเหตุ: คะแนนจะถูกบันทึกลงในตาราง 'สถิติการลง Rank Junior ทั้งหมด'")
        uploaded_file_jr = st.file_uploader("เลือกไฟล์ Excel Junior (.xlsx)", type=['xlsx'], key="jr_file")
        
        if uploaded_file_jr is not None:
            try:
                df = pd.read_excel(uploaded_file_jr, header=None)
                project_name_raw = df.iloc[0, 0]
                st.info(f"📍 งานแข่ง (Junior): **{project_name_raw}**")
                
                if st.button("🚀 เริ่มคำนวณ (Junior)", key="btn_jr"):
                    status_box = st.empty()
                    status_box.text("กำลังโหลดรายชื่อสมาชิก Notion ทั้งหมด...")
                    fetch_all_members_data.clear() 
                    all_members = fetch_all_members_data()
                    if not all_members: st.error("❌ ไม่สามารถดึงรายชื่อสมาชิก"); st.stop()
                    
                    project_info = get_project_info(project_name_raw)
                    if not project_info: st.error(f"❌ ไม่พบงานแข่ง '{project_name_raw}'")
                    else:
                        project_id = project_info['id']
                        is_minor = "งานย่อย" in str(project_info['type'])
                        data_rows = df.iloc[1:]
                        total = len(data_rows)
                        count_success = 0
                        count_skip = 0
                        progress_bar = st.progress(0)
                        
                        for i, (index, row) in enumerate(data_rows.iterrows()):
                            raw_name = str(row[0]) 
                            if pd.isna(row[0]): continue
                            found_name, found_data = find_member_smart(raw_name, all_members)
                            
                            status_msg = f"({i+1}/{total}): {raw_name}"
                            if found_data:
                                # 🔥 เช็คซ้ำใน JUNIOR DB
                                if check_history_exists(found_data['id'], project_id, JUNIOR_HISTORY_DB_ID):
                                    status_msg += " ⚠️ มีคะแนน Junior งานนี้แล้ว (ข้าม)"
                                    count_skip += 1
                                else:
                                    score = calculate_score(index, is_minor)
                                    # 🔥 บันทึกลง JUNIOR DB
                                    create_history_record(project_id, found_data['id'], score, project_name_raw, JUNIOR_HISTORY_DB_ID)
                                    status_msg += f" ✅ บันทึก Junior +{score}"
                                    count_success += 1
                            else:
                                status_msg += " ❌ ไม่พบชื่อในระบบ"
                            
                            status_box.text(status_msg)
                            progress_bar.progress((i + 1) / total)
                            
                        status_box.empty()
                        st.success(f"🎉 เสร็จสิ้น! บันทึก Junior ใหม่ {count_success} | ข้าม (มีแล้ว) {count_skip}")
            except Exception as e: st.error(traceback.format_exc())
