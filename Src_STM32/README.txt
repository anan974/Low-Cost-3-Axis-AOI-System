================================================================================
          PROJECT: STM32 CNC / STEPPER MOTOR CONTROLLER (CORE ARCHITECTURE)
          PHIÊN BẢN: V2 - BỔ SUNG CƠ CHẾ POLLING NÚT BẤM THỦ CÔNG (JOGGING)
================================================================================

1. GIỚI THIỆU CHUNG
--------------------------------------------------------------------------------
Dự án này thiết kế một bộ điều khiển (Controller) lõi nhúng cao tốc, chịu trách nhiệm
điều khiển động cơ bước (Stepper Motor) 3 trục (X, Y, Z) sử dụng vi điều khiển STM32. 
Hệ thống xử lý bất đồng bộ, nhận lệnh ký tự qua UART từ máy tính hoặc qua hệ thống 
nút bấm vật lý (Jogging), tự động phân tích cú pháp, tính toán động học và trực tiếp 
phát xung điều khiển chính xác theo thời gian thực (Real-time).

Hệ thống được thiết kế theo mô hình Kiến trúc hướng Ngắt (Interrupt-Driven Architecture),
giải phóng hoàn toàn luồng xử lý chính khỏi việc tạo xung, giúp máy vận hành 
mượt mà, không bao giờ bị mất bước (Lose steps) do nghẽn phần mềm.


2. CƠ CHẾ HOẠT ĐỘNG VÀ QUẢN LÝ LUỒNG TRONG HỆ THỐNG
--------------------------------------------------------------------------------
Hệ thống phân tách rõ ràng nhiệm vụ của CPU thành 3 tầng xử lý song song để tránh 
tranh chấp tài nguyên:

Tầng 1: Nhận lệnh ngoại vi (UART Interrupt & Button Polling - Luồng chính Background)
- Luồng chính liên tục thực hiện hai nhiệm vụ song song trong vòng lặp `while(1)`:
  1. Kiểm tra cờ `Data_Ready` để phân tích lệnh G-code từ máy tính truyền xuống qua UART.
  2. Thực hiện quét trạng thái (Polling) hệ thống nút bấm điều khiển thủ công (Jogging Buttons).

Tầng 2: Giám sát trạng thái Bận/Rảnh (Hàm Watchdog `Machine_Wait_Until_Done`)
- Khi bất kỳ lệnh di chuyển nào (từ G-code hoặc từ nút bấm tay) được kích hoạt, 
  luồng chính sẽ nạp số bước vào Timer và lập tức rơi vào hàm chờ `Machine_Wait_Until_Done()`.
- Tại đây, luồng chính tạm khóa chức năng nhận lệnh mới và chuyển sang Polling 
  Duy Nhất một nút bấm: Nút Tạm dừng khẩn cấp (PAUSE).

Tầng 3: Sinh xung cao tốc (Hardware Timers Interrupt - Real-time)
- Trục X và Y (TIM2): Áp dụng thuật toán nội suy Bresenham trong ngắt định kỳ 
  `PeriodElapsedCallback` để bật/tắt chân GPIO đồng bộ, ép dao chạy đúng đường chéo.
- Trục Z (TIM3): Hoạt động độc lập bằng ngắt PWM.
- Cơ chế Ramping tự động: Tốc độ tối đa và gia tốc được khống chế cứng thông qua 
  thanh ghi `ARR`. Phần cứng tự động tăng/giảm tốc độ hình thang mượt mà dựa trên 
  số bước còn lại.


3. CƠ CHẾ PHÂN CHIA POLLING NÚT BẤM ĐIỀU KHIỂN (NGOẠI VI)
--------------------------------------------------------------------------------
Để các nút bấm vật lý không xung đột với lệnh G-code từ máy tính, hệ thống chia các 
nút bấm thành hai nhóm hoạt động ở hai phân vùng độc lập:

Nhóm A: Các nút di chuyển thủ công (JOGGING BUTTONS - Quét trong `while(1)`)
- Điều kiện kích hoạt: CHỈ cho phép hoạt động khi máy đang rảnh hoàn toàn 
  (`step_count == 0 && z_step_count == 0`) và hệ thống không bị lỗi (`system_alarm == 0`).
- Cơ chế Dịch chuyển theo từng nấc (Incremental Jog): Do thuật toán Bresenham bắt buộc 
  phải biết trước khoảng cách để chia tỉ lệ xung, các nút bấm tay không chạy vô hạn.
- Nguyên lý: Khi đè giữ nút (ví dụ nút trục X+), hệ thống phát hiện phím nhấn (sau khi khử 
  rung `HAL_Delay(30)`), nạp lệnh dịch chuyển một khoảng ngắn tĩnh (ví dụ: 1mm) xuống 
  Timer thông qua hàm `Stepper_Move_mm()`, rồi nhảy vào hàm `Machine_Wait_Until_Done()` 
  đợi chạy xong. Nếu nút vẫn bị đè giữ, chu kỳ 1mm tiếp theo lại được nạp. Nhờ đó, 
  motor di chuyển liên tục mượt mà, nhưng khi nhả tay ra, máy lập tức dừng lại chính xác, 
  không bao giờ bị quá đà hay mất tọa độ.

