# Smart Server Room Monitoring

Hệ thống giám sát phòng server dùng **Arduino Uno** (đọc cảm biến, cảnh báo tại chỗ) kết hợp **Raspberry Pi 3B+** làm gateway (web dashboard, lưu SQLite, bot Telegram). Hệ thống theo dõi nhiệt độ/độ ẩm phòng, điểm nóng tủ rack, ánh sáng phòng; cảnh báo 3 mức **Normal / Warning / Critical**; tự bật quạt qua module relay khi vượt ngưỡng; và cho phép điều khiển từ xa qua dashboard web hoặc Telegram.

## Thành viên nhóm

| Họ và tên | MSSV |
| :--- | :--- |
| Lâm Quốc Đạt | 25MS23329 |
| Nguyễn Xuân Trường | 25MS23320 |
| Lê Trung Dũng | 25MS23335 |
| Trương Nguyễn Thắng Lợi | 25MS23330 |
| Lê Văn Nguyên | 25MS23324 |

---

## 1. Kiến trúc hệ thống

```text
┌──────────────────────────── ARDUINO UNO ────────────────────────────┐
│ Cảm biến:  DHT11 (D2) · LM35 (A0) · Quang trở (A1) · Biến trở (A2) │
│ Hiển thị:  LCD1602 I2C (A4/A5)                                     │
│ Cơ cấu:    Đèn phòng (D3) · Relay quạt (D5) · Buzzer (D8)          │
│ Logic:     Đọc cảm biến mỗi 2s, tính 3 mức cảnh báo, bật relay/còi │
└───────────────────┬────────────────────────────────┬───────────────┘
                    │ USB Serial 9600 (chính)        │ HC-05 (D10/D11, dự phòng)
                    ▼                                ▼
┌──────────────────────── RASPBERRY PI 3B+ (Gateway) ─────────────────┐
│ app.py      : Flask + luồng đọc Serial, tự dò /dev/ttyACM*,        │
│               /dev/ttyUSB*, /dev/rfcomm0 và tự kết nối lại         │
│ Phân tích   : Điểm sương (Magnus-Tetens), tốc độ tăng nhiệt,       │
│               phát hiện LM35 hở mạch                               │
│ database.py : SQLite (logs / incidents / access_logs)              │
│ Dashboard   : http://<ip-pi>:5000 — số liệu, biểu đồ, điều khiển   │
│ Telegram    : đẩy cảnh báo + nhận lệnh điều khiển 2 chiều          │
└─────────────────────────────────────────────────────────────────────┘
```

Arduino **tự hoạt động độc lập**: kể cả khi mất kết nối với Pi, nó vẫn đọc cảm biến, hiển thị LCD, bật relay quạt và kêu còi khi quá nhiệt. Pi đóng vai trò giám sát, lưu trữ và điều khiển từ xa.

---

## 2. Sơ đồ đấu dây

### 2.1. Bảng phân bổ chân (Pinout Matrix)

Dùng chung thanh nguồn trên breadboard: **5V** Arduino → hàng **(+)**, **GND** Arduino → hàng **(−)**.

| Chân Arduino | Linh kiện | Ghi chú kỹ thuật |
| :--- | :--- | :--- |
| **D2** | DHT11 — DATA | Nhiệt độ & độ ẩm phòng. Trở kéo lên 10kΩ lên 5V (module 3 chân thì bỏ qua) |
| **D3** | Đèn LED phòng Server (+) | Qua trở 220Ω. Tự bật theo quang trở, hoặc ép tay từ dashboard/Telegram. LED tích hợp D13 sáng đồng bộ |
| **D4** | LED Xanh — Normal (+) | Qua trở 220Ω. *Đang tắt trong code (`USE_STATUS_LEDS = false`)* |
| **D5** | Module Relay — chân IN | Đóng/mở quạt làm mát. Quạt dùng **nguồn riêng**, relay chỉ đóng tiếp điểm |
| **D6** | LED Vàng — Warning (+) | Qua trở 220Ω. *Đang tắt trong code* |
| **D7** | LED Đỏ — Critical (+) | Qua trở 220Ω. *Đang tắt trong code* |
| **D8** | Buzzer (+) | Còi chủ động (active buzzer) |
| **D9** | *(để trống)* | Trước đây dùng cho Servo |
| **D10** | HC-05 — TXD | `SoftwareSerial` RX |
| **D11** | HC-05 — RXD | `SoftwareSerial` TX. Nên qua cầu chia áp 1kΩ/2kΩ để hạ 5V → 3.3V |
| **A0** | LM35 — Vout (chân giữa) | Điểm nóng tủ rack, 10mV/°C. Chân 1 → 5V, chân 3 → GND |
| **A1** | Quang trở — điểm giữa cầu chia áp | 5V → LDR → **A1** → trở 10kΩ → GND |
| **A2** | Biến trở 10kΩ — chân giữa | Chỉnh ngưỡng Critical 30–36°C. Hai chân bìa nối 5V và GND |
| **A4 / A5** | LCD1602 I2C — SDA / SCL | Module PCF8574, địa chỉ `0x27` (đổi `0x3F` nếu không lên chữ) |
| **D0 / D1** | USB Serial | Kết nối chính tới Raspberry Pi — **không cắm dây ngoài vào 2 chân này** |

