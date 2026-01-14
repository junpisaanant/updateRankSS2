import streamlit as st
import pandas as pd
import requests
import time
import traceback
import math

# ================= CONFIGURATION =================
try:
    NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
    # ดึง Challonge Key จาก Secrets (ถ้าไม่มีให้เป็นค่าว่าง)
    CHALLONGE_API_KEY = st.secrets.get("CHALLONGE_API_KEY", "")
except FileNotFoundError:
    # กรณีรันในเครื่องแล้วลืมสร้าง secrets.toml
    NOTION_TOKEN = "YOUR_NOTION_TOKEN"
    CHALLONGE_API_KEY = "YOUR_CHALLONGE_KEY"

MEMBER_DB_ID = "271e6d24b97d80289175eef889a90a09" 
HISTORY_DB_ID = "2b1e6d24b97d803786c2ec7011c995ef"
PROJECT_DB_ID = "26fe6d24b97d80e1bdb3c2452a31694c" 

headers = {
    "Authorization": "Bearer " + NOTION_TOKEN,
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ================= HELPER FUNCTIONS: NOTION =================

def get_member_id(raw_name):
    if not isinstance(raw_name, str): return None
    clean_name = raw_name.split('-')[0].strip()
    url = f"https://api.notion.com/v1/databases/{MEMBER_DB_ID}/query"
    payload = {"filter": {"property": "ชื่อ", "title": {"contains": clean_name}}}
    try:
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        if data.get('results'): return data['results'][0]['id']
        return None
    except: return None

def get_project_info(project_name):
    url = f"https://api.notion.com/v1/databases/{PROJECT_DB_ID}/query"
    search_term = str(project_name).strip()
    payload = {"filter": {"property": "ชื่อกิจกรรม", "title": {"contains": search_term}}}
    try:
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        if data.get('results'):
            page = data['results'][0]
            project_id = page['id']
            event_type = "ทั่วไป"
            props = page.get('properties', {})
            if 'ประเภทงาน' in props:
                prop_data = props['ประเภทงาน']
                if prop_data['type'] == 'select' and prop_data['select']:
                    event_type = prop_data['select']['name']
                elif prop_data['type'] == 'multi_select' and prop_data['multi_select']:
                    event_type = prop_data['multi_select'][0]['name']
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
    if is_minor_event and row_index <= 15:
        score = math.ceil(score / 2)
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
    response = requests.post(url, json=payload, headers=headers)
    return response.status_code == 200

# ================= HELPER FUNCTIONS: CHALLONGE & GIANT KILLING =================

def fetch_all_members_scores():
    """ดึงข้อมูลสมาชิกทุกคนและคะแนนปัจจุบัน"""
    url = f"https://api.notion.com/v1/databases/{MEMBER_DB_ID}/query"
    members = {}
    has_more = True
    next_cursor = None
    
    while has_more:
        payload = {}
        if next_cursor: payload["start_cursor"] = next_cursor
        
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        
        for page in data.get("results", []):
            try:
                name_prop = page["properties"]["ชื่อ"]["title"]
                if not name_prop: continue
                name = name_prop[0]["text"]["content"].strip()
                
                score = 0
                # เช็คชื่อ Column 'คะแนน Rank SS2' ให้ตรง Notion
                score_prop = page["properties"].get("คะแนน Rank SS2") 
                
                if score_prop:
                    if score_prop['type'] == 'number':
                        score = score_prop['number'] or 0
                    elif score_prop['type'] == 'rollup':
                         score = score_prop['rollup'].get('number', 0) or 0
                
                members[name] = {"id": page["id"], "score": score}
            except Exception: continue
                
        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")
        
    return members

def get_challonge_data(tournament_id, api_key):
    """ดึงข้อมูล Match และ Participants จาก Challonge"""
    
    # 1. ✅ ประกาศตัวแปรนี้ก่อนเรียกใช้ (แก้ Error: name not defined)
    custom_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    # 2. ⚠️ ใส่ Username ของคุณตรงนี้ (เพื่อแก้ Error 401)
    # จากข้อมูลที่คุณเคยบอก ชื่อเล่นออนไลน์คือ LovelyToonZ ลองใช้ชื่อนี้ดูก่อนนะคะ
    # ถ้ายังไม่ได้ ให้ลองเปลี่ยนเป็น Email ที่ใช้ล็อกอิน Challonge
    YOUR_USERNAME = "junpisa@gmail.com" 
    
    # URL (ไม่ต้องใส่ api_key ในนี้แล้ว เราจะส่งแบบ Auth แทน)
    p_url = f"https://api.challonge.com/v1/tournaments/{tournament_id}/participants.json"
    
    try:
        # 3. ยิง Request แบบใส่ Username + API Key (Basic Auth)
        # วิธีนี้ชัวร์กว่าสำหรับบัญชีแบบ Migrated
        p_res = requests.get(p_url, headers=custom_headers, auth=(YOUR_USERNAME, api_key))
        
        if p_res.status_code != 200:
            # debug: ปริ้นท์ข้อความ error จาก challonge ออกมาดูเลย
            return None, f"Error Participants ({p_res.status_code}): {p_res.text}"
        
        participants = {}
        for p in p_res.json():
            p_data = p['participant']
            participants[p_data['id']] = p_data['name'] 

        # --- ดึง Matches ---
        m_url = f"https://api.challonge.com/v1/tournaments/{tournament_id}/matches.json"
        
        # ส่ง auth ชุดเดิม
        m_res = requests.get(m_url, headers=custom_headers, auth=(YOUR_USERNAME, api_key))
        
        if m_res.status_code != 200: 
            return None, f"Error Matches ({m_res.status_code}): {m_res.text}"
        
        matches = []
        for m in m_res.json():
            m_data = m['match']
            if m_data['state'] == 'complete' and m_data['winner_id']:
                matches.append({
                    "winner_id": m_data['winner_id'],
                    "loser_id": m_data['loser_id']
                })
                
        return {"participants": participants, "matches": matches}, None

    except Exception as e:
        return None, f"Connection Error: {str(e)}"

# ================= UI PART =================

st.set_page_config(page_title="Rank & Lomyak System", page_icon="⚔️", layout="wide")
st.title("⚔️ Rank & Giant Killing System")

tab1, tab2 = st.tabs(["🏆 อัปเดตคะแนน (Excel)", "👹 เช็คล้มยักษ์ (Challonge)"])

# --- TAB 1: EXCEL UPDATE ---
with tab1:
    st.header("📥 นำเข้าคะแนนจาก Excel")
    uploaded_file = st.file_uploader("เลือกไฟล์ Excel (.xlsx)", type=['xlsx'])

    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file, header=None)
            st.dataframe(df.head(5))
            project_name_raw = df.iloc[0, 0]
            st.info(f"📍 งานแข่ง: **{project_name_raw}**")
            
            if st.button("🚀 เริ่มคำนวณ", key="btn_excel"):
                status_box = st.empty()
                project_info = get_project_info(project_name_raw)
                
                if not project_info:
                    st.error(f"❌ ไม่พบงานแข่ง '{project_name_raw}'")
                else:
                    project_id = project_info['id']
                    event_type = project_info['type']
                    is_minor = "งานย่อย" in str(event_type)
                    
                    data_rows = df.iloc[1:]
                    total_rows = len(data_rows)
                    count_success = 0
                    progress_bar = st.progress(0)
                    
                    for i, (index, row) in enumerate(data_rows.iterrows()):
                        raw_name = row[0]
                        if pd.isna(raw_name): continue
                        clean_name = str(raw_name).split('-')[0].strip()
                        calculated_score = calculate_score(index, is_minor)
                        
                        member_id = get_member_id(raw_name)
                        if member_id:
                            if create_history_record(project_id, member_id, calculated_score, project_name_raw):
                                count_success += 1
                        
                        progress_bar.progress((i + 1) / total_rows)
                        time.sleep(0.05)
                        
                    st.success(f"🎉 เสร็จสิ้น! บันทึก {count_success} รายการ")
        except Exception as e:
            st.error(traceback.format_exc())

