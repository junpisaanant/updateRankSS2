import streamlit as st
import pandas as pd
import requests
import time
import traceback
import math

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

# ================= HELPER FUNCTIONS: NOTION & MATCHING =================

@st.cache_data(ttl=300) # ช่วยจำข้อมูลไว้ 5 นาที จะได้ไม่ต้องโหลดใหม่ทุกครั้ง
def fetch_all_members_data():
    """ดึงข้อมูลสมาชิกทุกคน (ID, ชื่อ, คะแนน) มาเตรียมไว้สำหรับการค้นหา"""
    url = f"https://api.notion.com/v1/databases/{MEMBER_DB_ID}/query"
    members = {}
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
                    # 1. ดึงชื่อ
                    name_prop = page["properties"]["ชื่อ"]["title"]
                    if not name_prop: continue
                    name = name_prop[0]["text"]["content"].strip()
                    
                    # 2. ดึงคะแนน (รองรับ Number, Rollup, Formula)
                    score = 0
                    score_prop = page["properties"].get("คะแนนรวม SS2")
                    if score_prop:
                        if score_prop['type'] == 'number':
                            score = score_prop['number'] or 0
                        elif score_prop['type'] == 'rollup':
                            score = score_prop['rollup'].get('number', 0) or 0
                        elif score_prop['type'] == 'formula':
                            score = score_prop['formula'].get('number', 0) or 0
                    
                    members[name] = {"id": page["id"], "score": score}
                except: continue
                    
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
        except: break
        
    return members

def find_member_smart(raw_text, members_dict):
    """
    🔍 ระบบค้นหาอัจฉริยะ:
    เช็คว่า 'ชื่อใน Notion' คนไหน ไปปรากฏอยู่ใน 'ข้อความดิบ' บ้าง
    เช่น raw_text = "O-015 LovelyToonZ-1F" -> เจอ "LovelyToonZ" -> จบ
    """
    if not isinstance(raw_text, str): return None, None
    
    # เรียงชื่อจากยาวไปสั้น (ป้องกันกรณีเจอชื่อสั้นๆ ก่อน เช่น 'Toon' ใน 'LovelyToonZ')
    sorted_names = sorted(members_dict.keys(), key=len, reverse=True)
    
    for name in sorted_names:
        if name in raw_text: # ถ้าเจอชื่อนี้อยู่ในข้อความดิบ
            return name, members_dict[name]
            
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

# ================= HELPER FUNCTIONS: CHALLONGE =================

def get_challonge_data(tournament_id, api_key):
    custom_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    YOUR_USERNAME = "junpisa@gmail.com" # <--- อีเมลของคุณ
    
    try:
        # 1. Participants
        p_url = f"https://api.challonge.com/v1/tournaments/{tournament_id}/participants.json"
        p_res = requests.get(p_url, headers=custom_headers, auth=(YOUR_USERNAME, api_key))
        if p_res.status_code != 200: return None, f"Error Participants: {p_res.text}"
        
        participants = {}
        for p in p_res.json():
            p_data = p['participant']
            participants[p_data['id']] = p_data['name'] # เก็บชื่อดิบๆ ไว้ (เช่น O-015 LovelyToonZ...)

        # 2. Matches
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

tab1, tab2 = st.tabs(["🏆 อัปเดตคะแนน (Excel)", "👹 เช็คล้มยักษ์ (Challonge)"])

