import streamlit as st
import pandas as pd
import requests
import time
import traceback
import math
import re
from datetime import datetime, date

# ================= CONFIGURATION =================
try:
    NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
    CHALLONGE_API_KEY = st.secrets.get("CHALLONGE_API_KEY", "")
except FileNotFoundError:
    NOTION_TOKEN = "YOUR_TOKEN"
    CHALLONGE_API_KEY = ""

MEMBER_DB_ID = "271e6d24b97d80289175eef889a90a09" 
HISTORY_DB_ID = "2b1e6d24b97d803786c2ec7011c995ef"
PROJECT_DB_ID = "26fe6d24b97d80e1bdb3c2452a31694c" 

headers = {
    "Authorization": "Bearer " + NOTION_TOKEN,
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ================= HELPER FUNCTIONS =================

@st.cache_data(ttl=300) 
def fetch_all_members_data():
    """ดึงข้อมูลสมาชิกทุกคน (ID, ชื่อ, คะแนน) เก็บเป็น List"""
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
                    score_prop = page["properties"].get("คะแนนรวม SS2")
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

@st.cache_data(ttl=300)
def get_all_projects_list():
    url = f"https://api.notion.com/v1/databases/{PROJECT_DB_ID}/query"
    raw_items = []
    has_more = True; next_cursor = None
    
    while has_more:
        payload = { "sorts": [ { "property": "วันที่จัดกิจกรรม", "direction": "descending" } ] }
        if next_cursor: payload["start_cursor"] = next_cursor
        try:
            res = requests.post(url, json=payload, headers=headers).json()
            for page in res.get("results", []):
                try:
                    props = page.get('properties', {})
                    
                    # 1. Filter Status & Capture Meta
                    status_val = ""
                    status_prop_name = "Status" if "Status" in props else "สถานะ"
                    status_prop = props.get(status_prop_name)
                    status_type = "status"
                    
                    if status_prop:
                        status_type = status_prop['type']
                        if status_type == 'select' and status_prop['select']: 
                            status_val = status_prop['select']['name']
                        elif status_type == 'status' and status_prop['status']: 
                            status_val = status_prop['status']['name']
                    
                    if status_val == "ปิดรับสมัครแล้ว": continue

                    title = props["ชื่อกิจกรรม"]["title"][0]["text"]["content"]
                    
                    event_type = "ทั่วไป"
                    if 'ประเภทงาน' in props:
                        pt = props['ประเภทงาน']
                        if pt['type'] == 'select' and pt['select']: event_type = pt['select']['name']
                        elif pt['type'] == 'multi_select' and pt['multi_select']: event_type = pt['multi_select'][0]['name']
                    
                    raw_items.append({
                        "title": title,
                        "data": { 
                            "id": page["id"], 
                            "type": event_type,
                            "status_meta": { "name": status_prop_name, "type": status_type }
                        }
                    })
                    
                except: pass
                
            has_more = res.get("has_more", False)
            next_cursor = res.get("next_cursor")
        except: break
    
    date_prefix_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}")
    
    group_date_prefix = []
    group_others = []
    
    for item in raw_items:
        if date_prefix_pattern.match(item['title']):
            group_date_prefix.append(item)
        else:
            group_others.append(item)
            
    group_date_prefix.sort(key=lambda x: x['title'], reverse=True)
    group_others.sort(key=lambda x: x['title'], reverse=True)
    
    final_dict = {}
    for item in group_date_prefix:
        final_dict[item['title']] = item['data']
        
    for item in group_others:
        final_dict[item['title']] = item['data']
    
    return final_dict

def calculate_score(row_index, is_minor_event):
    score = 0
    if row_index == 1: score = 25
    elif row_index == 2: score = 20
    elif 3 <= row_index <= 4: score = 16
    elif 5 <= row_index <= 8: score = 10
    elif 9 <= row_index <= 16: score = 5
    else: score = 2
    if is_minor_event: score = math.ceil(score / 2)
    return score

def create_history_record(project_id, member_id, score, record_name):
    url = "https://api.notion.com/v1/pages"
    properties = {
        "Name": { "title": [{"text": {"content": str(record_name)}}] },
        "สมาชิกแรงค์": { "relation": [{"id": member_id}] },
        "ชื่องานแข่ง": { "relation": [{"id": project_id}] },
        "คะแนนที่บวก": { "number": float(score) }
    }
    payload = {"parent": {"database_id": HISTORY_DB_ID}, "properties": properties}
    requests.post(url, json=payload, headers=headers)
    return True

def update_project_status(page_id, prop_name, prop_type, new_status):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    prop_data = { "name": new_status }
    if prop_type == "select":
        payload = { "properties": { prop_name: { "select": prop_data } } }
    else:
        payload = { "properties": { prop_name: { "status": prop_data } } }
    try:
        res = requests.patch(url, json=payload, headers=headers)
        return res.status_code == 200
    except: return False

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

