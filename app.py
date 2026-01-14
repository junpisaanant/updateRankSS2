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

def calculate_score(row_index, is_minor_event):
    score = 0
    if row_index == 1: score = 25
    elif row_index == 2: score = 20
    elif 3 <= row_index <= 4: score = 16
    elif 5 <= row_index <= 8: score = 10
    elif 9 <= row_index <= 16: score = 5
    else: score = 2
    if is_minor_event and row_index <= 15: score = math.ceil(score / 2)
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

# 🔥 แก้ไขฟังก์ชันนี้ (ป้องกัน Error: NoneType)
def get_season2_stats_data():
    """
    1. หางานทั้งหมดในช่วง SS2 (1 ม.ค. - 31 มี.ค. 2026) ที่ไม่ใช่งานย่อย
    2. ดึงประวัติการเข้าร่วมทั้งหมดมา map ไว้
    """
    # 1. หางานเป้าหมาย (Main Events)
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
            # เช็คประเภท
            event_type = "ทั่วไป"
            if 'ประเภทงาน' in props:
                pt = props['ประเภทงาน']
                if pt['type'] == 'select' and pt['select']: event_type = pt['select']['name']
                elif pt['type'] == 'multi_select' and pt['multi_select']: event_type = pt['multi_select'][0]['name']
            
            # เช็ควันที่ (แก้ตรงนี้ให้ปลอดภัยขึ้น)
            event_date_str = None
            date_prop = props.get("วันที่จัดกิจกรรม") or props.get("วันที่จัดงาน")
            if date_prop: 
                # ✅ ใช้ .get("date") แล้วเช็คว่ามีค่าไหม ก่อนจะ .get("start")
                date_obj = date_prop.get("date")
                if date_obj:
                    event_date_str = date_obj.get("start")
            
            if event_date_str:
                try:
                    e_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
                    # เงื่อนไข: อยู่ในช่วงเวลา และ ไม่ใช่งานย่อย
                    if target_start <= e_date <= target_end and "งานย่อย" not in str(event_type):
                        target_event_ids.add(page['id'])
                except: pass
        
        has_more = res.get("has_more", False)
        next_cursor = res.get("next_cursor")
    
    # 2. ดึงประวัติ (History)
    attendance_map = {} # { member_id: set(event_ids) }
    
    h_url = f"https://api.notion.com/v1/databases/{HISTORY_DB_ID}/query"
    has_more = True; next_cursor = None
    
    while has_more:
        payload = {}
        if next_cursor: payload["start_cursor"] = next_cursor
        h_res = requests.post(h_url, json=payload, headers=headers).json()
        
        for page in h_res.get("results", []):
            props = page.get("properties", {})
            
            # ดึง Member ID
            mem_rels = props.get("สมาชิกแรงค์", {}).get("relation", [])
            if not mem_rels: continue
            mem_id = mem_rels[0]['id']
            
            # ดึง Project ID
            proj_rels = props.get("ชื่องานแข่ง", {}).get("relation", [])
            if not proj_rels: continue
            proj_id = proj_rels[0]['id']
            
            # ถ้างานนี้เป็นงานเป้าหมาย (SS2 Main) -> นับ
            if proj_id in target_event_ids:
                if mem_id not in attendance_map: attendance_map[mem_id] = set()
                attendance_map[mem_id].add(proj_id)
        
        has_more = h_res.get("has_more", False)
        next_cursor = h_res.get("next_cursor")
        
    return len(target_event_ids), attendance_map

def update_rank_and_stats_to_notion(page_id, rank_text, stats_text):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    properties = {
        "อันดับ Rank SS2": { 
            "rich_text": [{"text": {"content": str(rank_text)}}]
        },
        "สถิติเข้าร่วม SS2": { 
            "rich_text": [{"text": {"content": str(stats_text)}}]
        }
    }
    payload = {"properties": properties}
    try:
        res = requests.patch(url, json=payload, headers=headers)
        return res.status_code == 200
    except:
        return False

# ================= HELPER FUNCTIONS: CHALLONGE =================