### 2.2. Sơ đồ ASCII

```text
================= NGUỒN CHUNG (BREADBOARD) =================
ARDUINO 5V  ----------> [ + RAIL 5V  ]
ARDUINO GND ----------> [ - RAIL GND ]

================= KHỐI CẢM BIẾN ============================
[DHT11]      VCC -> 5V | GND -> GND | DATA -> D2 --[10k pull-up]--> 5V
[LM35]       Vs  -> 5V | GND -> GND | Vout -> A0
             (nhìn mặt phẳng: Trái = Vs, Giữa = Vout, Phải = GND)
[LDR 5528]   5V -> LDR -> điểm giữa (A1) -> [10k] -> GND
[Biến trở]   5V -> chân bìa | chân giữa -> A2 | chân bìa -> GND

================= KHỐI HIỂN THỊ & CƠ CẤU ===================
[LCD1602]    VCC -> 5V | GND -> GND | SDA -> A4 | SCL -> A5
[Đèn phòng]  D3 --[220Ω]-->|>|-- LED --> GND
[Buzzer]     D8 -----------> (+) BUZZER --> GND
[RELAY]      VCC -> 5V | GND -> GND | IN -> D5
             COM/NO --> đóng ngắt mạch nguồn RIÊNG của quạt

================= TRUYỀN THÔNG =============================
[HC-05]      VCC -> 5V | GND -> GND | TXD -> D10
             RXD <-- [1k] <-- D11, điểm giữa --[2k]--> GND  (chia áp)
[USB]        ARDUINO UNO ==== cáp USB ==== RASPBERRY PI 3B+
             (/dev/ttyACM0 hoặc /dev/ttyUSB0 — cách ly điện áp an toàn)
```

> **Lưu ý về relay:** quạt phải dùng nguồn riêng, đi qua tiếp điểm COM/NO của relay. Module đang dùng là loại **active-LOW** (kích mức LOW mới đóng tiếp điểm) nên sketch đặt `RELAY_ACTIVE_LOW = true`. Nếu đổi sang module khác mà thấy 2 nút bật/tắt bị ngược nhau, chỉ cần đổi cờ này thành `false`.

---

## 3. Cấu trúc repo

```text
.
├── arduino/
│   └── smart_server_room_monitor/
│       └── smart_server_room_monitor.ino   # Firmware Arduino (non-blocking, millis())
├── raspberry_pi/
│   ├── app.py                   # Flask + luồng Serial + Telegram bot + API
│   ├── database.py              # SQLite: logs, incidents, access_logs
│   ├── templates/index.html     # Dashboard (Bootstrap dark + Chart.js)
│   ├── static/alert.mp3         # File cảnh báo giọng nói tiếng Việt
│   ├── telegram_secrets.example.py  # Mẫu cấu hình bot (copy → telegram_secrets.py)
│   ├── requirements.txt
│   └── run.sh
├── REQUIREMENT.md               # Đề bài & yêu cầu bài tập
└── README.md
```

File `raspberry_pi/telegram_secrets.py` (chứa token thật) và `iot_monitor.db`, `gateway.log` được **gitignore**, không đưa lên repo.

---

## 4. Logic cảnh báo

