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
odoo -c odoo.cfg
```

## Đóng góp

Vui lòng tạo pull request hoặc liên hệ trực tiếp để đóng góp cho dự án.