# --- TAB 1: EXCEL UPDATE ---
with tab1:
    st.header("📥 นำเข้าคะแนนจาก Excel")
    st.write("ระบบคำนวณคะแนนอัตโนมัติตามลำดับใน Excel")
    st.write("บรรทัดแรกสุด(ชื่องานแข่ง)ให้เอาจาก>> https://auspicious-tarsier-51c.notion.site/26fe6d24b97d80e1bdb3c2452a31694c?v=26fe6d24b97d813a9d8f000c8ed5dc7b&source=copy_link")
    st.write("ตัวอย่าง Template ให้เอาจาก>> https://docs.google.com/spreadsheets/d/1DPklisqF-ykQtKgg2h2AH-Q5ePN30zr1lNm9EaRjvg4/edit?gid=0#gid=0")
    uploaded_file = st.file_uploader("เลือกไฟล์ Excel (.xlsx)", type=['xlsx'])

    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file, header=None)
            project_name_raw = df.iloc[0, 0]
            st.info(f"📍 งานแข่ง: **{project_name_raw}**")
            
            if st.button("🚀 เริ่มคำนวณ", key="btn_excel"):
                status_box = st.empty()
                status_box.text("กำลังโหลดรายชื่อสมาชิก Notion ทั้งหมด...")
                
                # 1. โหลดสมาชิกทั้งหมดมารอไว้ก่อน (ทีเดียวจบ)
                all_members = fetch_all_members_data()
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
                        raw_name = str(row[0]) # ชื่อใน Excel (เช่น O-015 LovelyToonZ...)
                        if pd.isna(row[0]): continue
                        
                        # ใช้ระบบค้นหาแบบใหม่
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
        except Exception as e:
            st.error(traceback.format_exc())

# --- TAB 2: GIANT KILLING ---
with tab2:
    st.header("👹 ระบบเช็คการล้มยักษ์ (Bonus +5)")
    if not CHALLONGE_API_KEY:
        st.error("⚠️ ไม่พบ CHALLONGE_API_KEY ใน secrets.toml")
    else:
        challonge_id = st.text_input("Challonge ID", placeholder="testUpdateRank")
        target_project_name = st.text_input("ชื่องานแข่ง (Notion)", placeholder="Lomyak Tournament #1")

        if st.button("🔍 ตรวจสอบ"):
            with st.spinner("กำลังดึงข้อมูล..."):
                all_members = fetch_all_members_data() # ใช้ฟังก์ชันเดียวกันเลย
                proj_info = get_project_info(target_project_name)
                
                if not all_members or not proj_info:
                    st.error("ข้อมูลไม่พร้อม (เช็ค Notion หรือ อินเทอร์เน็ต)")
                    st.stop()
                    
                chal_data, err = get_challonge_data(challonge_id, CHALLONGE_API_KEY)
                if err:
                    st.error(err)
                    st.stop()
                
                giant_killings = []
                
                for m in chal_data['matches']:
                    # ชื่อดิบๆ จาก Challonge (เช่น O-015 LovelyToonZ...)
                    raw_win = chal_data['participants'].get(m['winner_id'])
                    raw_lose = chal_data['participants'].get(m['loser_id'])
                    
                    # ใช้ระบบค้นหาแบบใหม่ Match ชื่อ Notion ออกมา
                    w_name, w_data = find_member_smart(raw_win, all_members)
                    l_name, l_data = find_member_smart(raw_lose, all_members)
                    
                    if w_data and l_data:
                        # 🔥 เงื่อนไขล้มยักษ์ (ใช้คะแนนที่ดึงมาอย่างถูกต้อง)
                        if w_data['score'] <= 99 and l_data['score'] >= 100:
                            giant_killings.append({
                                "winner": w_name, "winner_id": w_data['id'],
                                "loser": l_name, "w_score": w_data['score'], "l_score": l_data['score']
                            })

                if not giant_killings:
                    st.info("ไม่พบการล้มยักษ์")
                else:
                    st.success(f"🔥 เจอ {len(giant_killings)} คู่!")
                    st.table(pd.DataFrame(giant_killings)[['winner', 'w_score', 'loser', 'l_score']])
                    st.session_state['gk_data'] = giant_killings
                    st.session_state['gk_proj_id'] = proj_info['id']

        if 'gk_data' in st.session_state:
            if st.button("✅ ยืนยันแจกโบนัส"):
                count = 0
                prog = st.progress(0)
                items = st.session_state['gk_data']
                for i, item in enumerate(items):
                    rec_name = f"Bonus: ล้มยักษ์ (ชนะ {item['loser']})"
                    create_history_record(st.session_state['gk_proj_id'], item['winner_id'], 5, rec_name)
                    count += 1
                    prog.progress((i+1)/len(items))
                    time.sleep(0.1)
                st.success(f"เรียบร้อย {count} รายการ")
                del st.session_state['gk_data']