def get_challonge_data(tournament_id, api_key):
    custom_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    YOUR_USERNAME = "junpisa@gmail.com"
    try:
        p_url = f"https://api.challonge.com/v1/tournaments/{tournament_id}/participants.json"
        p_res = requests.get(p_url, headers=custom_headers, auth=(YOUR_USERNAME, api_key))
        if p_res.status_code != 200: return None, f"Error Participants: {p_res.text}"
        
        participants = {}
        for p in p_res.json():
            p_data = p['participant']
            participants[p_data['id']] = p_data['name']

        m_url = f"https://api.challonge.com/v1/tournaments/{tournament_id}/matches.json"
        m_res = requests.get(m_url, headers=custom_headers, auth=(YOUR_USERNAME, api_key))
        if m_res.status_code != 200: return None, f"Error Matches: {m_res.text}"
        
        matches = []
        for m in m_res.json():
            m_data = m['match']
            if m_data['state'] == 'complete' and m_data['winner_id']:
                matches.append({"winner_id": m_data['winner_id'], "loser_id": m_data['loser_id']})
        return {"participants": participants, "matches": matches}, None
    except Exception as e: return None, f"Connection Error: {str(e)}"

# ================= UI PART =================

st.set_page_config(page_title="Rank & Lomyak System", page_icon="⚔️", layout="wide")
st.title("⚔️ Rank & Giant Killing System")

tab1, tab2, tab3 = st.tabs(["🏆 อัปเดตคะแนน (Excel)", "👹 เช็คล้มยักษ์ (Challonge)", "🏅 อัปเดตอันดับ & สถิติ"])

# --- TAB 1: EXCEL UPDATE ---
with tab1:
    st.header("📥 นำเข้าคะแนนจาก Excel")
    uploaded_file = st.file_uploader("เลือกไฟล์ Excel (.xlsx)", type=['xlsx'])
    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file, header=None)
            project_name_raw = df.iloc[0, 0]
            st.info(f"📍 งานแข่ง: **{project_name_raw}**")
            
            if st.button("🚀 เริ่มคำนวณ", key="btn_excel"):
                status_box = st.empty()
                status_box.text("กำลังโหลดรายชื่อสมาชิก Notion ทั้งหมด...")
                all_members = fetch_all_members_data()
                st.write(f"จำนวนสมาชิกที่โหลดได้: {len(all_members)} คน")
                
                if not all_members:
                    st.error("❌ ไม่สามารถดึงรายชื่อสมาชิกจาก Notion ได้")
                    st.stop()
                
                project_info = get_project_info(project_name_raw)
                if not project_info:
                    st.error(f"❌ ไม่พบงานแข่ง '{project_name_raw}'")
                else:
                    project_id = project_info['id']
                    is_minor = "งานย่อย" in str(project_info['type'])
                    data_rows = df.iloc[1:]
                    total = len(data_rows)
                    count_success = 0
                    progress_bar = st.progress(0)
                    
                    for i, (index, row) in enumerate(data_rows.iterrows()):
                        raw_name = str(row[0]) 
                        if pd.isna(row[0]): continue
                        found_name, found_data = find_member_smart(raw_name, all_members)
                        status_box.text(f"กำลังทำ ({i+1}/{total}): {raw_name} -> {'✅ เจอ ' + found_name if found_name else '❌ ไม่เจอ'}")
                        if found_data:
                            score = calculate_score(index, is_minor)
                            create_history_record(project_id, found_data['id'], score, project_name_raw)
                            count_success += 1
                        progress_bar.progress((i + 1) / total)
                        time.sleep(0.05)
                    status_box.empty()
                    st.success(f"🎉 เสร็จสิ้น! บันทึก {count_success} รายการ")
        except Exception as e: st.error(traceback.format_exc())

