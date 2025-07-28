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
# Student Service API Documentation

Tài liệu này mô tả tất cả các API trong file `service_api.py`, bao gồm input (request) và output (response).

---

## 1. GET `/api/service/groups`
**Mô tả:** Lấy danh sách nhóm dịch vụ và các dịch vụ trong nhóm.

**Input:**  
Không có.

**Response:**
```json
{
  "success": true,
  "message": "Danh sách nhóm dịch vụ và dịch vụ",
  "data": [
    {
      "id": 1,
      "name": "Tên nhóm",
      "description": "Mô tả nhóm",
      "parent_id": null,
      "services": [
        {
          "id": 10,
          "name": "Tên dịch vụ",
          "description": "Mô tả dịch vụ",
          "state": "active"
        }
      ]
    }
  ]
}
```

---

## 2. GET `/student_service/api/services`
**Mô tả:** Lấy danh sách tất cả dịch vụ.

**Input:**  
Không có.

**Response:**
```json
{
  "success": true,
  "message": "Danh sách dịch vụ",
  "data": [
    {
      "id": 10,
      "name": "Tên dịch vụ",
      "description": "Mô tả dịch vụ"
    }
  ]
}
```

---

## 3. GET `/student_service/api/service/<int:service_id>`
**Mô tả:** Lấy chi tiết một dịch vụ.

**Input:**  
- `service_id`: ID của dịch vụ (trên URL).

**Response:**
```json
{
  "success": true,
  "message": "Thành công",
  "data": {
    "id": 10,
    "name": "Tên dịch vụ",
    "description": "Mô tả dịch vụ",
    "titlenote": "",
    "state": "active",
    "group_id": 1,
    "group_name": "Tên nhóm",
    "step_ids": [
      {"id": 1, "name": "Tên bước", "description": "Mô tả bước"}
    ],
    "users": [
      {"id": 2, "name": "Tên người dùng"}
    ],
    "files": [
      {"id": 3, "name": "Tên file", "description": "Mô tả file"}
    ]
  }
}
```

---

## 4. POST `/api/public_user/refresh_token`
**Mô tả:** Làm mới JWT token.

**Input:**  
Header: `Authorization: Bearer <token>`

**Response:**
```json
{
  "success": true,
  "message": "Token refreshed",
  "token_auth": "<new_token>"
}
```

---

## 5. POST `/api/public_user/login`
**Mô tả:** Đăng nhập người dùng public qua API ngoài.

**Input:**
```json
{
  "username": "student_code",
  "password": "password",
  "fcm_device_token": "...",
  "device_id": "..."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Đăng nhập thành công",
  "data": {
    "id": 1,
    "name": "Tên đầy đủ",
    "email": "email@example.com",
    "phone": "0123456789",
    "gender": "Nam",
    "birthday": "YYYY-MM-DD",
    "can_login": false,
    "image_1920": true,
    "student_code": "123456",
    "avatar_url": "...",
    "university_name": "...",
    "id_card_number": "...",
    "id_card_date": "...",
    "id_card_issued_name": "...",
    "address": "...",
    "district_name": "...",
    "province_name": "...",
    "dormitory_full_name": "...",
    "dormitory_area_id": "...",
    "dormitory_house_name": "...",
    "dormitory_cluster_id": "...",
    "dormitory_room_type_name": "...",
    "dormitory_room_id": "...",
    "rent_id": "...",
    "access_token": "<jwt_token>",
    "refresh_token": "<refresh_token>"
  }
}
```

---

## 6. POST `/api/public_user/oauth`
**Mô tả:** Đăng nhập qua OAuth provider.

**Input:**
```json
{
  "provider": "google",
  "token": "<oauth_token>",
  "email": "email@example.com",
  "fullname": "Tên đầy đủ",
  "avatar": "...",
  "fcm_device_token": "...",
  "device_id": "...",
  "gender": "...",
  "phone": "..."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Thành công",
  "data": {
    "id": 1,
    "email": "email@example.com",
    "fullname": "Tên đầy đủ",
    "avatar_url": "...",
    "activated": true,
    "title_name": "...",
    "dormitory_area_id": 1,
    "dormitory_cluster_id": 2,
    "oauth": "google",
    "providers": ["google", "facebook"],
    "access_token": "<jwt_token>",
    "refresh_token": "<refresh_token>"
  }
}
```

---

## 7. POST `/api/service/request/create`
**Mô tả:** Tạo yêu cầu dịch vụ mới.

**Input:**  
Form-data:  
- `service_id`
- `request_id` (tùy chọn, nếu cập nhật)
- `request_user_id`
- `assign_user_id` (tùy chọn)
- `note`
- Files (đính kèm)

**Response:**
```json
{
  "success": true,
  "message": "Tạo yêu cầu dịch vụ thành công",
  "data": {
    "id": 1,
    "service_id": 10,
    "service_name": "Tên dịch vụ",
    "content": "Nội dung yêu cầu"
  }
}
```

---

## 8. GET `/api/service/request/user`
**Mô tả:** Lấy danh sách yêu cầu dịch vụ của một user, kèm lịch sử duyệt.

**Input:**
```json
{
  "user_id": 1
}
```

**Response:**
```json
{
  "success": true,
  "message": "Thành công",
  "data": [
    {
      "id": 1,
      "service": {
        "id": 10,
        "name": "Tên dịch vụ",
        "description": "Mô tả dịch vụ"
      },
      "name": "...",
      "note": "...",
      "request_date": "YYYY-MM-DD HH:MM:SS",
      "approve_user_id": 2,
      "approve_user_name": "Người duyệt",
      "approve_content": "...",
      "approve_date": "YYYY-MM-DD HH:MM:SS",
      "final_state": "approved",
      "finalfinal_data": "...",
      "histories": [
        {
          "id": 1,
          "step_id": 1,
          "step_name": "...",
          "state": "approved",
          "user_id": 2,
          "user_name": "Người duyệt",
          "note": "...",
          "date": "YYYY-MM-DD HH:MM:SS"
        }
      ]
    }
  ]
}
```

