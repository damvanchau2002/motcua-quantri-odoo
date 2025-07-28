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

This document describes all API endpoints provided in `service_api.py`, including request and response formats.

---

## 1. GET `/api/service/groups`
**Description:** Get all service groups and their services.

**Response:**
```json
{
  "success": true,
  "message": "Danh sách nhóm dịch vụ và dịch vụ",
  "data": [
    {
      "id": 1,
      "name": "Group Name",
      "description": "Group Description",
      "parent_id": null,
      "services": [
        {
          "id": 10,
          "name": "Service Name",
          "description": "Service Description",
          "state": "active"
        }
      ]
    }
  ]
}
```

---

## 2. GET `/student_service/api/services`
**Description:** List all services.

**Response:**
```json
{
  "success": true,
  "message": "Danh sách dịch vụ",
  "data": [
    {
      "id": 10,
      "name": "Service Name",
      "description": "Service Description"
    }
  ]
}
```

---

## 3. GET `/student_service/api/service/<int:service_id>`
**Description:** Get details of a specific service.

**Response:**
```json
{
  "success": true,
  "message": "Thành công",
  "data": {
    "id": 10,
    "name": "Service Name",
    "description": "Service Description",
    "titlenote": "",
    "state": "active",
    "group_id": 1,
    "group_name": "Group Name",
    "step_ids": [
      {"id": 1, "name": "Step 1", "description": "Step Description"}
    ],
    "users": [
      {"id": 2, "name": "User Name"}
    ],
    "files": [
      {"id": 3, "name": "File Name", "description": "File Description"}
    ]
  }
}
```

---

## 4. POST `/api/public_user/refresh_token`
**Description:** Refresh JWT token.

**Request:**  
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
**Description:** Login public user via external API.

**Request:**
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
    "name": "Full Name",
    "email": "email@example.com",
    "phone": "0123456789",
    "gender": "Male",
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
**Description:** Login via OAuth provider.

**Request:**
```json
{
  "provider": "google",
  "token": "<oauth_token>",
  "email": "email@example.com",
  "fullname": "Full Name",
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
    "fullname": "Full Name",
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
**Description:** Create a new service request.

**Request:**  
Form-data:  
- `service_id`
- `request_id` (optional, for update)
- `request_user_id`
- `assign_user_id` (optional)
- `note`
- Files (attachments)

**Response:**
```json
{
  "success": true,
  "message": "Tạo yêu cầu dịch vụ thành công",
  "data": {
    "id": 1,
    "service_id": 10,
    "service_name": "Service Name",
    "content": "Request note"
  }
}
```

---

## 8. GET `/api/service/request/user`
**Description:** List service requests of a user, including approval history.

**Request:**
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
        "name": "Service Name",
        "description": "Service Description"
      },
      "name": "...",
      "note": "...",
      "request_date": "YYYY-MM-DD HH:MM:SS",
      "approve_user_id": 2,
      "approve_user_name": "Approver",
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
          "user_name": "Approver",
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
**Description:** List service requests for approval by user or role.

**Request:**
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
      "approve_user_name": "Approver",
      "approve_content": "...",
      "approve_date": "YYYY-MM-DD HH:MM:SS",
      "final_state": "approved",
      "finalfinal_data": "...",
      "service": {
        "id": 10,
        "name": "Service Name",
        "description": "Service Description"
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
              "user_id": "Approver"
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
**Description:** List users in the "Settings" group.

**Response:**
```json
{
  "success": true,
  "message": "Danh sách users thuộc group Settings",
  "data": [
    {
      "id": 1,
      "name": "User Name",
      "login": "username",
      "email": "email@example.com"
    }
  ]
}
```

---

## 11. GET `/api/service/files`
**Description:** List all service files.

**Response:**
```json
{
  "success": true,
  "message": "Danh sách files",
  "data": [
    {
      "id": 1,
      "name": "File Name",
      "description": "File Description"
    }
  ]
}
```

---

## 12. GET `/api/service/request/detail/<int:request_id>`
**Description:** Get details of a service request.

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
          {"id": 1, "name": "File Name", "description": "..."}
        ],
        "file_checkbox_ids": [
          {"id": 2, "name": "File Name", "description": "..."}
        ],
        "history_ids": [
          {
            "id": 1,
            "state": "approved",
            "user_id": 2,
            "user_name": "Approver",
            "note": "...",
            "date": "YYYY-MM-DD HH:MM:SS"
          }
        ]
      }
    ],
    "users": [
      {"id": 2, "name": "Approver"}
    ],
    "role_ids": [
      {"id": 1, "name": "Role Name"}
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
        "user_name": "Approver",
        "note": "...",
        "date": "YYYY-MM-DD HH:MM:SS"
      }
    ]
  }
}
```

---

## 13. POST `/api/service/request/step/submit`
**Description:** Submit approval for a request step.

**Request:**
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
  "data": { ...step fields... }
}
```

---

## 14. GET `/api/notifications/my`
**Description:** Get notifications for a user.

**Request:**
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
      "title": "Notification Title",
      "body": "Notification Body",
      "is_read": false,
      "create_date": "YYYY-MM-DD HH:MM:SS",
      "data": {}
    }
  ]
}
```

---

## 15. POST `/api/service/request/approve`
**Description:** Approve a service request step.

**Request:**
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
    "step": { ...step fields... }
  }
}
```

---
