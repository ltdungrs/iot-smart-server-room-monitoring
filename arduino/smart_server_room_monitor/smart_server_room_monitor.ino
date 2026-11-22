/**
 * HỆ THỐNG GIÁM SÁT PHÒNG SERVER THÔNG MINH (SMART SERVER ROOM MONITORING)
 * Phần cứng: Arduino Uno R3 + DHT11 + LM35 + LDR + Biến trở + LCD I2C + Servo + HC-05
 * Chế độ Demo nhiệt độ phòng: Quá 30.0°C coi như vượt 60°C -> Buzzer + LED Đỏ + Servo quay liên tục
 */

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>
#include <Servo.h>
#include <SoftwareSerial.h>

// --- 1. ĐỊNH NGHĨA CHÂN THEO ĐÚNG SƠ ĐỒ MỚI ---
#define PIN_DHT        2    // D2: DHT11
#define DHTTYPE        DHT11
#define PIN_ROOM_LED   3    // D3: Đèn LED chiếu sáng phòng Server (Điều khiển bởi LDR)
#define PIN_LED_GREEN  5    // D5: LED Xanh (Normal)
#define PIN_LED_YELLOW 6    // D6: LED Vàng (Warning)
#define PIN_LED_RED    7    // D7: LED Đỏ (Critical)
#define PIN_BUZZER     8    // D8: Còi Buzzer
#define PIN_SERVO      9    // D9: Servo SG90 mô phỏng quạt làm mát
#define PIN_BT_RX      10   // D10: Nối chân TXD của HC-05
#define PIN_BT_TX      11   // D11: Nối chân RXD của HC-05

#define PIN_LM35       A0   // A0: Cảm biến điểm nóng tủ Rack
#define PIN_LDR        A1   // A1: Quang trở + 10k (Bật đèn phòng / phát hiện mở cửa)
#define PIN_POT        A2   // A2: Biến trở căn chỉnh ngưỡng demo

// --- 2. KHỞI TẠO ĐỐI TƯỢNG ---
DHT dht(PIN_DHT, DHTTYPE);
LiquidCrystal_I2C lcd(0x27, 16, 2); // Đổi 0x3F nếu LCD không lên chữ
Servo fanServo;
SoftwareSerial btSerial(PIN_BT_RX, PIN_BT_TX); // RX, TX Bluetooth

// --- 3. BIẾN THỜI GIAN NON-BLOCKING (MILLIS) ---
unsigned long prevSensorMillis = 0;
const unsigned long SENSOR_INTERVAL = 2000; // Chu kỳ đọc & gửi dữ liệu: 2000ms

unsigned long prevLcdMillis = 0;
const unsigned long LCD_INTERVAL = 800;     // Chu kỳ làm mới LCD: 800ms

unsigned long prevServoMillis = 0;
unsigned long prevBlinkMillis = 0;
bool blinkState = false;

// --- 4. BIẾN TRẠNG THÁI HỆ THỐNG ---
float roomTemp = 27.0;
float roomHum = 60.0;
float rackTemp = 28.0;
float demoThreshold = 30.0; // Ngưỡng chuẩn Demo = 30.0°C (tương đương 60°C thực tế)
bool isRoomLightOn = false;
bool isDoorOpen = false;
String currentStatus = "NORMAL";

// Biến điều khiển Servo quay liên tục (Quạt)
int servoAngle = 0;
int servoDirection = 1; // 1: tăng góc, -1: giảm góc
int fanSpeedMode = 0;   // 0: Tắt, 1: Quay chậm (Warning), 2: Quay nhanh không dừng (Critical)

// Điều khiển từ xa qua Raspberry Pi / Bluetooth
bool manualOverride = false;
int manualFanMode = 0;
bool alarmSilenced = false;

String usbCmdBuffer = "";
String btCmdBuffer = "";

void setup() {
  // Khởi tạo đồng thời cả USB Serial (D0, D1) và Bluetooth HC-05 (D10, D11)
  Serial.begin(9600);
  btSerial.begin(9600);

  // Cấu hình chân Output
  pinMode(PIN_ROOM_LED, OUTPUT);
  pinMode(PIN_LED_BUILTIN_CHECK(), OUTPUT); // Dùng luôn LED trên bo mạch (D13) báo đèn phòng
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);

  digitalWrite(PIN_ROOM_LED, LOW);
  digitalWrite(LED_BUILTIN, LOW);
  digitalWrite(PIN_LED_GREEN, LOW);
  digitalWrite(PIN_LED_YELLOW, LOW);
  digitalWrite(PIN_LED_RED, LOW);
  digitalWrite(PIN_BUZZER, LOW);

  // Khởi động Servo
  fanServo.attach(PIN_SERVO);
  fanServo.write(0);

  // Khởi động cảm biến & LCD
  dht.begin();
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("SERVER MONITOR");
  lcd.setCursor(0, 1);
  lcd.print("DEMO >=30C FAN!");
}

int PIN_LED_BUILTIN_CHECK() { return LED_BUILTIN; }