---

## 9. GET `/api/service/request/list`
**Mô tả:** Lấy danh sách yêu cầu dịch vụ cần duyệt theo user hoặc role.

**Input:**
```json
{
  "user_id": 1
}
```

**Response:**
```json
{
  "success": true,
  "message": "Thành công",
  "data": [
    {
      "id": 1,
      "name": "...",
      "note": "...",
      "request_date": "YYYY-MM-DD HH:MM:SS",
      "approve_user_id": 2,
      "approve_user_name": "Người duyệt",
      "approve_content": "...",
      "approve_date": "YYYY-MM-DD HH:MM:SS",
      "final_state": "approved",
      "finalfinal_data": "...",
      "service": {
        "id": 10,
        "name": "Tên dịch vụ",
        "description": "Mô tả dịch vụ"
      },
      "steps": [
        {
          "id": 1,
          "name": "...",
          "state": "pending",
          "base_secquence": 1,
          "approve_content": "...",
          "approve_date": "YYYY-MM-DD HH:MM:SS",
          "history_ids": [
            {
              "state": "approved",
              "note": "...",
              "date": "YYYY-MM-DD HH:MM:SS",
              "user_id": "Người duyệt"
            }
          ]
        }
      ]
    }
  ]
}
```

---

## 10. GET `/api/users/forassign`
**Mô tả:** Lấy danh sách user thuộc group "Settings".

**Input:**  
Không có.

**Response:**
```json
{
  "success": true,
  "message": "Danh sách users thuộc group Settings",
  "data": [
    {
      "id": 1,
      "name": "Tên người dùng",
      "login": "username",
      "email": "email@example.com"
    }
  ]
}
```

---

## 11. GET `/api/service/files`
**Mô tả:** Lấy danh sách tất cả file dịch vụ.

**Input:**  
Không có.

**Response:**
```json
{
  "success": true,
  "message": "Danh sách files",
  "data": [
    {
      "id": 1,
      "name": "Tên file",
      "description": "Mô tả file"
    }
  ]
}
```

---

## 12. GET `/api/service/request/detail/<int:request_id>`
**Mô tả:** Lấy chi tiết một yêu cầu dịch vụ.

**Input:**  
- `request_id`: ID của yêu cầu (trên URL).

**Response:**
```json
{
  "success": true,
  "message": "Thành công",
  "data": {
    "id": 1,
    "service_id": 10,
    "name": "...",
    "note": "...",
    "image_attachment_ids": [
      {"id": 1, "name": "file.png", "url": "..."}
    ],
    "request_date": "YYYY-MM-DD HH:MM:SS",
    "request_user_id": 1,
    "request_user_name": "...",
    "step_ids": [
      {
        "id": 1,
        "name": "...",
        "state": "pending",
        "sequence": 1,
        "approve_content": "...",
        "approve_date": "YYYY-MM-DD HH:MM:SS",
        "file_ids": [
          {"id": 1, "name": "Tên file", "description": "..."}
        ],
        "file_checkbox_ids": [
          {"id": 2, "name": "Tên file", "description": "..."}
        ],
        "history_ids": [
          {
            "id": 1,
            "state": "approved",
            "user_id": 2,
            "user_name": "Người duyệt",
            "note": "...",
            "date": "YYYY-MM-DD HH:MM:SS"
          }
        ]
      }
    ],
    "users": [
      {"id": 2, "name": "Người duyệt"}
    ],
    "role_ids": [
      {"id": 1, "name": "Tên vai trò"}
    ],
    "final_state": "approved",
    "final_data": "...",
    "approve_content": "...",
    "approve_date": "YYYY-MM-DD HH:MM:SS",
    "histories": [
      {
        "id": 1,
        "step_id": 1,
        "step_name": "...",
        "state": "approved",
        "user_id": 2,
        "user_name": "Người duyệt",
        "note": "...",
        "date": "YYYY-MM-DD HH:MM:SS"
      }
    ]
  }
}
```

---

## 13. POST `/api/service/request/step/submit`
**Mô tả:** Submit duyệt một bước của yêu cầu dịch vụ.

**Input:**
```json
{
  "request_id": 1,
  "step_id": 1,
  "user_id": 2,
  "note": "...",
  "act": "approved",
  "next_user_id": 3,
  "docs": [1,2],
  "final_data": "..."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Bước duyệt thành công",
  "data": { ...các trường của step... }
}
```

---

## 14. GET `/api/notifications/my`
**Mô tả:** Lấy danh sách thông báo của user.

**Input:**
```json
{
  "user_id": 1
}
```

**Response:**
```json
{
  "success": true,
  "message": "Danh sách thông báo",
  "data": [
    {
      "id": 1,
      "title": "Tiêu đề thông báo",
      "body": "Nội dung thông báo",
      "is_read": false,
      "create_date": "YYYY-MM-DD HH:MM:SS",
      "data": {}
    }
  ]
}
```

---

## 15. POST `/api/service/request/approve`
**Mô tả:** Duyệt một bước của yêu cầu dịch vụ.

**Input:**
```json
{
  "request_id": 1,
  "user_id": 2,
  "asign_user_id": 3,
  "step_id": 1,
  "checked_ids": [1,2],
  "note": "...",
  "final": "..."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Yêu cầu đã được duyệt",
  "data": {
    "request_id": 1,
    "step": { ...các trường của step... }
  }
}
```

---
