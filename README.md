# iot-smart-server-room-monitoring
Smart Server Room Monitoring System using Arduino Uno &amp; Raspberry Pi 3B+. Features environmental sensing (DHT11, LDR), proximity door access (HC-SR04, Servo), and a Flask Web Dashboard with SQLite logging.

# PHẦN 1: SƠ ĐỒ ĐẤU DÂY DẠNG BẢNG & TEXT GRAPH

### 1. Bảng phân bổ chân kết nối (Pinout Matrix)
Hệ thống sử dụng chung thanh cấp nguồn (Power Rails) trên Breadboard: Nối chân **5V** của Arduino vào hàng **Dương (+)**, chân **GND** của Arduino vào hàng **Âm (-)**.

| STT | Linh kiện | Chân trên linh kiện | Chân trên Arduino Uno | Ghi chú kỹ thuật / Linh kiện phụ trợ |
| :--- | :--- | :--- | :--- | :--- |
| 1 | **DHT11** | VCC | 5V (Breadboard Rail) | Cấp nguồn 5V DC |
| | | GND | GND (Breadboard Rail)| Nối Mass chung |
| | | DATA | **Digital Pin 2** | Dùng trở kéo lên 10kΩ lên 5V (nếu dùng module 3 chân thì bỏ qua trở ngoài) |
| 2 | **LM35** | Chân 1 (Vs - Nhìn mặt phẳng) | 5V (Breadboard Rail) | Cấp nguồn |
| | | Chân 2 (Vout - Giữa) | **Analog Pin A0** | Điện áp ra: 10mV/°C |
| | | Chân 3 (GND - Phải) | GND (Breadboard Rail)| Nối Mass chung |
| 3 | **Quang trở (LDR)**| Chân 1 | 5V (Breadboard Rail) | Cầu phân áp phát hiện mở cửa tủ Rack |
| | | Chân 2 | **Analog Pin A1** | Điểm giữa nối tiếp với Điện trở 10kΩ xuống GND |
| 4 | **Biến trở 10kΩ** | Chân 1 (Bìa) | 5V (Breadboard Rail) | Căn chỉnh ngưỡng cảnh báo tại chỗ (Local Calibration) |
| | | Chân 2 (Gạt giữa) | **Analog Pin A2** | Dải điện áp: 0V - 5V tương ứng 25°C - 50°C |
| | | Chân 3 (Bìa) | GND (Breadboard Rail)| Nối Mass chung |
| 5 | **LCD1602 I2C** | VCC | 5V (Breadboard Rail) | Module I2C (PCF8574) |
| | | GND | GND (Breadboard Rail)| Nối Mass chung |
| | | SDA | **Analog Pin A4** (SDA) | Đường truyền dữ liệu I2C |
| | | SCL | **Analog Pin A5** (SCL) | Đường xung nhịp I2C |
| 6 | **Servo SG90** | Dây Đỏ (VCC) | 5V (Breadboard Rail) | Cửa thông gió làm mát tủ Rack |
| | | Dây Nâu/Đen (GND)| GND (Breadboard Rail)| Nối Mass chung |
| | | Dây Cam/Vàng (Signal)| **Digital Pin 9** (PWM) | Tín hiệu điều khiển góc quay 0° - 90° |
| 7 | **LED Xanh (Normal)**| Anode (+) | **Digital Pin 3** | Nối tiếp qua Điện trở 220Ω |
| | | Cathode (-) | GND (Breadboard Rail)| Nối Mass chung |
| 8 | **LED Vàng (Warning)**| Anode (+) | **Digital Pin 4** | Nối tiếp qua Điện trở 220Ω |
| | | Cathode (-) | GND (Breadboard Rail)| Nối Mass chung |
| 9 | **LED Đỏ (Critical)** | Anode (+) | **Digital Pin 5** | Nối tiếp qua Điện trở 220Ω |
| | | Cathode (-) | GND (Breadboard Rail)| Nối Mass chung |
| 10 | **Còi Buzzer** | Cực (+) | **Digital Pin 6** | Còi chủ động (Active Buzzer) |
| | | Cực (-) | GND (Breadboard Rail)| Nối Mass chung |

---

### 2. Sơ đồ mạch nguyên lý dạng Text/ASCII trực quan

```text
==================================== HỆ THỐNG NGUỒN CHUNG (BREADBOARD) ====================================
ARDUINO 5V  -------------------------[ + RAIL BREADBOARD (5V) ]--------------------------------------------
ARDUINO GND -------------------------[ - RAIL BREADBOARD (GND)]--------------------------------------------

==================================== KHỐI CẢM BIẾN (SENSORS) =============================================
[DHT11]      VCC ---------> Rail 5V
             GND ---------> Rail GND
             DATA --------> D2 (Arduino) --------[ R 10k (Pull-up) ]--------> Rail 5V

[LM35]       Vs  ---------> Rail 5V
             Vout --------> A0 (Arduino)  (Hotspot Sensor)
             GND ---------> Rail GND

[LDR Sensor] Chân 1 ------> Rail 5V
             Chân 2 ------> A1 (Arduino) ------->[ R 10k ]-------> Rail GND

[Biến trở]   Chân 1 ------> Rail 5V
(Threshold)  Chân Giữa ---> A2 (Arduino)
             Chân 3 ------> Rail GND

==================================== KHỐI XUẤT TÍN HIỆU & HIỂN THỊ =======================================
[LCD1602]    VCC ---------> Rail 5V
(I2C PCF8574)GND ---------> Rail GND
             SDA ---------> A4 (Arduino)
             SCL ---------> A5 (Arduino)

[SG90 Servo] VCC (Đỏ) ----> Rail 5V
(Cửa gió)    GND (Nâu) ---> Rail GND
             PWM (Cam) ---> D9 (Arduino)

[Đèn & Còi]  D3 (Arduino) ------[ R 220Ω ]----->|>| LED XANH (Normal)   -----> Rail GND
             D4 (Arduino) ------[ R 220Ω ]----->|>| LED VÀNG (Warning)  -----> Rail GND
             D5 (Arduino) ------[ R 220Ω ]----->|>| LED ĐỎ (Critical)   -----> Rail GND
             D6 (Arduino) ---------------------> (+) BUZZER (Còi báo)   -----> Rail GND

==================================== GIAO TIẾP VỚI GATEWAY ===============================================
[ARDUINO UNO] ==== (Cáp USB Type-A to Type-B) ==== [RASPBERRY PI 3B+ (Port /dev/ttyACM0 hoặc /dev/ttyUSB0)]
(Giao tiếp Serial an toàn tuyệt đối qua USB, cách ly điện áp, không lo xung đột 3.3V/5V)