| Mức | Điều kiện | Hành động |
| :--- | :--- | :--- |
| **NORMAL** | Rack < (ngưỡng − 1.5°C) | Relay tắt quạt, còi tắt |
| **WARNING** | Rack ≥ (ngưỡng − 1.5°C), hoặc phòng ≥ ngưỡng | Relay **mở quạt**, còi kêu nhịp 100ms/320ms |
| **CRITICAL** | Rack > ngưỡng, hoặc phòng > (ngưỡng + 2°C) | Relay **mở quạt**, còi kêu, Telegram đẩy cảnh báo, dashboard phát âm thanh |

- **Ngưỡng Critical** chỉnh bằng biến trở A2 trong dải **30.0 – 36.0°C**. Theo đề bài, mốc 30°C được coi như tương đương >60°C trong tủ rack thật để demo được ở nhiệt độ phòng.
- **Chống nhấp nháy:** relay quạt giữ mở tối thiểu **10 giây**, còi kêu tối thiểu **2 giây** sau mỗi lần kích hoạt.
- **Đèn phòng (D3):** tự bật khi quang trở < **600** (tối), tắt khi ≥ **700** (sáng) — 2 ngưỡng lệch nhau (hysteresis) để đèn không chớp tắt ở vùng ranh giới. Xem giá trị `ldr` thô trên dashboard để tinh chỉnh: **tăng ngưỡng = nhạy hơn**.
- **Chống nhiễu LM35:** lấy trung bình 10 mẫu, bù theo điện áp nguồn thực tế (`readVcc()`), và Pi tự phát hiện giá trị dao động bất thường (dấu hiệu hở mạch/lỏng dây) rồi báo đỏ trên panel Hardware.

---

## 5. Giao thức Serial (Arduino ↔ Pi)

**Arduino → Pi**, mỗi 2 giây 1 dòng JSON (gửi song song qua USB Serial và HC-05):

```json
{"temp":27.4,"hum":58.0,"rack":29.1,"door":"CLOSED","light":"ON","ldr":412,"thresh":30.6,"status":"WARNING","fan":"ON"}
```

**Pi → Arduino**, mỗi lệnh 1 dòng kết thúc bằng `\n`:

| Lệnh | Tác dụng |
| :--- | :--- |
| `VENT_OPEN` | Ép mở relay — bật quạt |
| `VENT_CLOSE` | Ép đóng relay — tắt quạt |
| `VENT_AUTO` | Trả quạt về chế độ tự động theo nhiệt độ |
| `LIGHT_ON` / `LIGHT_OFF` | Ép bật / tắt đèn phòng |
| `LIGHT_AUTO` | Trả đèn về tự động theo quang trở |
| `ALARM_OFF` | Tắt còi báo động |

---

## 6. Dashboard web

Truy cập `http://<ip-raspberry-pi>:5000`

- **Thẻ số liệu real-time:** nhiệt độ/độ ẩm phòng, điểm nóng rack, điểm sương, tốc độ tăng nhiệt, trạng thái cửa/đèn, giá trị LDR thô, trạng thái relay quạt.
- **Thẻ trạng thái đổi màu** theo mức cảnh báo (xanh/vàng/đỏ nhấp nháy).
- **Biểu đồ Chart.js:** nhiệt độ phòng, nhiệt độ rack và điểm sương theo thời gian.
- **Điều khiển từ xa:** bật/tắt/auto quạt, bật/tắt/auto đèn phòng, tắt còi.
- **Cảnh báo bằng giọng nói:** bật qua nút ở header, phát file `static/alert.mp3` khi WARNING/CRITICAL, tối đa **1 lần mỗi 30 giây**. (Trình duyệt yêu cầu người dùng bấm nút 1 lần trước khi cho phép phát âm thanh.)
- **Panel Tình trạng Hardware:** liệt kê từng thiết bị theo chân, trạng thái OK / cảnh báo / lỗi — dùng để vừa giám sát vừa debug phần cứng.
- **Database ghi liên tục:** đếm số dòng của 3 bảng, nhấp nháy mỗi khi có bản ghi mới.
- **Nhật ký sự cố & kiểm soát ra vào (RFID demo).**

### API

| Endpoint | Method | Mô tả |
| :--- | :--- | :--- |
| `/` | GET | Trang dashboard |
| `/api/data/current` | GET | Số liệu hiện tại |
| `/api/data/history` | GET | 20 bản ghi gần nhất |
| `/api/incidents` | GET | 10 sự cố gần nhất |
| `/api/hardware` | GET | Trạng thái từng thiết bị theo chân |
| `/api/db/stats` | GET | Số dòng & ID mới nhất của từng bảng |
| `/api/rfid` | GET / POST | Đọc nhật ký ra vào / ghi nhận quẹt thẻ |
| `/api/control` | POST | `{"command": "VENT_OPEN"}` — gửi lệnh xuống Arduino |

