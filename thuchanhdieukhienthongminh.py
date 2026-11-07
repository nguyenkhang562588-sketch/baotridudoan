import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import requests
import paho.mqtt.client as mqtt
import json
import ssl
import time

# 1. Khởi tạo "kho chứa" dữ liệu trong Streamlit
if 'sensor_data' not in st.session_state:
    st.session_state.sensor_data = {"rpm": 0.0, "vibration": 0.0, "temperature": 0.0, "current": 0.0}

# 2. Hàm kết nối và nhận dữ liệu
@st.cache_resource
def init_mqtt_subscriber():
    def on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            client.subscribe("pdm/motor/sensor_data")
            
    def on_message(client, userdata, msg):
        payload = json.loads(msg.payload.decode())
        st.session_state.sensor_data = payload

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="Streamlit_Dashboard")
    client.username_pw_set(st.secrets["MQTT_USERNAME"], st.secrets["MQTT_PASSWORD"])
    client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS)
    
    client.on_connect = on_connect
    client.on_message = on_message
    
    client.connect(st.secrets["MQTT_BROKER"], st.secrets["MQTT_PORT"])
    client.loop_start() 
    return client

mqtt_client = init_mqtt_subscriber()

# 1. CẤU HÌNH TRANG
st.set_page_config(page_title="Dashboard Bảo Trì Dự Đoán", layout="wide")
st.title("⚙️ Hệ Thống Giám Sát & Bảo Trì Dự Đoán Thiết Bị")

# ==========================================
# HÀM GỬI CẢNH BÁO TELEGRAM (BƯỚC 6)
# ==========================================
# THAY THẾ BẰNG TOKEN VÀ CHAT ID CỦA BẠN
TELEGRAM_BOT_TOKEN = st.secrets["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = st.secrets["TELEGRAM_CHAT_ID"]

def send_telegram_alert(machine_name, fault, action):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    message = f"🚨 **CẢNH BÁO KHẨN CẤP** 🚨\n\n" \
              f"🏭 **Thiết bị:** {machine_name}\n" \
              f"❌ **Phát hiện lỗi:** {fault}\n" \
              f"🛠️ **Yêu cầu xử lý:** {action}"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Lỗi gửi Telegram: {e}")
# ==========================================
# BƯỚC 5: TỪ ĐIỂN LỖI & HÀNH ĐỘNG (KNOWLEDGE BASE)
# ==========================================
# Đây là bảng chuẩn hóa mọi hành động tương ứng với từng loại lỗi (Khối 4 Poster)
FAULT_KNOWLEDGE_BASE = {
    "NORMAL": {
        "desc": "Hoạt động bình thường",
        "action": "Duy trì theo dõi định kỳ. Không cần can thiệp."
    },
    "OVERLOAD": {
        "desc": "Quá tải động cơ",
        "action": "Giảm tải ngay lập tức. Kiểm tra hệ thống truyền động và băng tải."
    },
    "HIGH_VIBRATION": {
        "desc": "Rung động bất thường",
        "action": "Kiểm tra sự mất cân bằng, lệch trục hoặc lỏng chân đế. Siết lại bulong."
    },
    "JAM": {
        "desc": "Kẹt cơ khí (Jamming)",
        "action": "DỪNG MÁY KHẨN CẤP. Kiểm tra dị vật kẹt trong hệ thống cơ khí, bơm mỡ bôi trơn."
    },
    },
    "Imbalance": {
        "desc": "Mất cân bằng rotor / Lệch trục",
        "action": "Giảm tốc độ (RPM). Cần kiểm tra sự tích tụ bụi/rác trên cánh bơm, cân bằng động lại rotor."
    },
    "Looseness": {
        "desc": "Lỏng cơ khí / Lỏng chân đế",
        "action": "Dừng máy. Kiểm tra và siết chặt lại các bulong móng, kiểm tra bệ đỡ giảm chấn."
    },
    "Bearing Fault": {
        "desc": "Hư hỏng vòng bi (Rơ mòn, nứt, vỡ)",
        "action": "Lên lịch dừng máy khẩn cấp. Thay thế cụm vòng bi mới, kiểm tra lại chất lượng mỡ bôi trơn."
    },
    "Overheat": {
        "desc": "Quá nhiệt động cơ",
        "action": "Ngắt tải ngay lập tức. Kiểm tra hệ thống quạt tản nhiệt và đo kiểm tra cuộn dây stator."
    }
}

