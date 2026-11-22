SSH vào 172.16.2.139
user: pi
password: raspberry
Đây là tài khoản nội bộ raspberry nên hoàn toàn an toàn, không cần bảo mật.
---

YÊU CẦU LẬP TRÌNH FILE CODE CHO RASPBERRY VÀ ARDUINO CHO BÀI THẬP THỰC HÀNH IOT.
REQUIREMENT:
1) HOÀN THÀNH YÊU CẦU CỦA BÀI TẬP
2) TUÂN THEO TUYỆT ĐỐI SƠ ĐỒ PHẦN CỨNG TRUYỀN VÀO NẾU CÓ
3) TUÂN THEO THIẾT BỊ ĐANG CÓ.
4) TRƯỚC HẾT PHẢI KIỂM TRA PHẦN CỨNG, TỪNG CHÂN VÀ TỪNG THIẾT BỊ, NẾU HỞ MẠCH Ở ĐÂU PHẢI BÁO CHO TÔI
5) MỘI TIẾN TRÌNH PHẢI CÓ LOG TIẾN TRÌNH RA MÀN HÌNH ĐẦY ĐỦ CHO TÔI
6) KHI HOÀN TẤT PHẢI THÔNG BÁO ĐẦY ĐỦ KẾT QUẢ THEO YÊU CẦU BÀI TẬP RA MÀN HÌNH.

