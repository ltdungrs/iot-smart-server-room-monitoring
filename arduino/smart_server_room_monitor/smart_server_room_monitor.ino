/**
 * HỆ THỐNG GIÁM SÁT PHÒNG SERVER THÔNG MINH (SMART SERVER ROOM MONITORING)
 * ĐÃ FIX:
 *  - Chống nhảy nhiệt ảo LM35 bằng hàm đo điện áp thực tế readVcc()
 *  - Khóa ngưỡng chuẩn Demo: < 28.5°C = NORMAL (26°C không bao giờ báo động giả)
 *    28.5°C - 30.0°C = WARNING | > 30.0°C (coi như >60°C) = CRITICAL
 *  - Servo (D9) chạy tối thiểu 10 giây | Buzzer (D8) kêu vừa tai tối thiểu 2 giây
 */

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>
#include <Servo.h>
#include <SoftwareSerial.h>

#define USE_PASSIVE_BUZZER false

// --- 1. ĐỊNH NGHĨA CHÂN ---
#define PIN_DHT        2    // D2: DHT11
#define DHTTYPE        DHT11
#define PIN_ROOM_LED   3    // D3: Đèn LED phòng Server (Điều khiển bởi LDR)
#define PIN_LED_GREEN  5    // D5: LED Xanh (Normal)
#define PIN_LED_YELLOW 6    // D6: LED Vàng (Warning)
#define PIN_LED_RED    7    // D7: LED Đỏ (Critical)
#define PIN_BUZZER     8    // D8: Còi Buzzer
#define PIN_SERVO      9    // D9: Servo SG90 mô phỏng quạt
#define PIN_BT_RX      10   // D10: TXD của HC-05
#define PIN_BT_TX      11   // D11: RXD của HC-05

#define PIN_LM35       A0   // A0: Cảm biến điểm nóng tủ Rack
#define PIN_LDR        A1   // A1: Quang trở + trở 10k
#define PIN_POT        A2   // A2: Biến trở chỉnh ngưỡng (30°C - 36°C)

// --- 2. KHỞI TẠO ĐỐI TƯỢNG ---
DHT dht(PIN_DHT, DHTTYPE);
LiquidCrystal_I2C lcd(0x27, 16, 2);
Servo fanServo;
SoftwareSerial btSerial(PIN_BT_RX, PIN_BT_TX);

// --- 3. BIẾN ĐỊNH THỜI NON-BLOCKING ---
unsigned long prevSensorMillis = 0;
const unsigned long SENSOR_INTERVAL = 2000;

unsigned long prevLcdMillis = 0;
const unsigned long LCD_INTERVAL = 800;

unsigned long prevServoMillis = 0;
unsigned long prevBlinkMillis = 0;
bool blinkState = false;

const unsigned long MIN_SERVO_RUN_MS  = 10000UL; // Quạt chạy tối thiểu 10 giây
const unsigned long MIN_BUZZER_RUN_MS = 2000UL;  // Còi kêu tối thiểu 2 giây

bool isFanLatched = false;
unsigned long fanLatchStartMillis = 0;
int latchedFanMode = 0;

bool isBuzzerLatched = false;
unsigned long buzzerLatchStartMillis = 0;

// --- 4. BIẾN TRẠNG THÁI ---
float roomTemp = 26.0;
float roomHum = 60.0;
float rackTemp = 26.0;
float demoThreshold = 30.0; // Ngưỡng tối thiểu 30.0°C (Chỉnh được từ 30°C -> 36°C)
bool isRoomLightOn = false;
bool isDoorOpen = false;
String currentStatus = "NORMAL";

int servoAngle = 0;
int servoDirection = 1;
int fanSpeedMode = 0;

bool manualOverride = false;
int manualFanMode = 0;
bool alarmSilenced = false;

String usbCmdBuffer = "";
String btCmdBuffer = "";

void setup() {
  Serial.begin(9600);
  btSerial.begin(9600);

  pinMode(PIN_ROOM_LED, OUTPUT);
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);

  digitalWrite(PIN_ROOM_LED, LOW);
  digitalWrite(LED_BUILTIN, LOW);
  digitalWrite(PIN_LED_GREEN, LOW);
  digitalWrite(PIN_LED_YELLOW, LOW);
  digitalWrite(PIN_LED_RED, LOW);
  stopBuzzer();

  fanServo.attach(PIN_SERVO);
  fanServo.write(0);

  dht.begin();
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("SERVER MONITOR");
  lcd.setCursor(0, 1);
  lcd.print("SYSTEM READY!");

  // Đọc cảm biến lần đầu ngay khi khởi động
  readAllSensors();
}

void loop() {
  unsigned long currentMillis = millis();

  processSerialCommands();

  if (currentMillis - prevSensorMillis >= SENSOR_INTERVAL) {
    prevSensorMillis = currentMillis;
    readAllSensors();
    evaluateSystemLogic(currentMillis);
    sendTelemetryJson();
  }

  if (currentMillis - prevLcdMillis >= LCD_INTERVAL) {
    prevLcdMillis = currentMillis;
    updateLcdDisplay();
  }

  handleAlertsAndLeds(currentMillis);
  handleFanServoContinuous(currentMillis);
}