# ==========================================
# CƠ SỞ DỮ LIỆU TỪNG MÁY (DỮ LIỆU ĐỘNG)
# ==========================================
machine_db = {
    "Máy Bơm Số 1": {
        "health": 65,
        "rul": 25,
        "fault": "Imbalance",
        "conf": 0.75,
        "fft_peak": 25
    },
    "Máy Bơm Số 2": {
        "health": 30,
        "rul": 10,
        "fault": "Bearing Fault",
        "conf": 0.95,
        "fft_peak": 65
    },
    "Quạt hút 05": {
        "health": 95,
        "rul": 120,
        "fault": "Normal",
        "conf": 0.99,
        "fft_peak": 10
    },
    "Động cơ băng tải": {
        "health": 80,
        "rul": 50,
        "fault": "Looseness",
        "conf": 0.82,
        "fft_peak": 40
    }
}

# ==========================================
# CÁC HÀM TẠO DỮ LIỆU SÓNG VÀ LOGIC
# ==========================================
def generate_fake_vibration_data(scale):
    time_steps = pd.date_range(start=pd.Timestamp.now(), periods=100, freq='s')
    vibration_x = np.random.normal(0, scale, 100) 
    vibration_y = np.random.normal(0, scale * 0.7, 100) 
    return pd.DataFrame({'Time': time_steps, 'Vibration X': vibration_x, 'Vibration Y': vibration_y})

def generate_fake_fft_data(peak_index):
    freqs = np.linspace(0, 500, 100)
    amplitudes = np.random.exponential(0.3, 100)
    amplitudes[peak_index] += 4.2  
    return pd.DataFrame({'Tần số (Hz)': freqs, 'Biên độ (g)': amplitudes})

def generate_fake_rul_data(curr_health):
    days = np.arange(1, 101)
    health = curr_health - (days ** 1.3) / 10 + np.random.normal(0, 1.2, 100)
    health = np.clip(health, 0, 100) 
    return pd.DataFrame({'Ngày vận hành': days, 'Chỉ số sức khỏe (%)': health})

def xac_dinh_canh_bao(rul, health, ai_label, ai_conf):
    if rul <= 15 or health <= 50 or (ai_label not in ["Normal", "NORMAL"] and ai_conf > 0.85):
        return "🔴 Đỏ (Nguy hiểm)"
    elif rul <= 30 or health <= 80 or (ai_label not in ["Normal", "NORMAL"] and ai_conf <= 0.85):
        return "🟡 Vàng (Cảnh báo)"
    else:
        return "🟢 Xanh (Bình thường)"

# ==========================================
# SIDEBAR - ĐIỀU KHIỂN CHỌN MÁY
# ==========================================
st.sidebar.header("Tùy chọn hiển thị")
machine_selected = st.sidebar.selectbox("Chọn máy giám sát:", list(machine_db.keys()))
st.sidebar.markdown("---")

# ==========================================
# LẤY THÔNG SỐ CỦA MÁY & KÍCH HOẠT TELEGRAM
# ==========================================
curr_data = machine_db[machine_selected]
curr_health = curr_data["health"]
curr_rul = curr_data["rul"]
curr_fault = curr_data["fault"]
curr_conf = curr_data["conf"]
curr_status = xac_dinh_canh_bao(curr_rul, curr_health, curr_fault, curr_conf)

curr_fault_desc = FAULT_KNOWLEDGE_BASE[curr_fault]["desc"]
curr_action = FAULT_KNOWLEDGE_BASE[curr_fault]["action"]

# ==========================================
# 4 CHỈ SỐ TỔNG QUAN (ĐÃ ĐƯỢC TÍCH HỢP MQTT)
# ==========================================
latest_data = st.session_state.sensor_data

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric(label="Tốc độ Động cơ (RPM)", value=f"{latest_data.get('rpm', 0):.2f}")
with col2:
    st.metric(label="Độ rung (Vibration)", value=f"{latest_data.get('vibration', 0):.3f}")
with col3:
    st.metric(label="Nhiệt độ (Temperature)", value=f"{latest_data.get('temperature', 0):.1f} °C")
with col4:
    st.metric(label="Dòng điện (Current)", value=f"{latest_data.get('current', 0):.2f} A")

st.markdown("---")

# ==========================================
# LÔ-GÍC CẢNH BÁO TELEGRAM (ĐỘC LẬP TỰ ĐỘNG & THỦ CÔNG)
# ==========================================
import time

current_time = time.time()

# --- CẤU HÌNH THỜI GIAN ĐỘC LẬP ---
AUTO_COOLDOWN = 6000           # Gửi tự động: Cứ sau 60 giây gửi 1 lần
MANUAL_WINDOW = 300          # Chống spam thủ công: Xét trong khung 300 giây (5 phút)
MAX_MANUAL_ALERTS = 5        # Chống spam thủ công: Tối đa 5 lần bấm trong MANUAL_WINDOW