```

## PHẦN G — RULES & KINH NGHIỆM TRÁNH LỖI

- **Máy**: Raspberry Pi 3 Model B Plus Rev 1.3, Raspbian 12 (bookworm), Python 3.11.2,
  gpiozero 1.6.2, RPi.GPIO 0.7.1.
- **GPIO2 (board pin 3) đã có pull-up phần cứng cố định** (chân này gắn chung với bus
  I2C1 SDA) → công tắc chỉ cần nối 1 chân vào GPIO2, chân còn lại xuống GND. Không cần
  (và không nên cố) set `pull_up_down=PUD_UP` thêm ở RPi.GPIO — phần cứng đã kéo lên sẵn.
- ⚠️ **gpiozero `Button(2, ...)` LỖI `RuntimeError: Failed to add edge detection` nếu
  chạy không có `sudo`** trên board này (Bookworm, `gpiochip512`/`gpiochip566` — base
  renumber khác bản Raspbian cũ). User `pi` tuy đã ở group `gpio` nhưng vẫn thiếu quyền
  cho edge-detection qua `RPi.GPIO` backend của gpiozero. **Cách chạy đúng**:
  `sudo python3 blink_gpiozero.py` (áp dụng luôn cho `pwm_gpiozero.py` ở Practice 4.3 vì
  cùng dùng `Button(2)`).
- Bản **RPi.GPIO** (`blink_rpigpio.py`, `pwm_rpigpio.py`) dùng polling thuần
  (`GPIO.input()` trong loop, không `add_event_detect`) → chạy được **có hoặc không có
  `sudo`**, không gặp lỗi trên.
- Đã verify Practice 4.2 bằng `raspi-gpio get 17` lấy mẫu khi script gpiozero chạy (có
  `sudo`): GPIO17 dao động `level=1`/`level=0` đúng chu kỳ `BLINK_INTERVAL=0.5s` đã đặt
  trong code → xác nhận LED nhấp nháy đúng khi không nhấn công tắc.
- Practice 4.3 (PWM): dùng tần số PWM 100Hz, bước duty cycle +10%/lần nhấn, qua 100%
  (tức bấm thêm khi đang ở duty=100%) thì reset về 0% — đã verify bằng cách gọi thủ công
  hàm xử lý nhấn nút trong code (giả lập nhấn liên tục) và in giá trị duty cycle ra log,
  xác nhận đúng dãy 0→10→20→...→100→0.
- Không bấm được công tắc vật lý thật từ xa qua SSH cho cả 2 bài → nhánh phụ thuộc hành
  động "nhấn công tắc" (Practice 4.2: sáng liên tục; Practice 4.3: tăng duty cycle) được
  xác nhận bằng đọc logic code + giả lập gọi hàm xử lý sự kiện nhấn trong script test,
  CHƯA có ảnh/video bấm công tắc thật — người dùng tự bấm thử trên phần cứng để xác nhận
  cuối cùng.
- Sau mỗi lần test phải tắt LED + `GPIO.cleanup()` thủ công nếu kill script bằng
  `pkill`/SIGTERM (không đi qua `KeyboardInterrupt` nên khối `finally` không tự chạy,
  LED có thể bị kẹt sáng ở trạng thái cuối).



YÊU CẦU ĐỀ BÀI.


Case: Smart Server Room Monitoring

Hệ thống giám sát nhiệt độ, độ ẩm và điểm nóng trong tủ rack, phát hiện mở cửa phòng, cảnh báo 3 mức (Normal / Warning / Critical) và điều khiển cửa gió làm mát từ dashboard.

Thiết bị: có sẵn và còn thiếu
Vai trò	Linh kiện	Tình trạng
Nhiệt độ, độ ẩm phòng	DHT11	Có trong kit
Điểm nóng tủ rack	LM35	Có
Phát hiện mở cửa / bật đèn	Quang trở 5528 + điện trở 10k	Có
Chỉnh ngưỡng cảnh báo tại chỗ	Biến trở 10k	Có
Hiển thị tại chỗ	LCD1602 I2C	Có
Cửa gió làm mát	Servo 9g	Có
Cảnh báo	LED xanh/vàng/đỏ + buzzer	Có
Gateway	Raspberry Pi 3B+ (thẻ nhớ, nguồn)	Không có trong kit
Bluetooth	HC-05	Không có trong kit, chỉ cần cho mức 9–10
LED 4 số trên Pi	Module TM1637	Nên mua; LED 4 số trần trong kit vẫn dùng được nhưng tốn 12 chân GPIO

Relay, RFID, cảm biến nước và KY-037 có trong kit nhưng nằm ngoài danh sách thiết bị của đề. Tôi để chúng ở phần điểm thưởng; anh nên hỏi giảng viên trước khi dùng.

Bản lõi 7–8 điểm
Dòng rubric	Cách làm
Arduino	DHT11 + LCD1602 + buzzer và 3 LED
Giao tiếp	Serial qua cáp USB, không cần mạch hạ áp
Raspberry Pi	Flask dashboard + nút điều khiển
Lưu dữ liệu	SQLite, 2 bảng: readings, events
Dashboard	Số liệu hiện tại + bảng lịch sử
Điều khiển từ GUI	Tắt còi, mở/đóng cửa gió

Arduino gửi mỗi 2 giây một dòng, ví dụ D,28.5,61,30.2,512,27,WARN. Pi gửi lệnh xuống dạng C,SERVO,90, C,MUTE,1, C,TH,30. Giao thức này giữ nguyên khi chuyển sang Bluetooth.

Nâng lên 9–10 điểm
Thêm cảm biến: LM35, quang trở, biến trở (đủ điều kiện ≥ 2 cảm biến).
Bluetooth: HC-05 nối SoftwareSerial (D10/D11), chân RX của HC-05 qua cầu chia áp 1k/2k. Pi tự chuyển sang USB Serial khi mất Bluetooth và tự kết nối lại.
LED 4 số trên Pi: hiển thị nhiệt độ hiện tại.
Biểu đồ: Chart.js vẽ nhiệt độ và độ ẩm theo thời gian, có vạch ngưỡng.
Điều khiển bắt buộc từ GUI: chế độ Auto/Manual, góc servo, đặt ngưỡng, tắt còi.

Điểm thưởng +1:

Dashboard đẹp: thẻ trạng thái đổi màu theo mức cảnh báo.
Biểu đồ: đã có ở bước 4.
Bluetooth ổn định: đã có ở bước 2.
Ý tưởng mở rộng: Pi tính điểm sương và tốc độ tăng nhiệt, ghi nhật ký sự cố; nếu được phép thì thêm RFID ghi nhận người vào phòng.
Sơ đồ chân Arduino
Chân	Nối với
D2	DHT11 : HIỂN THỊ LÊN LCD VÀ GỬI DATA LÊN SERVER
A0	LM35 : ALERT KHI TỦ RACK NÓNG - ALERT RA BUZZER VÀ ĐÈN LED SÁNG VÀ KÍCH HOẠT MODULE RELAY TẮT VÀ MỞ QUẠT. CHÂN SỐ 5
RELAY: DÙNG ĐỂ TẮT VÀ MỞ QUẠT. CHÂN SỐ 5. TẮT MỞ KHI CÓ BÁO ĐỘNG VƯỢT NGƯỠNG NHIỆT ĐỘ
A1	Quang trở + 10k : DÙNG ĐỂ MỞ ĐÈN LED TRONG PHÒNG SERVER
A2	Biến trở 
A4, A5	LCD I2C: HIỂN THỊ TRÊN ARDUINO
D5, D6, D7	LED xanh, vàng, đỏ (220Ω)
D8	Buzzer
D9	Servo: MÔ PHỎNG CHỐT CỬA RA VÀO. CHÂN SỐ 6
D10, D11	HC-05
D0, D1 (USB)	Serial dự phòng

YÊU CẦU:
Case: Smart Server Room Monitoring
Hệ thống giám sát nhiệt độ, độ ẩm và điểm nóng trong tủ rack, phát hiện mở cửa phòng, cảnh báo 3 mức (Normal / Warning / Critical) và điều khiển cửa gió làm mát từ dashboard.
Thiết bị: có sẵn và còn thiếu
Vai trò	Linh kiện	Tình trạng
Nhiệt độ, độ ẩm phòng	DHT11	Có trong kit
Điểm nóng tủ rack	LM35	Có
Phát hiện mở cửa / bật đèn	Quang trở 5528 + điện trở 10k	Có
Chỉnh ngưỡng cảnh báo tại chỗ	Biến trở 10k	Có
Hiển thị tại chỗ	LCD1602 I2C	Có
Cửa gió làm mát	Servo 9g	Có
Cảnh báo	LED xanh/vàng/đỏ + buzzer	Có
Gateway	Raspberry Pi 3B+ (thẻ nhớ, nguồn)	Không có trong kit
Bluetooth	HC-05	Không có trong kit, chỉ cần cho mức 9–10
LED 4 số trên Pi	Module TM1637	Nên mua; LED 4 số trần trong kit vẫn dùng được nhưng tốn 12 chân GPIO