/**
 * Đo điện áp nguồn thực tế của Arduino (mV) bằng nội tham chiếu 1.1V
 * Giúp cảm biến LM35 đọc chính xác tuyệt đối, không bị tăng nhiệt ảo khi sụt áp USB
 */
long readVcc() {
  ADMUX = _BV(REFS0) | _BV(MUX3) | _BV(MUX2) | _BV(MUX1);
  delayMicroseconds(2000);
  ADCSRA |= _BV(ADSC);
  while (bit_is_set(ADCSRA, ADSC));
  uint8_t low  = ADCL;
  uint8_t high = ADCH;
  long result = (high << 8) | low;
  result = 1125300L / result; // Tính Vcc theo mV
  return result;
}

void readAllSensors() {
  // 1. Đọc DHT11
  float h = dht.readHumidity();
  float t = dht.readTemperature();
  if (!isnan(h) && !isnan(t)) {
    roomHum = h;
    roomTemp = t;
  }

  // 2. Lấy điện áp nguồn thực tế & đọc bỏ 1 mẫu để ổn định tụ ADC
  long vcc_mV = readVcc();
  analogRead(PIN_LM35); 

  // 3. Đọc LM35 trung bình 10 mẫu với điện áp nguồn thực tế
  long sumLm35 = 0;
  for (int i = 0; i < 10; i++) {
    sumLm35 += analogRead(PIN_LM35);
  }
  rackTemp = (((float)sumLm35 / 10.0) * ((float)vcc_mV / 1024.0)) / 10.0;

  // Chống nhiễu nếu chân A0 chưa cắm cảm biến hoặc dao động bất thường
  if (rackTemp > 100.0 || rackTemp < 0.0) {
    rackTemp = roomTemp;
  }

  // 4. Biến trở (A2) chỉnh ngưỡng Critical từ 30.0°C đến 36.0°C
  // (Tại 26°C luôn luôn nằm trong vùng an toàn NORMAL)
  int potRaw = analogRead(PIN_POT);
  demoThreshold = 30.0 + ((float)potRaw / 1023.0) * 6.0;

  // 5. Quang trở LDR (A1): Tối/che tay -> Bật đèn phòng Server (D3 + D13)
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

void evaluateSystemLogic(unsigned long currentMillis) {
  int targetFanByTemp = 0;
  bool shouldTriggerBuzzer = false;

  // Ngưỡng Warning = demoThreshold - 1.5°C (tối thiểu 28.5°C)
  float warningThresh = demoThreshold - 1.5;

  // Mức CRITICAL: Tủ Rack vượt ngưỡng (> 30.0°C trở lên, coi như > 60°C để demo)
  if (rackTemp > demoThreshold || roomTemp > (demoThreshold + 2.0)) {
    currentStatus = "CRITICAL";
    targetFanByTemp = 2; // Quạt quay nhanh liên tục
    shouldTriggerBuzzer = true;
  }
  // Mức WARNING: Nhiệt độ tiệm cận ngưỡng (từ 28.5°C đến 30.0°C)
  else if (rackTemp >= warningThresh || roomTemp >= demoThreshold) {
    currentStatus = "WARNING";
    targetFanByTemp = 1; // Quạt quay vừa
    shouldTriggerBuzzer = true;
  }
  // Mức NORMAL: Dưới 28.5°C (Ví dụ 26°C hoàn toàn bình thường)
  else {
    currentStatus = "NORMAL";
    targetFanByTemp = 0;
    shouldTriggerBuzzer = false;
  }

  // Duy trì Servo quay tối thiểu 10 giây
  if (manualOverride) {
    fanSpeedMode = manualFanMode;
    isFanLatched = false;
  } else {
    if (targetFanByTemp > 0) {
      if (!isFanLatched) {
        isFanLatched = true;
        fanLatchStartMillis = currentMillis;
        latchedFanMode = targetFanByTemp;
      } else if (targetFanByTemp > latchedFanMode) {
        latchedFanMode = targetFanByTemp;
      }
      fanSpeedMode = latchedFanMode;
    } else {
      if (isFanLatched) {
        if (currentMillis - fanLatchStartMillis >= MIN_SERVO_RUN_MS) {
          isFanLatched = false;
          fanSpeedMode = 0;
        } else {
          fanSpeedMode = latchedFanMode;
        }
      } else {
        fanSpeedMode = 0;
      }
    }
  }

  // Duy trì Buzzer kêu tối thiểu 2 giây
  if (shouldTriggerBuzzer && !alarmSilenced) {
    if (!isBuzzerLatched) {
      isBuzzerLatched = true;
      buzzerLatchStartMillis = currentMillis;
    }
  } else {
    if (alarmSilenced) {
      isBuzzerLatched = false;
    } else if (isBuzzerLatched && (currentMillis - buzzerLatchStartMillis >= MIN_BUZZER_RUN_MS)) {
      isBuzzerLatched = false;
      alarmSilenced = false;
    }
  }

  if (currentStatus == "NORMAL" && !isBuzzerLatched) {
    alarmSilenced = false;
  }
}

void handleFanServoContinuous(unsigned long currentMillis) {
  if (fanSpeedMode == 0) {
    if (servoAngle != 0) {
      servoAngle = 0;
      fanServo.write(0);
    }
    return;
  }

  unsigned long stepInterval = (fanSpeedMode == 2) ? 12 : 30;
  int stepSize = (fanSpeedMode == 2) ? 14 : 6;

  if (currentMillis - prevServoMillis >= stepInterval) {
    prevServoMillis = currentMillis;
    servoAngle += (servoDirection * stepSize);

    if (servoAngle >= 180) {
      servoAngle = 180;
      servoDirection = -1;
    } else if (servoAngle <= 0) {
      servoAngle = 0;
      servoDirection = 1;
    }
    fanServo.write(servoAngle);
  }
}

void handleAlertsAndLeds(unsigned long currentMillis) {
  if (currentStatus == "NORMAL") {
    digitalWrite(PIN_LED_GREEN, HIGH);
    digitalWrite(PIN_LED_YELLOW, LOW);
    digitalWrite(PIN_LED_RED, LOW);
  } else if (currentStatus == "WARNING") {
    digitalWrite(PIN_LED_GREEN, LOW);
    digitalWrite(PIN_LED_YELLOW, HIGH);
    digitalWrite(PIN_LED_RED, LOW);
  } else if (currentStatus == "CRITICAL") {
    digitalWrite(PIN_LED_GREEN, LOW);
    digitalWrite(PIN_LED_YELLOW, LOW);
    if (currentMillis - prevBlinkMillis >= 180) {
      prevBlinkMillis = currentMillis;
      blinkState = !blinkState;
      digitalWrite(PIN_LED_RED, blinkState ? HIGH : LOW);
    }
  }

  // Kêu còi mức vừa phải (100ms BẬT / 220ms TẮT) duy trì tối thiểu 2 giây
  if (isBuzzerLatched && !alarmSilenced) {
    if ((currentMillis % 320) < 100) {
      soundBuzzerModerate();
    } else {
      stopBuzzer();
    }
  } else {
    stopBuzzer();
  }
}

void soundBuzzerModerate() {
#if USE_PASSIVE_BUZZER
  tone(PIN_BUZZER, 1200);
#else
  digitalWrite(PIN_BUZZER, HIGH);
#endif
}

void stopBuzzer() {
#if USE_PASSIVE_BUZZER
  noTone(PIN_BUZZER);
#else
  digitalWrite(PIN_BUZZER, LOW);
#endif
}

void updateLcdDisplay() {
  lcd.setCursor(0, 0);
  char line0[17];
  snprintf(line0, sizeof(line0), "T:%02dC H:%02d%% R:%02dC", (int)roomTemp, (int)roomHum, (int)rackTemp);
  lcd.print(line0);

  lcd.setCursor(0, 1);
  char line1[17];
  if (currentStatus == "NORMAL" && isFanLatched) {
    unsigned long elapsed = millis() - fanLatchStartMillis;
    unsigned long remainSec = (elapsed < MIN_SERVO_RUN_MS) ? ((MIN_SERVO_RUN_MS - elapsed) / 1000) : 0;
    snprintf(line1, sizeof(line1), "COOLING: %02lus    ", remainSec);
  } else {
    const char* lightStr = isRoomLightOn ? "L:ON " : "L:OFF";
    snprintf(line1, sizeof(line1), "%s  %-9s", lightStr, currentStatus.c_str());
  }
  lcd.print(line1);
}

void sendTelemetryJson() {
  String json = "{\"temp\":" + String(roomTemp, 1) +
                ",\"hum\":" + String(roomHum, 1) +
                ",\"rack\":" + String(rackTemp, 1) +
                ",\"door\":\"" + String(isDoorOpen ? "OPEN" : "CLOSED") + "\"" +
                ",\"light\":\"" + String(isRoomLightOn ? "ON" : "OFF") + "\"" +
                ",\"thresh\":" + String(demoThreshold, 1) +
                ",\"status\":\"" + currentStatus + "\"" +
                ",\"servo\":" + String(fanSpeedMode == 0 ? 0 : (fanSpeedMode == 1 ? 50 : 100)) + "}";

  Serial.println(json);
  btSerial.println(json);
}

void processSerialCommands() {
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
    manualFanMode = 2;
  } else if (cmd == "VENT_CLOSE") {
    manualOverride = true;
    manualFanMode = 0;
    isFanLatched = false;
  } else if (cmd == "VENT_AUTO") {
    manualOverride = false;
  } else if (cmd == "ALARM_OFF") {
    alarmSilenced = true;
    isBuzzerLatched = false;
    stopBuzzer();
  }
}