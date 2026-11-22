#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BACKEND GATEWAY: FLASK + THREADING SERIAL (USB & BLUETOOTH HC-05)
Tich hop tinh Diem suong, Toc do tang nhiet, Nhat ky su co & API RFID
"""

import os
import time
import json
import math
import logging
import threading
import urllib.request
import urllib.parse
from collections import deque

import serial
import serial.tools.list_ports
from flask import Flask, jsonify, request, render_template

import database

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("smart_monitor")

app = Flask(__name__)

# --- TELEGRAM ALERT (tuy chon) ---
# Doc token/chat_id tu raspberry_pi/telegram_secrets.py (file rieng, KHONG commit len git).
try:
    import telegram_secrets as tg
    TELEGRAM_BOT_TOKEN = getattr(tg, "BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = getattr(tg, "CHAT_ID", "")
except ImportError:
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_CHAT_ID = ""

TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send_telegram_message(chat_id, message):
    """Gui 1 tin nhan toi chat_id bat ky qua Telegram Bot API (khong dung thu vien ngoai)."""
    if not TELEGRAM_ENABLED:
        log.warning("Telegram chua duoc cau hinh (thieu telegram_secrets.py) - bo qua gui tin")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            ok = resp.status == 200
        if not ok:
            log.error("Gui tin Telegram toi %s tra ve HTTP %s", chat_id, resp.status)
        return ok
    except Exception as exc:
        log.error("Gui tin Telegram toi %s loi: %s", chat_id, exc)
        return False


def send_telegram_alert(message):
    """Gui tin nhan canh bao toi chu he thong (TELEGRAM_CHAT_ID)."""
    ok = send_telegram_message(TELEGRAM_CHAT_ID, message)
    if ok:
        log.info("Da gui canh bao Telegram thanh cong")
    return ok


# --- DIEU KHIEN SERVO (QUAT LAM MAT) - CHUYEN TU ARDUINO SANG RASPBERRY PI ---
# Ly do: servo quay lien tuc rut dong tu nguon 5V cua Arduino gay sut ap/treo
# mach. Servo nay cam truc tiep vao GPIO18 (vat ly pin 12) cua Raspberry Pi,
# dung nguon 5V rieng (khong chung rail voi Arduino).
SERVO_GPIO_PIN = 18   # BCM numbering - vat ly pin 12
SERVO_FREQ_HZ = 50
MIN_SERVO_RUN_SEC = 60  # Da kich hoat thi phai quay toi thieu 60s (tuong tu logic buzzer 10s ben Arduino)


class PiServoController:
    """Quay servo lien tuc 0<->180 do mo phong quat, toc do theo status
    (CRITICAL=nhanh, WARNING=vua, NORMAL=tat), ho tro lenh tay VENT_OPEN/
    VENT_CLOSE/VENT_AUTO va giu quay toi thieu 60s mot khi da kich hoat."""

    def __init__(self, pin=SERVO_GPIO_PIN):
        self.pin = pin
        self.available = GPIO_AVAILABLE
        self.lock = threading.Lock()
        self.angle = 0
        self.direction = 1
        self.mode = 0  # 0=tat, 1=vua (warning), 2=nhanh khong dung (critical)
        self.manual_override = False
        self.manual_mode = 0
        self.latched = False
        self.latch_start = 0.0
        self.latched_mode = 0

        if self.available:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setwarnings(False)
                GPIO.setup(self.pin, GPIO.OUT)
                self.pwm = GPIO.PWM(self.pin, SERVO_FREQ_HZ)
                self.pwm.start(self._angle_to_duty(0))
                log.info("PiServoController: da khoi tao PWM tren GPIO%d (vat ly pin 12)", self.pin)
            except Exception as exc:
                log.error("PiServoController: khong khoi tao duoc GPIO%d: %s", self.pin, exc)
                self.available = False
        else:
            log.warning("PiServoController: khong co RPi.GPIO - servo se KHONG quay (chi mo phong %)")

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    @staticmethod
    def _angle_to_duty(angle):
        # SG90: 0 do ~ 2.5% duty, 180 do ~ 12.5% duty @ 50Hz
        return 2.5 + (max(0, min(180, angle)) / 180.0) * 10.0

    def update_from_status(self, status):
        """Goi moi lan co telemetry moi (status tu Arduino) de tinh target mode,
        tru khi dang bi override thu cong."""
        target_mode = 2 if status == "CRITICAL" else (1 if status == "WARNING" else 0)
        now = time.time()
        with self.lock:
            if self.manual_override:
                self.mode = self.manual_mode
                return
            if target_mode > 0:
                if not self.latched:
                    self.latched = True
                    self.latch_start = now
                    self.latched_mode = target_mode
                else:
                    self.latched_mode = max(self.latched_mode, target_mode)
                self.mode = self.latched_mode
            else:
                if self.latched:
                    if now - self.latch_start >= MIN_SERVO_RUN_SEC:
                        self.latched = False
                        self.mode = 0
                    else:
                        self.mode = self.latched_mode
                else:
                    self.mode = 0

    def set_manual(self, cmd):
        with self.lock:
            if cmd == "VENT_OPEN":
                self.manual_override = True
                self.manual_mode = 2
                self.mode = 2
                log.info("PiServoController: lenh tay VENT_OPEN - quat quay toi da")
            elif cmd == "VENT_CLOSE":
                self.manual_override = True
                self.manual_mode = 0
                self.mode = 0
                self.latched = False
                log.info("PiServoController: lenh tay VENT_CLOSE - tat quat")
            elif cmd == "VENT_AUTO":
                self.manual_override = False
                log.info("PiServoController: VENT_AUTO - tra ve che do tu dong theo nhiet do")

    def current_percent(self):
        with self.lock:
            return {0: 0, 1: 50, 2: 100}.get(self.mode, 0)

    def _run(self):
        while True:
            if not self.available:
                time.sleep(1)
                continue
            with self.lock:
                mode = self.mode
            if mode == 0:
                if self.angle != 0:
                    self.angle = 0
                    try:
                        self.pwm.ChangeDutyCycle(self._angle_to_duty(0))
                    except Exception as exc:
                        log.error("PiServoController: loi ghi PWM: %s", exc)
                time.sleep(0.2)
                continue

            step_interval = 0.012 if mode == 2 else 0.035
            step_size = 12 if mode == 2 else 5
            self.angle += self.direction * step_size
            if self.angle >= 180:
                self.angle = 180
                self.direction = -1
            elif self.angle <= 0:
                self.angle = 0
                self.direction = 1
            try:
                self.pwm.ChangeDutyCycle(self._angle_to_duty(self.angle))
            except Exception as exc:
                log.error("PiServoController: loi ghi PWM: %s", exc)
            time.sleep(step_interval)


pi_servo = PiServoController()


# Bo nho dem trang thai hien tai
latest_telemetry = {
    "temp": 0.0,
    "hum": 0.0,
    "rack": 0.0,
    "dew_point": 0.0,
    "rise_rate": 0.0,
    "door": "CLOSED",
    "light": "OFF",
    "thresh": 30.0,
    "status": "DISCONNECTED",
    "servo": 0,
    "conn_type": "NONE",
    "last_update": "--:--:--",
    "rack_anomaly": False,
}

data_lock = threading.Lock()
serial_lock = threading.Lock()
serial_port_instance = None

# Hang doi tinh toc do tang nhiet (Luu 5 mau gan nhat: (timestamp_sec, rack_temp))
temp_window = deque(maxlen=5)
last_recorded_status = "NORMAL"

# Hang doi kiem tra "hop mach"/nhieu bat thuong cho LM35 (Rack): neu gia tri nhay
# qua >8C giua 2 lan do lien tiep, xay ra >=2 lan trong 6 mau gan nhat -> nghi ho mach.
rack_history = deque(maxlen=6)

VALID_COMMANDS = {"VENT_OPEN", "VENT_CLOSE", "VENT_AUTO", "ALARM_OFF"}

# Danh sach nhan vien dang ky the RFID mau
RFID_DIRECTORY = {
    "A1B2C3D4": "Nguyen Van An (SysAdmin)",
    "E5F6G7H8": "Tran Minh Tuan (Ky su Mang)",
    "99887766": "Le Hoang Nam (Bao tri)",
}


def calculate_dew_point(temp_c, hum_pct):
    """Tinh diem suong (C) theo cong thuc Magnus-Tetens"""
    if not hum_pct or hum_pct <= 0 or temp_c is None:
        return 0.0
    a, b = 17.27, 237.7
    gamma = ((a * temp_c) / (b + temp_c)) + math.log(hum_pct / 100.0)
    dew = (b * gamma) / (a - gamma)
    return round(dew, 1)


def calculate_rise_rate(current_rack_temp):
    """Tinh toc do bien thien nhiet do tu Rack (C/phut)"""
    now = time.time()
    temp_window.append((now, current_rack_temp))
    if len(temp_window) < 2:
        return 0.0
    oldest_t, oldest_temp = temp_window[0]
    dt_minutes = (now - oldest_t) / 60.0
    if dt_minutes <= 0.01:
        return 0.0
    rate = (current_rack_temp - oldest_temp) / dt_minutes
    return round(rate, 2)


def detect_rack_anomaly(current_rack_temp):
    """Phat hien cam bien LM35 nghi ho mach/long day: gia tri nhay bat thuong giua
    cac lan doc lien tiep (vd 0C <-> 20C moi 2s) la dieu khong the xay ra vat ly."""
    rack_history.append(current_rack_temp)
    if len(rack_history) < 3:
        return False
    jumps = sum(
        1 for i in range(1, len(rack_history))
        if abs(rack_history[i] - rack_history[i - 1]) > 8.0
    )
    return jumps >= 2


def find_communication_port():
    """Uu tien quet cong USB Serial Arduino hoac Bluetooth RFCOMM0"""
    if os.path.exists("/dev/rfcomm0"):
        return "/dev/rfcomm0", "BLUETOOTH (HC-05)"

    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        desc = (p.description or "").lower()
        dev = p.device
        if any(k in desc for k in ["arduino", "ch340", "cp210", "usb serial"]) or "ttyacm" in dev.lower() or "ttyusb" in dev.lower():
            return dev, f"USB SERIAL ({dev})"
    return None, "NONE"


def serial_worker():
    """Luong nen doc JSON tu Arduino, tinh toan phan tich & ghi SQLite"""
    global serial_port_instance, last_recorded_status

    log.info("Serial worker thread started, scanning for Arduino/Bluetooth...")

    while True:
        port, conn_label = find_communication_port()
        if not port:
            with data_lock:
                latest_telemetry["status"] = "DISCONNECTED"
                latest_telemetry["conn_type"] = "NONE"
                latest_telemetry["rack_anomaly"] = False
            log.warning("Khong tim thay Arduino (USB) hoac HC-05 (/dev/rfcomm0) - thu lai sau 3s")
            time.sleep(3)
            continue

        try:
            log.info("Dang ket noi qua %s", conn_label)
            ser = serial.Serial(port, 9600, timeout=2)
            with serial_lock:
                serial_port_instance = ser
            time.sleep(2.0)
            log.info("Da ket noi thanh cong qua %s", conn_label)
            database.insert_incident("INFO", f"Gateway da ket noi qua {conn_label}")

            while True:
                if ser.in_waiting > 0:
                    raw_line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if raw_line.startswith("{") and raw_line.endswith("}"):
                        try:
                            payload = json.loads(raw_line)
                        except json.JSONDecodeError:
                            log.warning("Du lieu JSON khong hop le, bo qua: %r", raw_line)
                            continue

                        temp = float(payload.get("temp", 0.0))
                        hum = float(payload.get("hum", 0.0))
                        rack = float(payload.get("rack", 0.0))
                        status = payload.get("status", "NORMAL")
                        door = payload.get("door", "CLOSED")
                        light = payload.get("light", "OFF")

                        # Servo (quat) nay do Raspberry Pi tu quay qua GPIO18, khong con
                        # phu thuoc truong "servo" cua Arduino (Arduino khong con servo).
                        pi_servo.update_from_status(status)
                        servo = pi_servo.current_percent()

                        dew_pt = calculate_dew_point(temp, hum)
                        rise_rt = calculate_rise_rate(rack)
                        rack_anomaly = detect_rack_anomaly(rack)
                        if rack_anomaly:
                            log.warning(
                                "LM35 (A0) nghi ho mach: gia tri Rack dao dong bat thuong (hien tai=%.1fC)",
                                rack,
                            )

                        if status != last_recorded_status:
                            if status == "CRITICAL":
                                database.insert_incident(
                                    "CRITICAL",
                                    f"Qua nhiet tu Rack ({rack}C - coi nhu >60C)! Kich hoat quat 100%.",
                                )
                                alert_msg = (
                                    "🔴 <b>CẢNH BÁO QUÁ NHIỆT - SERVER ROOM</b>\n"
                                    f"Tủ Rack (LM35): <b>{rack:.1f}°C</b> (vượt ngưỡng demo 30°C ~ &gt;60°C thực tế)\n"
                                    f"Nhiệt độ phòng (DHT11): {temp:.1f}°C / {hum:.0f}%\n"
                                    "Servo đã quay làm mát tối đa, buzzer + LED đỏ đã kích hoạt.\n"
                                    f"Thời gian: {time.strftime('%H:%M:%S %d/%m/%Y')}"
                                )
                                threading.Thread(target=send_telegram_alert, args=(alert_msg,), daemon=True).start()
                            elif status == "WARNING":
                                database.insert_incident(
                                    "WARNING",
                                    f"Nhiet do cham nguong canh bao (Rack: {rack}C, Phong: {temp}C).",
                                )
                            elif status == "NORMAL" and last_recorded_status in ("WARNING", "CRITICAL"):
                                database.insert_incident("INFO", "Nhiet do he thong da hoi phuc ve muc an toan.")
                                if last_recorded_status == "CRITICAL":
                                    recovery_msg = (
                                        "🟢 <b>SERVER ROOM ĐÃ ỔN ĐỊNH TRỞ LẠI</b>\n"
                                        f"Rack: {rack:.1f}°C, Phòng: {temp:.1f}°C\n"
                                        f"Thời gian: {time.strftime('%H:%M:%S %d/%m/%Y')}"
                                    )
                                    threading.Thread(target=send_telegram_alert, args=(recovery_msg,), daemon=True).start()
                            log.info("EVENT STATUS_CHANGE %s -> %s", last_recorded_status, status)
                            last_recorded_status = status

                        with data_lock:
                            latest_telemetry.update(payload)
                            latest_telemetry["servo"] = servo
                            latest_telemetry["dew_point"] = dew_pt
                            latest_telemetry["rise_rate"] = rise_rt
                            latest_telemetry["conn_type"] = conn_label
                            latest_telemetry["last_update"] = time.strftime("%H:%M:%S")
                            latest_telemetry["rack_anomaly"] = rack_anomaly

                        database.insert_log(temp, hum, rack, dew_pt, rise_rt, door, light, status, servo)

                        log.info(
                            "READING temp=%.1fC hum=%.1f%% rack=%.1fC dew=%.1fC rise=%.2fC/p "
                            "door=%s light=%s status=%s servo=%s",
                            temp, hum, rack, dew_pt, rise_rt, door, light, status, servo,
                        )
                time.sleep(0.05)

        except (serial.SerialException, OSError) as exc:
            log.error("Mat ket noi %s: %s", port, exc)
            with serial_lock:
                serial_port_instance = None
            with data_lock:
                latest_telemetry["status"] = "DISCONNECTED"
                latest_telemetry["conn_type"] = "NONE"
                latest_telemetry["rack_anomaly"] = False
            database.insert_incident("WARNING", f"Mat ket noi Serial tren {port}: {exc}")
            time.sleep(2)


def send_command_to_arduino(cmd):
    with serial_lock:
        if serial_port_instance and serial_port_instance.is_open:
            try:
                serial_port_instance.write((cmd + "\n").encode("utf-8"))
                serial_port_instance.flush()
                log.info("Da gui lenh xuong Arduino: %s", cmd)
                return True, f"Da thuc thi lenh '{cmd}'."
            except Exception as exc:
                log.error("Gui lenh '%s' loi: %s", cmd, exc)
                return False, str(exc)
        log.error("Khong gui duoc lenh '%s': chua ket noi Arduino", cmd)
        return False, "Chua ket noi duoc voi Arduino!"


def build_hardware_status(t):
    """Tra ve trang thai tung thiet bi theo dung so do chan, de dashboard vua
    monitor vua debug. Cac thiet bi INPUT suy ra tu telemetry JSON cua Arduino;
    cac thiet bi OUTPUT (LED/Buzzer/Servo) khong co tin hieu phan hoi rieng nen
    chi hien thi trang thai SUY RA tu 'status' he thong; LCD tren Arduino khong
    co kenh bao loi nguoc ve Pi nen danh dau 'khong giam sat duoc tu xa'."""
    online = t.get("conn_type", "NONE") != "NONE"
    bt_active = str(t.get("conn_type", "")).startswith("BLUETOOTH")
    usb_active = str(t.get("conn_type", "")).startswith("USB")

    def base(ok_when_online=True):
        if not online:
            return "error"
        return "ok" if ok_when_online else "warning"

    items = [
        {
            "pin": "D2", "device": "DHT11",
            "role": "Nhiet/am phong -> hien thi LCD & gui data len Server",
            "status": base(),
            "detail": f"{t.get('temp')}C / {t.get('hum')}%" if online else "Mat ket noi Arduino",
        },
        {
            "pin": "A0", "device": "LM35",
            "role": "Canh bao Rack nong -> Buzzer + LED + kich hoat Servo quay lien tuc",
            "status": "error" if t.get("rack_anomaly") else base(),
            "detail": (
                f"{t.get('rack')}C - NGHI HO MACH/LONG DAY (gia tri dao dong bat thuong)"
                if t.get("rack_anomaly") else f"{t.get('rack')}C" if online else "Mat ket noi Arduino"
            ),
        },
        {
            "pin": "A1", "device": "Quang tro 5528 + 10k",
            "role": "Dung de mo den LED trong phong Server",
            "status": base(),
            "detail": f"light={t.get('light')}" if online else "Mat ket noi Arduino",
        },
        {
            "pin": "A2", "device": "Bien tro 10k",
            "role": "Chinh nguong canh bao demo",
            "status": base(),
            "detail": f"nguong={t.get('thresh')}C" if online else "Mat ket noi Arduino",
        },
        {
            "pin": "A4, A5", "device": "LCD1602 I2C",
            "role": "Hien thi tai cho tren Arduino",
            "status": "unknown",
            "detail": "Khong co kenh phan hoi qua Serial - kiem tra truc tiep man hinh LCD",
        },
        {
            "pin": "D5, D6, D7", "device": "LED xanh / vang / do",
            "role": "Bao trang thai Normal / Warning / Critical (220 Ohm)",
            "status": base(),
            "detail": f"suy ra tu status={t.get('status')}" if online else "Mat ket noi Arduino",
        },
        {
            "pin": "D8", "device": "Buzzer",
            "role": "Coi bao khi Warning/Critical",
            "status": base(),
            "detail": ("ON" if t.get("status") in ("WARNING", "CRITICAL") else "OFF") if online else "Mat ket noi Arduino",
        },
        {
            "pin": "Pi GPIO18 (truoc la D9)", "device": "Servo SG90",
            "role": "Mo phong quat - DA CHUYEN tu Arduino sang Raspberry Pi dieu khien truc tiep "
                    "(tranh sut ap servo lam treo mach Arduino). Nguon 5V rieng, tin hieu GPIO18.",
            "status": "ok" if pi_servo.available else "error",
            "detail": (
                f"{pi_servo.current_percent()}% toc do quat (Pi tu dieu khien)"
                if pi_servo.available else "Loi GPIO tren Pi - servo KHONG quay duoc"
            ),
        },
        {
            "pin": "D10, D11", "device": "HC-05 Bluetooth",
            "role": "Du phong khong day (SoftwareSerial)",
            "status": "ok" if bt_active else "idle",
            "detail": t.get("conn_type") if bt_active else "Khong hoat dong (dang dung USB hoac mat ket noi)",
        },
        {
            "pin": "D0, D1 (USB)", "device": "USB Serial",
            "role": "Ket noi chinh toi Raspberry Pi",
            "status": "ok" if usb_active else "idle",
            "detail": t.get("conn_type") if usb_active else "Khong hoat dong",
        },
    ]
    return items


# --- TELEGRAM BOT 2 CHIEU (XEM THONG TIN + DIEU KHIEN TU XA) ---
# Long-polling getUpdates (khong can webhook/HTTPS public). Chi chat_id trong
# telegram_secrets.py (TELEGRAM_CHAT_ID) moi duoc phep dieu khien - moi chat_id
# khac bi tu choi va ghi log, khong thuc thi lenh.

TELEGRAM_HELP_TEXT = (
    "🤖 <b>Smart Server Room Bot</b>\n"
    "Theo dõi &amp; điều khiển song song với Dashboard web.\n\n"
    "<b>Xem thông tin:</b>\n"
    "/status - Số liệu hiện tại (nhiệt độ, độ ẩm, trạng thái...)\n"
    "/hardware - Tình trạng kết nối từng thiết bị\n"
    "/history - 5 lần đo gần nhất\n"
    "/incidents - 5 sự cố gần nhất\n\n"
    "<b>Điều khiển:</b>\n"
    "/fan_on - Bật quạt tối đa (ép tay)\n"
    "/fan_off - Tắt quạt (ép tay)\n"
    "/fan_auto - Trả quạt về chế độ tự động\n"
    "/mute - Tắt còi báo động\n"
    "/rfid - Demo quẹt thẻ RFID vào phòng\n"
)


def format_status_text():
    with data_lock:
        t = dict(latest_telemetry)
    status_emoji = {"NORMAL": "🟢", "WARNING": "🟡", "CRITICAL": "🔴"}.get(t.get("status"), "⚪")
    return (
        f"{status_emoji} <b>{t.get('status')}</b> — cập nhật {t.get('last_update')}\n"
        f"Kênh kết nối Arduino: {t.get('conn_type')}\n\n"
        f"🌡️ Phòng (DHT11): {t.get('temp')}°C / {t.get('hum')}%\n"
        f"🔥 Rack (LM35): {t.get('rack')}°C" + (" ⚠️ nghi hở mạch" if t.get("rack_anomaly") else "") + "\n"
        f"💧 Điểm sương: {t.get('dew_point')}°C | Tốc độ tăng nhiệt: {t.get('rise_rate')}°C/phút\n"
        f"🚪 Cửa/Cảm biến sáng: {t.get('door')} | Đèn phòng: {t.get('light')}\n"
        f"🎛️ Ngưỡng demo: {t.get('thresh')}°C\n"
        f"🌀 Quạt (Pi GPIO18): {t.get('servo')}%"
    )


def format_hardware_text():
    with data_lock:
        snapshot = dict(latest_telemetry)
    items = build_hardware_status(snapshot)
    icon = {"ok": "🟢", "warning": "🟡", "error": "🔴", "idle": "⚪", "unknown": "❔"}
    lines = ["🧩 <b>Tình trạng Hardware</b>"]
    for it in items:
        lines.append(f"{icon.get(it['status'], '❔')} <b>{it['device']}</b> ({it['pin']}): {it['detail']}")
    return "\n".join(lines)


def format_history_text():
    rows = database.get_history_logs(limit=5)
    if not rows:
        return "Chưa có dữ liệu trong database."
    lines = ["📜 <b>5 lần đo gần nhất</b>"]
    for r in rows:
        lines.append(
            f"{r['timestamp']}: {r['temp']}°C/{r['hum']}% | Rack {r['rack']}°C | {r['status']}"
        )
    return "\n".join(lines)


def format_incidents_text():
    rows = database.get_recent_incidents(limit=5)
    if not rows:
        return "Chưa có sự cố nào được ghi nhận."
    icon = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "ℹ️"}
    lines = ["🧾 <b>5 sự cố gần nhất</b>"]
    for r in rows:
        lines.append(f"{icon.get(r['severity'], 'ℹ️')} {r['timestamp']}: {r['message']}")
    return "\n".join(lines)


def handle_telegram_command(chat_id, text):
    cmd = text.strip().split()[0].lower() if text.strip() else ""

    if cmd in ("/start", "/help"):
        send_telegram_message(chat_id, TELEGRAM_HELP_TEXT)
    elif cmd == "/status":
        send_telegram_message(chat_id, format_status_text())
    elif cmd == "/hardware":
        send_telegram_message(chat_id, format_hardware_text())
    elif cmd == "/history":
        send_telegram_message(chat_id, format_history_text())
    elif cmd == "/incidents":
        send_telegram_message(chat_id, format_incidents_text())
    elif cmd == "/fan_on":
        pi_servo.set_manual("VENT_OPEN")
        database.insert_incident("INFO", "Dieu khien qua Telegram: fan_on (quat toi da)")
        send_telegram_message(chat_id, "🌀 Đã bật quạt tối đa (chế độ thủ công).")
    elif cmd == "/fan_off":
        pi_servo.set_manual("VENT_CLOSE")
        database.insert_incident("INFO", "Dieu khien qua Telegram: fan_off (tat quat)")
        send_telegram_message(chat_id, "🛑 Đã tắt quạt (chế độ thủ công).")
    elif cmd == "/fan_auto":
        pi_servo.set_manual("VENT_AUTO")
        database.insert_incident("INFO", "Dieu khien qua Telegram: fan_auto")
        send_telegram_message(chat_id, "✅ Đã trả quạt về chế độ tự động theo nhiệt độ.")
    elif cmd == "/mute":
        ok, msg = send_command_to_arduino("ALARM_OFF")
        database.insert_incident("INFO", "Dieu khien qua Telegram: mute coi")
        send_telegram_message(chat_id, ("🔇 " + msg) if ok else ("⚠️ " + msg))
    elif cmd == "/rfid":
        uid = "A1B2C3D4"
        staff = RFID_DIRECTORY.get(uid, f"Khach vang lai ({uid})")
        database.insert_rfid_access(uid, staff, "QUET THE VAO PHONG (demo qua Telegram)")
        database.insert_incident("INFO", f"Nhan su [{staff}] vua mo khoa vao phong Server (demo Telegram).")
        send_telegram_message(chat_id, f"🪪 Demo quẹt thẻ: {staff} ({uid}) vừa vào phòng.")
    else:
        send_telegram_message(chat_id, "Không hiểu lệnh. Gửi /help để xem danh sách lệnh.")


def telegram_bot_loop():
    """Long-polling getUpdates - lang nghe lenh tu Telegram, chi chap nhan tu TELEGRAM_CHAT_ID."""
    offset = 0
    log.info("Telegram bot (2 chieu) da khoi dong, chi nhan lenh tu chat_id=%s", TELEGRAM_CHAT_ID)
    while True:
        try:
            params = urllib.parse.urlencode({"timeout": 25, "offset": offset})
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?{params}"
            with urllib.request.urlopen(url, timeout=35) as resp:
                payload = json.loads(resp.read().decode("utf-8"))

            for update in payload.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text") or ""
                if not text:
                    continue

                if chat_id != str(TELEGRAM_CHAT_ID):
                    log.warning("Tu choi lenh Telegram tu chat_id khong duoc phep: %s (text=%r)", chat_id, text)
                    send_telegram_message(chat_id, "⛔ Bạn không có quyền điều khiển hệ thống này.")
                    continue

                log.info("Telegram command tu chu he thong: %r", text)
                handle_telegram_command(chat_id, text)
        except Exception as exc:
            log.error("Telegram bot loop loi: %s", exc)
            time.sleep(5)


# --- FLASK API ROUTES ---

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data/current", methods=["GET"])
def api_current():
    with data_lock:
        return jsonify(latest_telemetry)


@app.route("/api/data/history", methods=["GET"])
def api_history():
    return jsonify(database.get_history_logs(limit=20))


@app.route("/api/incidents", methods=["GET"])
def api_incidents():
    return jsonify(database.get_recent_incidents(limit=10))


@app.route("/api/hardware", methods=["GET"])
def api_hardware():
    with data_lock:
        snapshot = dict(latest_telemetry)
    return jsonify(build_hardware_status(snapshot))


@app.route("/api/db/stats", methods=["GET"])
def api_db_stats():
    return jsonify(database.get_db_stats())


@app.route("/api/rfid", methods=["GET", "POST"])
def api_rfid():
    """API doc danh sach ra vao hoac ghi nhan quet the RFID moi"""
    if request.method == "GET":
        return jsonify(database.get_recent_access_logs(limit=8))

    data = request.get_json(silent=True) or {}
    uid = str(data.get("uid", "A1B2C3D4")).upper()
    staff = RFID_DIRECTORY.get(uid, f"Khach vang lai ({uid})")
    database.insert_rfid_access(uid, staff, "QUET THE VAO PHONG")
    database.insert_incident("INFO", f"Nhan su [{staff}] vua mo khoa vao phong Server.")
    log.info("RFID scan: uid=%s staff=%s", uid, staff)
    return jsonify({"success": True, "uid": uid, "staff": staff})


@app.route("/api/control", methods=["POST"])
def api_control():
    data = request.get_json(silent=True) or {}
    cmd = str(data.get("command", "")).strip().upper()
    if cmd not in VALID_COMMANDS:
        log.warning("Tu choi lenh dieu khien khong hop le: %r", cmd)
        return jsonify({"success": False, "message": "Lenh khong hop le!"}), 400

    if cmd in ("VENT_OPEN", "VENT_CLOSE", "VENT_AUTO"):
        # Servo (quat) do Raspberry Pi tu quay qua GPIO18 - xu ly truc tiep,
        # KHONG gui xuong Arduino (Arduino khong con servo).
        pi_servo.set_manual(cmd)
        database.insert_incident("INFO", f"Quan tri vien gui lenh dieu khien quat (Pi GPIO18): {cmd}")
        return jsonify({"success": True, "message": f"Da thuc thi lenh '{cmd}' tren quat (Raspberry Pi)."})

    # ALARM_OFF van gui qua Serial de Arduino tat coi tai cho
    ok, msg = send_command_to_arduino(cmd)
    if ok:
        database.insert_incident("INFO", f"Quan tri vien gui lenh dieu khien tu xa: {cmd}")
    return jsonify({"success": ok, "message": msg})


if __name__ == "__main__":
    log.info("=== Smart Server Room Monitoring Gateway dang khoi dong ===")
    database.init_db()
    t = threading.Thread(target=serial_worker, daemon=True)
    t.start()
    if TELEGRAM_ENABLED:
        threading.Thread(target=telegram_bot_loop, daemon=True).start()
    else:
        log.warning("Telegram chua cau hinh (thieu telegram_secrets.py) - bot 2 chieu se khong chay")
    log.info("Web Dashboard san sang tai: http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
