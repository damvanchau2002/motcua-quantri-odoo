# API Yêu Cầu Gia Hạn - Tài Liệu Hướng Dẫn

## Tổng Quan
Tài liệu này mô tả các API endpoint để quản lý yêu cầu gia hạn trong hệ thống Student Request.

## Base URL
```
http://localhost:8069
```

## 1. Tạo Yêu Cầu Gia Hạn

### Endpoint
```
POST /api/service/request/extension/create
```

### Request Body
```json
{
    "request_id": 28,
    "hours": 2,
    "reason": "Cần thêm thời gian để hoàn thành",
    "user_id": 11  // Tùy chọn: ID của user gửi yêu cầu. Nếu không có, sẽ sử dụng user hiện tại
}
```

### Tham Số
- `request_id` (integer, bắt buộc): ID của yêu cầu dịch vụ cần gia hạn
- `hours` (integer, bắt buộc): Số giờ gia hạn (1-720 giờ)
- `reason` (string, bắt buộc): Lý do gia hạn
- `user_id` (integer, tùy chọn): ID của user gửi yêu cầu. Nếu không có, sẽ sử dụng user hiện tại

### Response
```json
{
    "success": true,
    "message": "Đã gửi yêu cầu gia hạn 2 giờ",
    "data": {
        "extension_id": 15,
        "hours": 2,
        "user_id": 2,
        "requester": {
            "id": 2,
            "name": "Mitchell Admin",
            "email": "admin@example.com",
            "phone": "0123456789",
            "login": "admin"
        },
        "request_date": "2025-10-31 04:15:30"
    }
}
```

**Lưu ý:** API này sẽ tự động gửi yêu cầu gia hạn với trạng thái `submitted` ngay lập tức, không cần thêm bước gửi riêng biệt.

## 2. Lấy Danh Sách Yêu Cầu Gia Hạn

### Endpoint
```
GET /api/service/request/extension/list
```

### Query Parameters
- `request_id` (optional): ID của yêu cầu dịch vụ cụ thể
- `state` (optional): Trạng thái (draft, submitted, approved, rejected)
- `limit` (optional): Số lượng bản ghi tối đa (mặc định: 50)
- `offset` (optional): Vị trí bắt đầu (mặc định: 0)

### Example Request
```
GET /api/service/request/extension/list?request_id=28&state=submitted&limit=10&offset=0
```

### Response
```json
{
    "success": true,
    "data": [
        {
            "id": 15,
            "name": "EXT-2025-001",
            "hours": 2,
            "reason": "Cần thêm thời gian để hoàn thành",
            "state": "submitted",
            "user_id": 2,
            "request_date": "2025-10-31 04:15:30",
            "approval_date": null,
            "rejection_date": null,
            "rejection_reason": "",
            "original_deadline": "2025-10-30 23:59:59",
            "new_deadline": "2025-11-01 01:59:59",
            "requester": {
                "id": 2,
                "name": "Mitchell Admin",
                "email": "admin@example.com",
                "phone": "0123456789",
                "login": "admin"
            },
            "approver": null,
            "service_request": {
                "id": 28,
                "name": "REQ-2025-028",
                "service_name": "Dịch vụ hỗ trợ học tập",
                "current_deadline": "2025-10-30 23:59:59"
            }
        }
    ],
    "total": 1,
    "limit": 10,
    "offset": 0
}
```

## 3. Lấy Thông Tin Chi Tiết Yêu Cầu Gia Hạn

### Endpoint
```
GET /api/service/request/extension/{extension_id}
```

### Example Request
```
GET /api/service/request/extension/15
```

### Response
```json
{
    "success": true,
    "data": {
        "id": 15,
        "name": "EXT-2025-001",
        "hours": 2,
        "reason": "Cần thêm thời gian để hoàn thành",
        "state": "submitted",
        "user_id": 2,
        "request_date": "2025-10-31 04:15:30",
        "approval_date": null,
        "rejection_date": null,
        "rejection_reason": "",
        "original_deadline": "2025-10-30 23:59:59",
        "new_deadline": "2025-11-01 01:59:59",
        "requester": {
            "id": 2,
            "name": "Mitchell Admin",
            "email": "admin@example.com",
            "phone": "0123456789",
            "login": "admin"
        },
        "approver": null,
        "service_request": {
            "id": 28,
            "name": "REQ-2025-028",
            "service_name": "Dịch vụ hỗ trợ học tập",
            "current_deadline": "2025-10-30 23:59:59",
            "state": "processing"
        }
    }
}
```

## Trạng Thái Yêu Cầu Gia Hạn

- `draft`: Bản nháp
- `submitted`: Đã gửi yêu cầu
- `approved`: Đã được duyệt
- `rejected`: Bị từ chối

## Thông Tin Người Gửi (Requester)

Mỗi yêu cầu gia hạn sẽ bao gồm thông tin chi tiết về người gửi:
- `id`: ID của người dùng
- `name`: Tên đầy đủ
- `email`: Địa chỉ email
- `phone`: Số điện thoại
- `login`: Tên đăng nhập

## Xử Lý Lỗi

Tất cả API sẽ trả về format lỗi như sau:
```json
{
    "success": false,
    "message": "Mô tả lỗi chi tiết"
}
```

## CORS Support

Tất cả API đều hỗ trợ CORS và có thể được gọi từ frontend JavaScript.

## Ví Dụ Sử Dụng JavaScript

```javascript
// Tạo yêu cầu gia hạn với user_id tùy chọn
const createExtension = async () => {
    const response = await fetch('http://localhost:8069/api/service/request/extension/create', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            request_id: 35,
            hours: 2,
            user_id: 11,  // Tùy chọn: chỉ định user gửi yêu cầu
            reason: "Cần thêm thời gian để hoàn thành"
        })
    });
    
    const result = await response.json();
    console.log('User ID:', result.data.user_id);
    console.log('Sender info:', result.data.requester);
};

// Tạo yêu cầu gia hạn không chỉ định user_id (sử dụng user hiện tại)
const createExtensionCurrentUser = async () => {
    const response = await fetch('http://localhost:8069/api/service/request/extension/create', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            request_id: 35,
            hours: 2,
            reason: "Cần thêm thời gian để hoàn thành"
        })
    });
    
    const result = await response.json();
    console.log('User ID:', result.data.user_id);
    console.log('Sender info:', result.data.requester);
};

// Lấy danh sách yêu cầu gia hạn
const getExtensions = async () => {
    const response = await fetch('http://localhost:8069/api/service/request/extension/list?request_id=28');
    const result = await response.json();
    
    result.data.forEach(ext => {
        console.log('User ID:', ext.user_id);
        console.log('Requester:', ext.requester.name, ext.requester.email);
    });
};
```