# 1. Khởi tạo bộ nhớ cho nút bấm thủ công
history_key = f"manual_alert_history_{machine_selected}"
if history_key not in st.session_state:
    st.session_state[history_key] = []

# 2. Khởi tạo bộ nhớ cho tiến trình tự động
auto_alert_key = f"last_auto_alert_{machine_selected}"
if auto_alert_key not in st.session_state:
    st.session_state[auto_alert_key] = 0.0

if "Đỏ" in curr_status:
    # --- LUỒNG 1: XỬ LÝ NÚT BẤM THỦ CÔNG (CHỐNG SPAM) ---
    st.session_state[history_key] = [
        t for t in st.session_state[history_key] 
        if current_time - t <= MANUAL_WINDOW
    ]
    
    sent_count = len(st.session_state[history_key])
    st.caption(f"ℹ️ Chống spam: Đã bấm gửi **{sent_count}/{MAX_MANUAL_ALERTS}** lần trong {MANUAL_WINDOW//60} phút qua.")

    if st.button("📲 Gửi cảnh báo khẩn cấp qua Telegram ngay"):
        if sent_count >= MAX_MANUAL_ALERTS:
            st.error(f"⚠️ Vượt giới hạn! Nút bấm đang bị khóa để chống spam. Vui lòng chờ vài phút.")
        else:
            send_telegram_alert(machine_selected, curr_fault_desc, curr_action)
            st.session_state[history_key].append(current_time)
            st.success(f"Đã gửi cảnh báo khẩn cấp! (Còn lại {MAX_MANUAL_ALERTS - sent_count - 1} lượt bấm)")

    # --- LUỒNG 2: TỰ ĐỘNG GỬI CẢNH BÁO (KHÔNG LIÊN QUAN TỚI NÚT BẤM) ---
    last_auto_sent = st.session_state[auto_alert_key]
    if current_time - last_auto_sent > AUTO_COOLDOWN:
        send_telegram_alert(machine_selected, curr_fault_desc, curr_action)
        st.session_state[auto_alert_key] = current_time
        st.toast(f"Hệ thống tự động gửi cảnh báo Telegram cho {machine_selected}!", icon="🚨")

elif "Xanh" in curr_status:
    # Reset toàn bộ khi máy an toàn
    st.session_state[auto_alert_key] = 0.0
    st.session_state[history_key] = []

        
# Nếu máy trở lại trạng thái XANH, reset lại bộ nhớ để sẵn sàng cho lần hỏng sau
elif "Xanh" in curr_status:
    st.session_state[alert_key] = False

# Tự động tra cứu mô tả và hành động từ Bộ từ điển (Bước 5)
curr_fault_desc = FAULT_KNOWLEDGE_BASE[curr_fault]["desc"]
curr_action = FAULT_KNOWLEDGE_BASE[curr_fault]["action"]

# ==========================================
# 4 CHỈ SỐ TỔNG QUAN 
# ==========================================
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric(label="Sức khỏe hiện tại", value=f"{curr_health}%", delta=f"{curr_health - 100}%")
with col2:
    st.metric(label="RUL (Thời gian sống còn lại)", value=f"{curr_rul} Ngày", delta="-1 Ngày")
with col3:
    st.metric(label="Trạng thái chẩn đoán (YOLO)", value=curr_fault, delta=curr_status)
with col4:
    st.metric(label="Độ tin cậy mô hình", value=f"{curr_conf * 100:.1f}%")

st.markdown("---")

# ==========================================
# CHI TIẾT SỨC KHỎE & ĐỘ TIN CẬY
# ==========================================
c_gauge, c_diag = st.columns([1, 2])

with c_gauge:
    gauge_color = "#00c04b" if curr_health > 80 else ("#ffa421" if curr_health > 50 else "#ff4b4b")
    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=curr_health,
        title={'text': "Chỉ số sức khỏe (Health Index)", 'font': {'size': 16}},
        gauge={
            'axis': {'range': [0, 100]},
            'bar': {'color': gauge_color},
            'steps': [
                {'range': [0, 50], 'color': "#ff4b4b"},
                {'range': [50, 80], 'color': "#ffa421"},
                {'range': [80, 100], 'color': "#262730"}
            ]
        }
    ))
    fig_gauge.update_layout(height=230, margin=dict(l=15, r=15, t=35, b=10))
    st.plotly_chart(fig_gauge, use_container_width=True)