tab1, tab2 = st.tabs(["⚡ อัปเดตจาก Challonge", "🏅 อัปเดตอันดับ & สถิติ"])

# --- TAB 1: CHALLONGE SCORE & GIANT KILLING ---
with tab1:
    st.header("⚡ อัปเดตจาก Challonge (Rank + Bonus)")
    st.write("1. ให้คะแนนตามอันดับ และผู้เข้าร่วมทุกคน (งานย่อยแต้มหารครึ่ง)")
    st.write("2. เช็คการล้มยักษ์ (Bonus +5 / งานย่อย +3)")
    st.write("3. **ปิดรับสมัคร** งานแข่งให้อัตโนมัติ")
    
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

        if st.button("🚀 ประมวลผลและปิดงาน", type="primary"):
            if not challonge_id_score or not selected_project_name:
                st.error("กรุณากรอกข้อมูลให้ครบถ้วน")
            else:
                proj_data = projects_map.get(selected_project_name)
                project_id = proj_data['id']
                is_minor = "งานย่อย" in str(proj_data['type'])
                status_meta = proj_data.get('status_meta', {'name': 'Status', 'type': 'status'})
                
                status_box = st.empty()
                status_box.info("1/5 📥 ดึงข้อมูล Challonge...")
                chal_data, err = get_challonge_full_data(challonge_id_score, CHALLONGE_API_KEY)
                
                if err: st.error(err)
                elif not chal_data['participants']: st.warning("ไม่พบข้อมูลผู้แข่งขัน")
                else:
                    status_box.info("2/5 👥 ดึงข้อมูลสมาชิก Notion...")
                    all_members = fetch_all_members_data()
                    
                    rank_logs = []
                    gk_logs = []
                    
                    # --- Phase 3: Rank Score ---
                    status_box.info("3/5 🧮 คำนวณคะแนนอันดับ...")
                    rank_prog = st.progress(0)
                    total_p = len(chal_data['participants'])
                    rank_success = 0
                    
                    p_items = list(chal_data['participants'].items())
                    for i, (p_id, p_info) in enumerate(p_items):
                        if p_info['final_rank']:
                            found_name, found_data = find_member_smart(p_info['name'], all_members)
                            if found_data:
                                score = calculate_score(p_info['final_rank'], is_minor)
                                create_history_record(project_id, found_data['id'], score, selected_project_name)
                                rank_logs.append(f"✅ {p_info['name']} (ที่ {p_info['final_rank']}) -> +{score}")
                                rank_success += 1
                        rank_prog.progress((i + 1) / total_p)
                        time.sleep(0.02)
                        
                    # --- Phase 4: Giant Killing ---
                    status_box.info("4/5 👹 เช็คโบนัสล้มยักษ์...")
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
                                # 🔥 Logic ใหม่: งานย่อยหารครึ่ง (5 -> 3)
                                bonus = 5
                                if is_minor: bonus = math.ceil(5 / 2)
                                
                                rec_name = f"Bonus: ล้มยักษ์ (ชนะ {l_name})"
                                create_history_record(project_id, w_data['id'], bonus, rec_name)
                                gk_logs.append(f"🔥 {w_name} ({w_data['score']}) ชนะ {l_name} ({l_data['score']}) -> +{bonus}")
                                gk_success += 1
                        gk_prog.progress((i + 1) / total_m)
                        time.sleep(0.02)
                    
                    # --- Phase 5: Close Project ---
                    status_box.info(f"5/5 🔒 ปิดรับสมัครงาน: {selected_project_name} ...")
                    if update_project_status(project_id, status_meta['name'], status_meta['type'], "ปิดรับสมัครแล้ว"):
                        st.toast(f"🔒 ปิดงาน '{selected_project_name}' แล้ว!", icon="✅")
                        get_all_projects_list.clear()
                    else:
                        st.error("❌ อัปเดตสถานะงานไม่สำเร็จ")

                    status_box.empty()
                    st.success("🎉 ทำรายการเสร็จสิ้น!")
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown(f"### 🏆 คะแนนอันดับ ({rank_success} คน)")
                        with st.container(height=200):
                            for l in rank_logs: st.caption(l)
                    with c2:
                        st.markdown(f"### 👹 โบนัสล้มยักษ์ ({gk_success} คู่)")
                        with st.container(height=200):
                            if gk_logs:
                                for l in gk_logs: st.caption(l)
                            else: st.info("ไม่พบการล้มยักษ์")

# --- TAB 2: UPDATE RANK & STATS ---
with tab2:
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
                status_rank.text(f"Updating ({rank}/{total_members}): {member['name']} | Rank: {rank_str} | Stats: {stats_str}")
                if update_rank_and_stats_to_notion(member['id'], rank_str, stats_str): success_count += 1
                progress_rank.progress((i + 1) / total_members)
                time.sleep(0.05) 
            status_rank.empty()
            st.success(f"🎉 อัปเดตเสร็จสิ้น! สำเร็จ {success_count}/{total_members} คน")