void loop() {
  unsigned long currentMillis = millis();

  // 1. Lắng nghe lệnh từ cả cổng USB và Bluetooth HC-05
  processSerialCommands();

  // 2. Đọc cảm biến & gửi gói tin JSON mỗi 2 giây
  if (currentMillis - prevSensorMillis >= SENSOR_INTERVAL) {
    prevSensorMillis = currentMillis;
    readAllSensors();
    evaluateSystemLogic();
    sendTelemetryJson();
  }

  // 3. Cập nhật LCD1602 mỗi 800ms
  if (currentMillis - prevLcdMillis >= LCD_INTERVAL) {
    prevLcdMillis = currentMillis;
    updateLcdDisplay();
  }

  // 4. Điều khiển đèn cảnh báo, còi và Servo quay liên tục (Non-blocking)
  handleAlertsAndLeds(currentMillis);
  handleFanServoContinuous(currentMillis);
}

/**
 * Đọc DHT11, LM35, Quang trở LDR và Biến trở
 */
void readAllSensors() {
  // Đọc DHT11 (D2)
  float h = dht.readHumidity();
  float t = dht.readTemperature();
  if (!isnan(h) && !isnan(t)) {
    roomHum = h;
    roomTemp = t;
  }

  // Đọc LM35 (A0): Lấy trung bình 10 mẫu để chống nhiễu ADC
  long sumLm35 = 0;
  for (int i = 0; i < 10; i++) {
    sumLm35 += analogRead(PIN_LM35);
  }
  float avgLm35 = (float)sumLm35 / 10.0;
  rackTemp = (avgLm35 * 5000.0 / 1024.0) / 10.0;

  // Đọc Biến trở (A2): Cho phép chỉnh ngưỡng demo từ 26.0°C đến 34.0°C (Mức giữa = 30.0°C)
  int potRaw = analogRead(PIN_POT);
  demoThreshold = 26.0 + ((float)potRaw / 1023.0) * 8.0;

  // Đọc Quang trở LDR (A1): Điều khiển Đèn LED phòng Server & phát hiện mở cửa
  // Nếu che tối (< 450): Bật đèn LED phòng Server (D3 + D13)
  // Nếu sáng mạnh (>= 450): Tắt đèn phòng, ghi nhận có ánh sáng / cửa mở
  int ldrVal = analogRead(PIN_LDR);
  if (ldrVal < 450) {
    isRoomLightOn = true;
    isDoorOpen = false;
    digitalWrite(PIN_ROOM_LED, HIGH);
    digitalWrite(LED_BUILTIN, HIGH);
  } else {
    isRoomLightOn = false;
    isDoorOpen = true;
    digitalWrite(PIN_ROOM_LED, LOW);
    digitalWrite(LED_BUILTIN, LOW);
  }
}

/**
 * Logic xử lý 3 mức cảnh báo & Quạt Servo
 * Quy ước Demo: Nhiệt độ tủ Rack > 30.0°C (hoặc > ngưỡng biến trở) coi như > 60°C -> Quạt quay nhanh không dừng!
 */
void evaluateSystemLogic() {
  // Mức CRITICAL: Tủ Rack nóng vượt ngưỡng Demo (> 30.0°C hoặc > demoThreshold)
  if (rackTemp > 30.0 || rackTemp > demoThreshold) {
    currentStatus = "CRITICAL";
    if (!manualOverride) {
      fanSpeedMode = 2; // Quay nhanh liên tục không dừng
    }
  } 
  // Mức WARNING: Nhiệt độ phòng hoặc tủ Rack tiệm cận ngưỡng (từ ngưỡng - 2°C đến ngưỡng)
  else if (rackTemp >= (demoThreshold - 2.0) || roomTemp >= demoThreshold) {
    currentStatus = "WARNING";
    if (!manualOverride) {
      fanSpeedMode = 1; // Quạt quay tốc độ trung bình / hé gió
    }
  } 
  // Mức NORMAL: An toàn
  else {
    currentStatus = "NORMAL";
    alarmSilenced = false; // Tự mở lại còi cho lần sự cố sau
    if (!manualOverride) {
      fanSpeedMode = 0; // Tắt quạt
    }
  }

  if (manualOverride) {
    fanSpeedMode = manualFanMode;
  }
}

/**
 * Điều khiển Servo SG90 quay qua lại không dừng để mô phỏng Quạt tản nhiệt (Non-blocking)
 */
void handleFanServoContinuous(unsigned long currentMillis) {
  if (fanSpeedMode == 0) {
    // Tắt quạt: Đưa về vị trí 0°
    if (servoAngle != 0) {
      servoAngle = 0;
      fanServo.write(0);
    }
    return;
  }

  // Tốc độ cập nhật bước quay: Mode 2 (Critical >30C) quay cực nhanh (12ms/bước), Mode 1 chậm (35ms/bước)
  unsigned long stepInterval = (fanSpeedMode == 2) ? 12 : 35;
  int stepSize = (fanSpeedMode == 2) ? 12 : 5;

  if (currentMillis - prevServoMillis >= stepInterval) {
    prevServoMillis = currentMillis;
    servoAngle += (servoDirection * stepSize);

    if (servoAngle >= 180) {
      servoAngle = 180;
      servoDirection = -1; // Đảo chiều quay liên tục không dừng
    } else if (servoAngle <= 0) {
      servoAngle = 0;
      servoDirection = 1;
    }
    fanServo.write(servoAngle);
  }
}