with c_diag:
    st.subheader(f"Chẩn đoán chi tiết - {machine_selected}")
    
    if curr_fault == "Normal":
        st.success(f"✅ Trạng thái: **{curr_fault} ({curr_fault_desc})**")
    elif "Đỏ" in curr_status:
        st.error(f"🚨 Nhận diện lỗi: **{curr_fault} ({curr_fault_desc})**")
    else:
        st.warning(f"⚠️ Nhận diện lỗi: **{curr_fault} ({curr_fault_desc})**")
        
    st.write(f"**Độ tin cậy YOLOv8:** {curr_conf * 100:.1f}%")
    st.progress(curr_conf)
    
    # Hiển thị hành động tự động từ từ điển (Bước 5)
    st.info(f"🛠️ **Hành động đề xuất (SOP):** {curr_action}")

st.markdown("---")

# ==========================================
# TÍN HIỆU RUNG
# ==========================================
st.subheader(f"📊 Phân tích tín hiệu rung - {machine_selected}")
tab_time, tab_fft = st.tabs(["📉 Miền thời gian (Time-domain)", "📈 Miền tần số (FFT Spectrum)"])

with tab_time:
    vib_scale = 1.2 if "Đỏ" in curr_status else (0.6 if "Vàng" in curr_status else 0.2)
    df_vib = generate_fake_vibration_data(vib_scale)
    fig_time = px.line(df_vib, x='Time', y=['Vibration X', 'Vibration Y'], 
                       title=f"Biểu đồ sóng rung thời gian thực - {machine_selected}")
    st.plotly_chart(fig_time, use_container_width=True)

with tab_fft:
    df_fft = generate_fake_fft_data(curr_data["fft_peak"])
    fig_fft = px.bar(df_fft, x='Tần số (Hz)', y='Biên độ (g)', 
                     title="Phổ biên độ tần số FFT",
                     color_discrete_sequence=['#ffa421'])
    st.plotly_chart(fig_fft, use_container_width=True)

st.markdown("---")

# ==========================================
# DỰ BÁO RUL & KẾ HOẠCH BẢO TRÌ
# ==========================================
st.subheader("⏳ Dự báo tuổi thọ (RUL) & Quản lý bảo trì")

col_rul_chart, col_rul_list = st.columns([3, 2])

with col_rul_chart:
    st.markdown(f"**Biểu đồ suy giảm sức khỏe - {machine_selected}**")
    df_rul = generate_fake_rul_data(curr_health)
    fig_rul = px.line(df_rul, x='Ngày vận hành', y='Chỉ số sức khỏe (%)')
    
    fig_rul.add_hline(y=30, line_dash="dash", line_color="red", annotation_text="Ngưỡng hỏng hóc (Failure)")
    fig_rul.add_hline(y=50, line_dash="dash", line_color="orange", annotation_text="Ngưỡng cảnh báo (Warning)")
    
    fig_rul.update_layout(height=350, margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig_rul, use_container_width=True)

with col_rul_list:
    st.markdown("**Danh sách thiết bị ưu tiên bảo trì**")
    machines = list(machine_db.keys())
    ruls = [machine_db[m]["rul"] for m in machines]
    healths = [machine_db[m]["health"] for m in machines]
    yolo_labels = [machine_db[m]["fault"] for m in machines]
    yolo_confs = [machine_db[m]["conf"] for m in machines]
    
    danh_sach_canh_bao = [xac_dinh_canh_bao(r, h, l, c) for r, h, l, c in zip(ruls, healths, yolo_labels, yolo_confs)]
    
    # Lấy hành động tự động từ KNOWLEDGE BASE để điền vào bảng
    danh_sach_hanh_dong = [FAULT_KNOWLEDGE_BASE[l]["action"] for l in yolo_labels]
    
    fake_maintenance_list = pd.DataFrame({
        "Tên máy": machines,
        "Cảnh báo": danh_sach_canh_bao,
        "RUL (Ngày)": ruls,
        "Lỗi YOLO": yolo_labels,
        "Hành động": danh_sach_hanh_dong
    }).sort_values(by="RUL (Ngày)")
    
    st.dataframe(fake_maintenance_list, use_container_width=True, hide_index=True)

# ==========================================
# HIỂN THỊ BẢNG TRA CỨU HÀNH ĐỘNG (BƯỚC 5)
# ==========================================
with st.expander("📖 Bảng tra cứu hành động khắc phục tiêu chuẩn (SOP) đối với từng loại lỗi"):
    df_sop = pd.DataFrame([
        {"Loại Lỗi (YOLO)": k, "Mô tả": v["desc"], "Quy trình xử lý (SOP)": v["action"]}
        for k, v in FAULT_KNOWLEDGE_BASE.items()
    ])
    st.table(df_sop)
time.sleep(1)
st.rerun()    