# --- TAB 2: GIANT KILLING (LOMYAK) ---
with tab2:
    st.header("👹 ระบบเช็คการล้มยักษ์ (Bonus +5)")
    st.markdown("""
    **เงื่อนไข:**
    * 🛡️ **ผู้ท้าชิง:** คะแนนปัจจุบัน ≤ 99
    * 👹 **ยักษ์:** คะแนนปัจจุบัน ≥ 100
    * ถ้า **ผู้ท้าชิง** ชนะ **ยักษ์** ได้รับโบนัส **+5 คะแนน**
    """)
    
    # ⚠️ ตรวจสอบว่ามี Key หรือยัง
    if not CHALLONGE_API_KEY:
        st.error("⚠️ ไม่พบ CHALLONGE_API_KEY ใน secrets.toml กรุณาเพิ่มก่อนใช้งาน")
        st.stop()
    else:
        st.caption("✅ เชื่อมต่อ Challonge API แล้ว (จาก secrets.toml)")

    # เหลือแค่ช่องกรอก ID งานแข่งอย่างเดียว (โล่งขึ้นเยอะ!)
    challonge_id = st.text_input("Challonge Tournament ID / URL", placeholder="เช่น testUpdateRank")
    target_project_name = st.text_input("ชื่องานแข่งที่จะบันทึก (ต้องตรงกับใน Notion)", placeholder="เช่น Lomyak Tournament #1")

    if st.button("🔍 ตรวจสอบการล้มยักษ์"):
        if not challonge_id or not target_project_name:
            st.error("กรุณากรอกข้อมูลให้ครบทุกช่อง")
        else:
            with st.spinner("กำลังดึงข้อมูล Notion และ Challonge..."):
                # 1. หา Project ID ใน Notion ก่อน
                proj_info = get_project_info(target_project_name)
                if not proj_info:
                    st.error(f"❌ ไม่พบงานแข่ง '{target_project_name}' ใน Notion")
                    st.stop()
                
                project_id_notion = proj_info['id']

                # 2. ดึงข้อมูลสมาชิกและคะแนนจาก Notion
                notion_members = fetch_all_members_scores()
                if not notion_members:
                    st.error("ไม่สามารถดึงข้อมูลสมาชิกจาก Notion ได้")
                    st.stop()
                    
                # 3. ดึงข้อมูล Match จาก Challonge (ใช้ Key จาก Secrets)
                chal_data, err = get_challonge_data(challonge_id.split('/')[-1], CHALLONGE_API_KEY)
                if err:
                    st.error(err)
                    st.stop()
                
                # 4. ประมวลผลหาล้มยักษ์
                giant_killings = []
                matches = chal_data['matches']
                participants = chal_data['participants']
                
                for m in matches:
                    win_p_name = participants.get(m['winner_id'])
                    lose_p_name = participants.get(m['loser_id'])
                    
                    def find_in_notion(c_name):
                        if not c_name: return None, None
                        clean_c = c_name.split('-')[0].strip()
                        for n_name, n_data in notion_members.items():
                            if clean_c in n_name:
                                return n_name, n_data
                        return None, None

                    winner_name_notion, winner_data = find_in_notion(win_p_name)
                    loser_name_notion, loser_data = find_in_notion(lose_p_name)
                    
                    if winner_data and loser_data:
                        winner_score = winner_data['score']
                        loser_score = loser_data['score']
                        
                        # 🔥 เงื่อนไขล้มยักษ์
                        if winner_score <= 99 and loser_score >= 100:
                            giant_killings.append({
                                "winner": winner_name_notion,
                                "winner_id": winner_data['id'],
                                "loser": loser_name_notion,
                                "winner_score": winner_score,
                                "loser_score": loser_score
                            })

                # 5. แสดงผล
                if not giant_killings:
                    st.info("ไม่พบการล้มยักษ์ในรายการนี้")
                else:
                    st.success(f"🔥 พบการล้มยักษ์ทั้งหมด {len(giant_killings)} คู่!")
                    df_gk = pd.DataFrame(giant_killings)
                    st.table(df_gk[['winner', 'winner_score', 'loser', 'loser_score']])
                    
                    st.session_state['giant_killings_data'] = giant_killings
                    st.session_state['gk_project_id'] = project_id_notion
                    st.session_state['gk_project_name'] = target_project_name

    # ปุ่มยืนยัน
    if 'giant_killings_data' in st.session_state and st.session_state['giant_killings_data']:
        if st.button("✅ ยืนยันแจกโบนัส (+5 คะแนน)"):
            count = 0
            progress = st.progress(0)
            gk_list = st.session_state['giant_killings_data']
            total = len(gk_list)
            
            for i, item in enumerate(gk_list):
                record_name = f"Bonus: ล้มยักษ์ (ชนะ {item['loser']})"
                member_id = item['winner_id']
                proj_id = st.session_state['gk_project_id']
                
                if create_history_record(proj_id, member_id, 5, record_name):
                    count += 1
                progress.progress((i+1)/total)
                time.sleep(0.1)
            
            st.success(f"บันทึกโบนัสสำเร็จ {count} รายการ!")
            del st.session_state['giant_killings_data']
