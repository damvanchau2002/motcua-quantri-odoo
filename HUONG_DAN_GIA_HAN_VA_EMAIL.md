# Hướng Dẫn Quy Trình Gia Hạn và Thông Báo Email

## 📋 Tổng Quan

Hệ thống quản lý sinh viên đã được cấu hình để:
1. **Tự động kiểm tra yêu cầu quá hạn** mỗi giờ
2. **Gửi email thông báo** khi yêu cầu quá hạn
3. **Hỗ trợ gia hạn yêu cầu** thông qua wizard

## 🔄 Quy Trình Gia Hạn Yêu Cầu Quá Hạn

### Bước 1: Xác định yêu cầu quá hạn
- Hệ thống tự động đánh dấu yêu cầu quá hạn dựa trên trường `expired_date`
- Trường `is_expired` được tính toán tự động
- Cron job chạy mỗi giờ để kiểm tra và cập nhật trạng thái

### Bước 2: Gửi thông báo email
- Email thông báo được gửi đến người xử lý (`user_processing_id`)
- Template email: `email_template_request_expired`
- Báo cáo tổng hợp hàng ngày gửi đến admin

### Bước 3: Thực hiện gia hạn
1. Truy cập yêu cầu cần gia hạn
2. Sử dụng wizard "Gia hạn yêu cầu"
3. Nhập số giờ gia hạn và lý do
4. Hệ thống sẽ:
   - Cập nhật `expired_date` mới
   - Gửi email thông báo gia hạn
   - Ghi log vào chatter

## 📧 Cấu Hình Email Thông Báo

### Cấu hình SMTP trong odoo.cfg
```ini
# SMTP Configuration for email notifications
email_from = admin@localhost
smtp_server = localhost
smtp_port = 1025
smtp_ssl = False
smtp_user = False
smtp_password = False
```

### Các Template Email Có Sẵn

#### 1. Thông báo yêu cầu quá hạn
- **ID**: `email_template_request_expired`
- **Người nhận**: `user_processing_id.email`
- **Nội dung**: Thông tin chi tiết yêu cầu quá hạn

#### 2. Báo cáo hàng ngày
- **ID**: `email_template_daily_expired_report`
- **Người nhận**: `admin@example.com`
- **Nội dung**: Tổng hợp yêu cầu quá hạn trong ngày

#### 3. Thông báo gia hạn
- **Tự động gửi**: Khi gia hạn được phê duyệt
- **Nội dung**: Thông tin gia hạn và deadline mới

## ⚙️ Cron Job Kiểm Tra Quá Hạn

### Cấu hình
- **Tên**: `cron_check_expired_requests`
- **Tần suất**: Mỗi giờ (`interval_type: hours`, `interval_number: 1`)
- **Method**: `_cron_check_expired_requests()`

### Chức năng
1. Tìm các yêu cầu đã quá hạn nhưng chưa được đánh dấu
2. Cập nhật trạng thái `expiry_warning_sent`
3. Gửi email thông báo cá nhân
4. Ghi log vào chatter
5. Gửi báo cáo tổng hợp hàng ngày

## 🧪 Test Chức Năng Email

### Script Test Đơn Giản
```python
# Chạy file test_email_simple.py để kiểm tra SMTP
python test_email_simple.py
```

### SMTP Debug Server
```bash
# Khởi động server debug để xem email
python -m aiosmtpd -n -l localhost:1025
```

## 🔧 Khắc Phục Sự Cố

### Vấn đề thường gặp

#### 1. Email không được gửi
- **Kiểm tra**: Cấu hình SMTP trong `odoo.cfg`
- **Kiểm tra**: SMTP server có đang chạy không
- **Kiểm tra**: Log Odoo để xem lỗi

#### 2. Cron job không chạy
- **Kiểm tra**: Cron job có được kích hoạt không
- **Kiểm tra**: Database có quyền thực thi không
- **Kiểm tra**: Log hệ thống

#### 3. Gia hạn không hoạt động
- **Kiểm tra**: Wizard có được cài đặt đúng không
- **Kiểm tra**: Quyền người dùng
- **Kiểm tra**: Validation logic

## 📊 Monitoring và Báo Cáo

### Theo dõi email
- Kiểm tra `mail.mail` model để xem trạng thái email
- Log SMTP server để debug

### Theo dõi yêu cầu quá hạn
- Dashboard hiển thị số lượng yêu cầu quá hạn
- Báo cáo định kỳ về hiệu suất xử lý

## 🚀 Cải Tiến Tương Lai

### Đề xuất
1. **Thông báo đa kênh**: SMS, push notification
2. **Escalation tự động**: Thông báo cấp trên khi quá hạn lâu
3. **Dashboard real-time**: Hiển thị trạng thái yêu cầu
4. **AI prediction**: Dự đoán yêu cầu có thể quá hạn

---

## 📞 Hỗ Trợ

Nếu gặp vấn đề, vui lòng:
1. Kiểm tra log Odoo
2. Kiểm tra cấu hình SMTP
3. Chạy script test email
4. Liên hệ admin hệ thống