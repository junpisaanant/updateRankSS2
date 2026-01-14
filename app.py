import streamlit as st
import pandas as pd
import requests
import time
import traceback
import math 

# ================= CONFIGURATION =================
try:
    NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
except FileNotFoundError:
    # กรณีรันในเครื่องแล้วลืมสร้าง secrets.toml (ใส่ Token ชั่วคราวตรงนี้ได้ถ้าจำเป็น)
    NOTION_TOKEN = "YOUR_TOKEN_HERE"

MEMBER_DB_ID = "271e6d24b97d80289175eef889a90a09" 
HISTORY_DB_ID = "2b1e6d24b97d803786c2ec7011c995ef"
PROJECT_DB_ID = "26fe6d24b97d80e1bdb3c2452a31694c" 

headers = {
    "Authorization": "Bearer " + NOTION_TOKEN,
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ================= HELPER FUNCTIONS =================

def get_member_id(raw_name):
    if not isinstance(raw_name, str):
        return None
    clean_name = raw_name.split('-')[0].strip()
    url = f"https://api.notion.com/v1/databases/{MEMBER_DB_ID}/query"
    payload = {
        "filter": {
            "property": "ชื่อ", 
            "title": {"contains": clean_name}
        }
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        if data.get('results'):
            return data['results'][0]['id']
        return None
    except:
        return None

def get_project_info(project_name):
    """
    ค้นหา ID งานแข่ง และเช็ค 'ประเภทงาน' ว่าเป็นงานย่อยหรือไม่
    Return: Dictionary {id, type}
    """
    url = f"https://api.notion.com/v1/databases/{PROJECT_DB_ID}/query"
    search_term = str(project_name).strip()
    
    payload = {
        "filter": {
            "property": "ชื่อกิจกรรม", 
            "title": {"contains": search_term}
        }
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        
        if data.get('results'):
            page = data['results'][0]
            project_id = page['id']
            
            # ดึงประเภทงาน
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
    except Exception as e:
        print(f"Error getting project: {e}")
        return None

def calculate_score(row_index, is_minor_event):
    score = 0
    # เกณฑ์คะแนนปกติ
    if row_index == 1: score = 25
    elif row_index == 2: score = 20
    elif 3 <= row_index <= 4: score = 16
    elif 5 <= row_index <= 8: score = 10
    elif 9 <= row_index <= 16: score = 5
    else: score = 2

    # เกณฑ์งานย่อย
    if is_minor_event and row_index <= 15:
        score = math.ceil(score / 2)
        
    return score

# ⚠️ แก้ไขจุดที่ 1: รับ project_name เพิ่มเข้ามา
def create_history_record(project_id, member_id, score, project_name):
    url = "https://api.notion.com/v1/pages"
    
    properties = {
        # ⚠️ แก้ไขจุดที่ 2: เพิ่มการบันทึก Title (Name)
        "Name": { 
            "title": [
                {
                    "text": {
                        "content": str(project_name)
                    }
                }
            ]
        },
        "สมาชิกแรงค์": { "relation": [{"id": member_id}] },
        "ชื่องานแข่ง": { "relation": [{"id": project_id}] },
        "คะแนนที่บวก": { "number": float(score) }
    }
    
    payload = {"parent": {"database_id": HISTORY_DB_ID}, "properties": properties}
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code != 200:
        st.error(f"❌ Notion Error: {response.text}")
        return False
    return True

# ================= UI PART =================

st.title("🏆 Update คะแนนแรงค์ Season2")
st.write("ระบบคำนวณคะแนนอัตโนมัติตามลำดับใน Excel")
st.write("บรรทัดแรกสุด(ชื่องานแข่ง)ให้เอาจาก>> https://auspicious-tarsier-51c.notion.site/26fe6d24b97d80e1bdb3c2452a31694c?v=26fe6d24b97d813a9d8f000c8ed5dc7b&source=copy_link")
st.write("ตัวอย่าง Template ให้เอาจาก>> https://docs.google.com/spreadsheets/d/1DPklisqF-ykQtKgg2h2AH-Q5ePN30zr1lNm9EaRjvg4/edit?gid=0#gid=0")

uploaded_file = st.file_uploader("เลือกไฟล์ Excel (.xlsx)", type=['xlsx'])

if uploaded_file is not None:
    try:
        df = pd.read_excel(uploaded_file, header=None)
        
        st.write("### Preview Data:")
        st.dataframe(df.head(10))
        
        project_name_raw = df.iloc[0, 0]
        st.info(f"📍 งานแข่งในไฟล์: **{project_name_raw}**")
        
        if st.button("🚀 เริ่มคำนวณและนำเข้าข้อมูล"):
            status_box = st.empty()
            status_box.text("กำลังตรวจสอบประเภทงาน...")
            
            project_info = get_project_info(project_name_raw)
            
            if not project_info:
                st.error(f"❌ ไม่พบงานแข่ง: {project_name_raw}")
            else:
                project_id = project_info['id']
                event_type = project_info['type']
                is_minor = "งานย่อย" in str(event_type)
                
                if is_minor:
                    st.warning(f"⚠️ ตรวจพบประเภทงาน: **'{event_type}'** (ระบบจะหารคะแนน)")
                else:
                    st.success(f"✅ ตรวจพบประเภทงาน: **'{event_type}'** (คิดคะแนนเต็ม)")
                
                progress_bar = st.progress(0)
                data_rows = df.iloc[1:]
                total_rows = len(data_rows)
                count_success = 0
                
                for i, (index, row) in enumerate(data_rows.iterrows()):
                    excel_row_num = index 
                    raw_name = row[0]
                    if pd.isna(raw_name): continue
                    
                    clean_name = str(raw_name).split('-')[0].strip()
                    calculated_score = calculate_score(excel_row_num, is_minor)
                    
                    status_box.text(f"Processing ({i+1}/{total_rows}): {clean_name}")
                    
                    member_id = get_member_id(raw_name)
                    
                    if member_id:
                        # ⚠️ แก้ไขจุดที่ 3: ส่ง project_name_raw เข้าไปด้วย
                        if create_history_record(project_id, member_id, calculated_score, project_name_raw):
                            count_success += 1
                    else:
                        st.warning(f"⚠️ ไม่พบสมาชิก: {clean_name}")
                    
                    progress_bar.progress((i + 1) / total_rows)
                    time.sleep(0.1)
                    
                status_box.empty()
                st.success(f"🎉 เสร็จสิ้น! บันทึกสำเร็จ {count_success} รายการ")
                
    except Exception as e:
        st.error("เกิดข้อผิดพลาด:")
        st.code(traceback.format_exc())

