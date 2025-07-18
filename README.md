# motcua-quantri-odoo

## Giới thiệu

Đây là dự án quản trị một cửa dựa trên nền tảng Odoo, nhằm hỗ trợ số hóa quy trình quản lý, tiếp nhận và xử lý hồ sơ cho các tổ chức/doanh nghiệp. Dự án cung cấp các tính năng quản lý hồ sơ, quy trình phê duyệt, báo cáo và tích hợp với các hệ thống khác.

## Tính năng chính

motcua_odoo\addons\student_request

- Quản lý hồ sơ một cửa
- Quy trình phê duyệt linh hoạt
- Báo cáo, thống kê
- Tích hợp với các hệ thống nội bộ

## Yêu cầu

- Python 3.x
- Odoo 18

## Cài đặt

```bash
git clone https://github.com/nghiapm164/motcua-quantri-odoo.git
cd motcua-quantri-odoo
# Thực hiện các bước cài đặt Odoo và cấu hình module tại đây
```

### Cấu hình cơ sở dữ liệu

Sao chép file cấu hình mẫu và chỉnh sửa thông tin kết nối database:

```bash
cp odoo.cfg.example odoo.cfg
```

Mở file `odoo.cfg` và cập nhật các thông tin sau cho phù hợp với môi trường của bạn:

```ini
[options]
db_host = <tên_host_db>
db_port = <cổng_db>
db_user = <tên_user_db>
db_password = <mật_khẩu_db>
db_name = <tên_database>
# ...các cấu hình khác...
```

Sau đó, khởi động Odoo với file cấu hình này:

```bash
python odoo-bin -c odoo.cfg -i base
```
## API

### Danh sách dịch vụ
```
GET /student_service/api/services
```
Trả về danh sách các dịch vụ.

### Danh sách nhóm dịch vụ và các dịch vụ trong nhóm
```
GET /api/service/groups
```
Trả về danh sách nhóm dịch vụ và các dịch vụ thuộc từng nhóm.

### Tạo yêu cầu dịch vụ (có upload nhiều ảnh)
```
POST /api/service/request/create
Content-Type: multipart/form-data

Form data:
  service_id: <id dịch vụ>
  request_user_id: <id user>
  note: <ghi chú>
  files: <chọn nhiều file ảnh> (có thể gửi nhiều file, mỗi file là một ảnh đính kèm)
```
**Ví dụ dùng curl:**
```bash
curl --location 'http://localhost:8069/api/service/request/create' \
--form 'service_id="1"' \
--form 'request_user_id="2"' \
--form 'note="ghi chú"' \
--form 'files=@"/path/to/image1.jpg"' \
--form 'files=@"/path/to/image2.png"'
```
Trả về thông tin yêu cầu vừa tạo, bao gồm danh sách id ảnh đính kèm.

### Danh sách các yêu cầu dịch vụ của một user (có lịch sử duyệt)
```
POST /api/service/request/user
Content-Type: application/json

{
  "user_id": <id user>
}
```
Trả về danh sách các yêu cầu dịch vụ của user, kèm lịch sử duyệt từng yêu cầu.

### Đăng nhập lấy session (User Login)
```
POST /web/session/authenticate
Content-Type: application/json

{
  "params": {
    "db": "<tên_database>",
    "login": "<username>",
    "password": "<password>"
  }
}
```
Trả về thông tin user và session_id. Sử dụng session_id này cho các API cần xác thực user.

**Ví dụ sử dụng session cho các API:**
- Gửi cookie `session_id` trong header khi gọi các API có `auth='user'`.
- Với các API public, không cần session.

### Tạo user public (không đăng nhập Odoo)
- Để đồng bộ tài khoản Sinh Viên
```
POST /api/public_user/create
Content-Type: application/json

{
  "username": "<tên người dùng>",
  "loginname": "<tên đăng nhập>",
  "image_url": "<url ảnh đại diện>"
}
```
Trả về thông tin user vừa tạo (id, tên, ảnh)