Nhóm B: Nút Tạm dừng khẩn cấp (PAUSE BUTTON - Quét trong `Machine_Wait_Until_Done`)
- Vị trí chân: Kết nối vào chân `GPIOA - PIN 4` (PA4).
- Điều kiện kích hoạt: Hoạt động ngay cả khi motor đang quay tốc độ cao nhằm can thiệp 
  phần cứng lập tức.
- Nguyên lý: Nhấn lần 1 -> Đóng ngắt `TIM2` và `TIM3` ngay trong ngắt, phanh cứng 
  motor bằng cách giữ nguyên dòng điện cuộn dây (giữ bước, không trôi tự do). Xuất chuỗi 
  báo cáo qua UART: `"EVENT: Machine Paused\n"`. Nhấn lần 2 -> Nhả block, bật lại Timer 
  để motor chạy tiếp hành trình còn lại mà không sai lệch tọa độ.


4. TẬP LỆNH G-CODE & CONTROL ĐƯỢC HỖ TRỢ
--------------------------------------------------------------------------------
Giao tiếp qua Serial Terminal (Baudrate: 115200, 8 bit, 1 stop, no parity, kết thúc bằng `\n`). 
Hệ thống KHÔNG dùng tham số F (Feedrate), tốc độ khống chế bằng phần cứng.

- LỆNH `G0` : CHU KỲ TỰ ĐỘNG TÌM GỐC MÁY (HOMING CYCLE)
  * Cú pháp: `G0\n`
  * Cơ chế: Động cơ XY quay ngược về công tắc hành trình. Chạm -> lùi lại giảm chấn 
    -> tiến vào chậm lần 2 lấy gốc tuyệt đối. Cài đặt `current_pos_x = 0`, `current_pos_y = 0`.

- LỆNH `G1` : DỊCH CHUYỂN NỘI SUY ĐƯỜNG THẲNG
  * Cú pháp: `G1 X[tọa_độ_mm] Y[tọa_độ_mm] Z[tọa_độ_độ]\n`
  * Cơ chế: Điều khiển đầu dao đi tuyến tính tới đích, tự động áp dụng Ramping điều tốc. 
    Nếu thiếu tham số trục nào, trục đó tự giữ nguyên vị trí cũ.

- LỆNH `RMLOCK` : GIẢI PHÓNG KHÓA HỆ THỐNG (REMOVE LOCK / CLEAR ALARM)
  * Cú pháp: `RMLOCK\n`
  * Cơ chế: Khi bật nguồn hoặc khi tông trúng công tắc hành trình, máy tự khóa an toàn 
    (`system_alarm = 1`) và từ chối lệnh di chuyển. Lệnh này xóa lỗi (`system_alarm = 0`) 
    để mở lại quyền chạy cho Timer.


5. THÔNG SỐ CẤU HÌNH CƠ KHÍ LÕI (stepper_v3.h)
--------------------------------------------------------------------------------
- `STEPS_PER_MM_X` (1275): 1275 xung = 1mm tịnh tiến trục X.
- `STEPS_PER_MM_Y` (1275): 1275 xung = 1mm tịnh tiến trục Y.
- `Z_STEPS_PER_DEGREE` (160.0f): 160 xung = 1 độ xoay trục Z.
- Hướng di chuyển (DIR Pin logic):
  + `DIR_NEGATIVE` (Mức cao - GPIO_PIN_SET): Quay lùi về phía Home.
  + `DIR_POSITIVE` (Mức thấp - GPIO_PIN_RESET): Quay tiến ra vùng làm việc.


6. HƯỚNG DẪN HẠ CẤP PHẦN CỨNG XUỐNG DÒNG CHIP GIÁ RẺ (STM32F0)
--------------------------------------------------------------------------------
Do toàn bộ các module hiển thị màn hình LCD đã được lược bỏ, mã nguồn cực kỳ 
tinh gọn, sẵn sàng chạy hoàn hảo trên lõi STM32F0:
- Số lượng chân: Yêu cầu khoảng 17 - 21 chân IO thực tế tùy thuộc số lượng nút bấm 
  Jogging bác thiết kế thêm. Chọn chip dòng 32 chân (STM32F030K6T6) hoặc tốt nhất là 
  48 chân (STM32F030C8T6) để thiết kế PCB thoải mái.
- Do F0 không có FPU (tính toán số thực cứng), việc cô lập toán `float` ở luồng Main 
  là cực kỳ chính xác. Cơ chế Polling nút bấm bằng các hàm nấc ngắn (`Stepper_Move_mm(1.0, 0.0)`) 
  chỉ chạy ngoài vòng `while(1)`, khi ngắt Timer hoạt động thì chỉ xử lý các phép toán 
  số nguyên `int32_t` (Bresenham), giúp chip F0 chạy mượt mà, không sợ bị trễ xung hay quá tải.
================================================================================