/**
 * Điều khiển LED Xanh (D5), Vàng (D6), Đỏ (D7) và Còi Buzzer (D8)
 */
void handleAlertsAndLeds(unsigned long currentMillis) {
  if (currentStatus == "NORMAL") {
    digitalWrite(PIN_LED_GREEN, HIGH);
    digitalWrite(PIN_LED_YELLOW, LOW);
    digitalWrite(PIN_LED_RED, LOW);
    digitalWrite(PIN_BUZZER, LOW);
  } 
  else if (currentStatus == "WARNING") {
    digitalWrite(PIN_LED_GREEN, LOW);
    digitalWrite(PIN_LED_YELLOW, HIGH);
    digitalWrite(PIN_LED_RED, LOW);

    if (!alarmSilenced && (currentMillis % 1200 < 150)) {
      digitalWrite(PIN_BUZZER, HIGH); // Bíp cảnh báo nhẹ
    } else {
      digitalWrite(PIN_BUZZER, LOW);
    }
  } 
  else if (currentStatus == "CRITICAL") {
    digitalWrite(PIN_LED_GREEN, LOW);
    digitalWrite(PIN_LED_YELLOW, LOW);

    // Nhấp nháy LED đỏ & Còi hú liên tục chu kỳ 180ms
    if (currentMillis - prevBlinkMillis >= 180) {
      prevBlinkMillis = currentMillis;
      blinkState = !blinkState;
      digitalWrite(PIN_LED_RED, blinkState ? HIGH : LOW);
      if (!alarmSilenced) {
        digitalWrite(PIN_BUZZER, blinkState ? HIGH : LOW);
      } else {
        digitalWrite(PIN_BUZZER, LOW);
      }
    }
  }
}

/**
 * Hiển thị thông số lên LCD1602 I2C
 */
void updateLcdDisplay() {
  // Dòng 1: T:28C H:60% R:31C (R là Rack LM35)
  lcd.setCursor(0, 0);
  char line0[17];
  snprintf(line0, sizeof(line0), "T:%02dC H:%02d%% R:%02dC", (int)roomTemp, (int)roomHum, (int)rackTemp);
  lcd.print(line0);

  // Dòng 2: L:ON/OF CRITICAL / NORMAL
  lcd.setCursor(0, 1);
  char line1[17];
  const char* lightStr = isRoomLightOn ? "L:ON " : "L:OFF";
  snprintf(line1, sizeof(line1), "%s  %-9s", lightStr, currentStatus.c_str());
  lcd.print(line1);
}

/**
 * Đóng gói JSON gửi đồng thời lên cả USB Serial (D0,D1) và Bluetooth HC-05 (D10,D11)
 */
void sendTelemetryJson() {
  String json = "{\"temp\":" + String(roomTemp, 1) +
                ",\"hum\":" + String(roomHum, 1) +
                ",\"rack\":" + String(rackTemp, 1) +
                ",\"door\":\"" + String(isDoorOpen ? "OPEN" : "CLOSED") + "\"" +
                ",\"light\":\"" + String(isRoomLightOn ? "ON" : "OFF") + "\"" +
                ",\"thresh\":" + String(demoThreshold, 1) +
                ",\"status\":\"" + currentStatus + "\"" +
                ",\"servo\":" + String(fanSpeedMode == 0 ? 0 : (fanSpeedMode == 1 ? 50 : 100)) + "}";

  Serial.println(json);   // Gửi qua cáp USB
  btSerial.println(json); // Gửi qua Bluetooth HC-05
}

/**
 * Lắng nghe lệnh điều khiển từ cả 2 kênh Serial
 */
void processSerialCommands() {
  // Kênh 1: USB Serial
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (usbCmdBuffer.length() > 0) {
        executeCommand(usbCmdBuffer);
        usbCmdBuffer = "";
      }
    } else {
      usbCmdBuffer += c;
    }
  }
  // Kênh 2: Bluetooth HC-05
  while (btSerial.available() > 0) {
    char c = (char)btSerial.read();
    if (c == '\n' || c == '\r') {
      if (btCmdBuffer.length() > 0) {
        executeCommand(btCmdBuffer);
        btCmdBuffer = "";
      }
    } else {
      btCmdBuffer += c;
    }
  }
}

void executeCommand(String cmd) {
  cmd.trim();
  if (cmd == "VENT_OPEN") {
    manualOverride = true;
    manualFanMode = 2; // Ép quạt quay hết công suất
  } else if (cmd == "VENT_CLOSE") {
    manualOverride = true;
    manualFanMode = 0; // Ép dừng quạt
  } else if (cmd == "VENT_AUTO") {
    manualOverride = false; // Trả về chế độ tự động theo cảm biến
  } else if (cmd == "ALARM_OFF") {
    alarmSilenced = true;
    digitalWrite(PIN_BUZZER, LOW);
  }
}