# --- TAB 2: GIANT KILLING ---
with tab2:
    st.header("👹 ระบบเช็คการล้มยักษ์")
    if not CHALLONGE_API_KEY: st.error("⚠️ ไม่พบ API Key")
    else:
        challonge_id = st.text_input("Challonge ID", placeholder="testUpdateRank")
        target_project_name = st.text_input("ชื่องานแข่ง (Notion)", placeholder="Lomyak Tournament #1")
        if st.button("🔍 ตรวจสอบ"):
            with st.spinner("กำลังดึงข้อมูล..."):
                all_members = fetch_all_members_data()
                proj_info = get_project_info(target_project_name)
                if not all_members or not proj_info: st.error("ข้อมูลไม่พร้อม"); st.stop()
                chal_data, err = get_challonge_data(challonge_id, CHALLONGE_API_KEY)
                if err: st.error(err); st.stop()
                
                giant_killings = []
                for m in chal_data['matches']:
                    raw_win = chal_data['participants'].get(m['winner_id'])
                    raw_lose = chal_data['participants'].get(m['loser_id'])
                    w_name, w_data = find_member_smart(raw_win, all_members)
                    l_name, l_data = find_member_smart(raw_lose, all_members)
                    if w_data and l_data:
                        if w_data['score'] <= 99 and l_data['score'] >= 100:
                            giant_killings.append({ "winner": w_name, "winner_id": w_data['id'], "loser": l_name, "w_score": w_data['score'], "l_score": l_data['score'] })
                if not giant_killings: st.info("ไม่พบการล้มยักษ์")
                else:
                    st.success(f"🔥 เจอ {len(giant_killings)} คู่!")
                    st.table(pd.DataFrame(giant_killings)[['winner', 'w_score', 'loser', 'l_score']])
                    st.session_state['gk_data'] = giant_killings
                    st.session_state['gk_proj_id'] = proj_info['id']
        if 'gk_data' in st.session_state:
            if st.button("✅ ยืนยันแจกโบนัส"):
                count = 0; prog = st.progress(0); items = st.session_state['gk_data']
                for i, item in enumerate(items):
                    create_history_record(st.session_state['gk_proj_id'], item['winner_id'], 5, f"Bonus: ล้มยักษ์ (ชนะ {item['loser']})")
                    count += 1; prog.progress((i+1)/len(items)); time.sleep(0.1)
                st.success(f"เรียบร้อย {count} รายการ"); del st.session_state['gk_data']

# --- TAB 3: UPDATE RANK & STATS (CORRECTED) ---
with tab3:
    st.header("🏅 อัปเดตอันดับ & สถิติ SS2")
    st.write("1. เรียงลำดับ Rank (คะแนนมาก->น้อย, ชื่อ ก->ฮ)")
    st.write("2. คำนวณสถิติการเข้าร่วม (เฉพาะงานหลักในช่วง 1 ม.ค. - 31 มี.ค. 26)")
    
    if st.button("🔄 คำนวณและอัปเดตทั้งหมด"):
        fetch_all_members_data.clear() # Clear Cache
        status_rank = st.empty()
        
        # 1. โหลดข้อมูลสมาชิก
        status_rank.info("⏳ กำลังดึงข้อมูลสมาชิก...")
        all_members = fetch_all_members_data() 
        total_members = len(all_members)
        
        if total_members == 0:
            st.error("❌ ไม่พบข้อมูลสมาชิก")
        else:
            # 2. โหลดข้อมูลสถิติ
            status_rank.info("⏳ กำลังดึงและคำนวณประวัติการเข้าร่วมงาน (อาจใช้เวลาสักครู่)...")
            total_season_events, attendance_map = get_season2_stats_data()
            
            # 3. จัดเรียงลำดับ Rank
            all_members.sort(key=lambda x: (-x['score'], x['name']))
            
            status_rank.info(f"✅ ข้อมูลพร้อม! งานหลัก SS2 ทั้งหมด: {total_season_events} งาน | เริ่มอัปเดตสมาชิก {total_members} คน...")
            progress_rank = st.progress(0)
            success_count = 0
            
            # 4. วนลูปอัปเดต
            for i, member in enumerate(all_members):
                # คำนวณ Rank
                rank = i + 1
                rank_str = f"{rank}/{total_members}" 
                
                # คำนวณ Stats
                attended_count = len(attendance_map.get(member['id'], set()))
                stats_str = f"{attended_count}/{total_season_events}"
                
                status_rank.text(f"Updating ({rank}/{total_members}): {member['name']} | Rank: {rank_str} | Stats: {stats_str}")
                
                # บันทึกลง Notion
                if update_rank_and_stats_to_notion(member['id'], rank_str, stats_str):
                    success_count += 1
                
                progress_rank.progress((i + 1) / total_members)
                time.sleep(0.05) 
            
            status_rank.empty()
            st.success(f"🎉 อัปเดตเสร็จสิ้น! สำเร็จ {success_count}/{total_members} คน")