---

## 7. Bot Telegram

Giám sát và điều khiển song song với dashboard. Bot dùng **long-polling**, chỉ nhận lệnh từ `CHAT_ID` đã cấu hình — mọi chat khác bị từ chối và ghi log.

| Lệnh | Mô tả |
| :--- | :--- |
| `/help` | Danh sách lệnh |
| `/status` | Số liệu hiện tại |
| `/hardware` | Tình trạng kết nối từng thiết bị |
| `/history` | 5 lần đo gần nhất |
| `/incidents` | 5 sự cố gần nhất |
| `/fan_on` · `/fan_off` · `/fan_auto` | Điều khiển relay quạt |
| `/light_on` · `/light_off` · `/light_auto` | Điều khiển đèn phòng |
| `/mute` | Tắt còi báo động |
| `/rfid` | Demo quẹt thẻ RFID |

Ngoài ra bot **tự đẩy cảnh báo** khi hệ thống chuyển sang `CRITICAL` (kèm nhiệt độ, thời gian) và một tin báo khi đã hồi phục về `NORMAL` — chỉ gửi tại thời điểm chuyển trạng thái, không spam.

---

## 8. Cơ sở dữ liệu (`iot_monitor.db`)

| Bảng | Nội dung |
| :--- | :--- |
| `logs` | Mỗi bản ghi 2s: `temp`, `hum`, `rack`, `dew_point`, `rise_rate`, `door`, `light`, `status`, `servo_state` |
| `incidents` | Nhật ký sự cố tự động: đổi trạng thái, mất/khôi phục kết nối Serial, lệnh điều khiển từ xa |
| `access_logs` | Nhật ký quẹt thẻ RFID vào phòng (`card_uid`, `staff_name`, `action`) |

---

## 9. Hướng dẫn chạy

### 9.1. Nạp firmware Arduino

Cài 3 thư viện trong Arduino IDE: **DHT sensor library**, **LiquidCrystal I2C**, và **Adafruit Unified Sensor** (phụ thuộc của DHT). Mở `arduino/smart_server_room_monitor/smart_server_room_monitor.ino`, chọn board **Arduino Uno**, rồi Upload.

Các cờ cấu hình ở đầu sketch:

| Cờ | Mặc định | Ý nghĩa |
| :--- | :--- | :--- |
| `RELAY_ACTIVE_LOW` | `true` | Module đang dùng là loại kích mức LOW. Đổi `false` nếu thấy 2 nút bật/tắt bị ngược |
| `USE_STATUS_LEDS` | `false` | Đổi `true` để dùng lại 3 LED xanh/vàng/đỏ |
| `USE_PASSIVE_BUZZER` | `false` | Đổi `true` nếu dùng còi thụ động (phát tần số 1200Hz) |
| `LDR_LIGHT_ON_THRESHOLD` | `600` | Ngưỡng ADC bật đèn (tăng = nhạy hơn) |
| `LDR_LIGHT_OFF_THRESHOLD` | `700` | Ngưỡng ADC tắt đèn |

### 9.2. Chạy gateway trên Raspberry Pi

```bash
# Cài thư viện (Raspbian Bookworm đã có sẵn Flask & pyserial)
pip3 install -r raspberry_pi/requirements.txt

# Cấu hình Telegram (tuỳ chọn — bỏ qua thì bot không chạy, phần còn lại vẫn hoạt động)
cp raspberry_pi/telegram_secrets.example.py raspberry_pi/telegram_secrets.py
# → điền BOT_TOKEN (lấy từ @BotFather) và CHAT_ID (xem /getUpdates)

# Chạy
cd raspberry_pi && python3 app.py
```

Cắm cáp USB từ Arduino sang Pi — gateway tự dò cổng và kết nối lại trong vòng 3 giây nếu rút/cắm lại. Mở dashboard tại `http://<ip-raspberry-pi>:5000`.

Mọi tiến trình đều ghi log ra màn hình kèm timestamp (kết nối Serial, từng bản ghi cảm biến, lệnh điều khiển, cảnh báo Telegram, lỗi phần cứng).
