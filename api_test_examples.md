# Maintenance Mode API Documentation

## Tổng quan
API này cho phép quản lý chế độ bảo trì của ứng dụng. Khi bảo trì được bật, client (mobile/web) sẽ nhận được thông báo và khóa toàn bộ thao tác khác.

## Endpoints

### 1. Lấy trạng thái bảo trì
**GET** `/api/maintenance/status`

**Mô tả:** Lấy trạng thái bảo trì hiện tại

**Authentication:** Không cần

**Response:**
```json
{
    "status": "on/off",
    "message": "Nội dung thông báo",
    "duration": "Thời gian dự kiến",
    "start_time": "2024-01-01T10:00:00",
    "end_time": "2024-01-01T12:00:00"
}
```

**Ví dụ sử dụng:**
```bash
# PowerShell
Invoke-WebRequest -Uri "http://localhost:8069/api/maintenance/status" -Method GET

# cURL
curl -X GET "http://localhost:8069/api/maintenance/status"

# JavaScript (Fetch API)
fetch('http://localhost:8069/api/maintenance/status')
  .then(response => response.json())
  .then(data => console.log(data));
```

### 2. Cập nhật trạng thái bảo trì
**POST** `/api/maintenance/set`

**Mô tả:** Cập nhật trạng thái bảo trì (chỉ admin)

**Authentication:** Cần đăng nhập với quyền admin

**Request Body:**
```json
{
    "status": "on/off",
    "message": "Nội dung thông báo (optional)",
    "duration": "Thời gian dự kiến (optional)"
}
```

**Response:**
```json
{
    "success": true,
    "status": "on/off",
    "message": "Thông báo",
    "duration": "Thời gian",
    "timestamp": "2024-01-01T10:00:00"
}
```

**Ví dụ sử dụng:**
```bash
# PowerShell
$body = @{
    status = "on"
    message = "Hệ thống đang nâng cấp"
    duration = "2 giờ"
} | ConvertTo-Json

Invoke-WebRequest -Uri "http://localhost:8069/api/maintenance/set" -Method POST -Body $body -ContentType "application/json" -Headers @{"Authorization"="Bearer YOUR_TOKEN"}

# cURL
curl -X POST "http://localhost:8069/api/maintenance/set" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "status": "on",
    "message": "Hệ thống đang nâng cấp",
    "duration": "2 giờ"
  }'

# JavaScript (Fetch API)
fetch('http://localhost:8069/api/maintenance/set', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer YOUR_TOKEN'
  },
  body: JSON.stringify({
    status: 'on',
    message: 'Hệ thống đang nâng cấp',
    duration: '2 giờ'
  })
})
.then(response => response.json())
.then(data => console.log(data));
```

### 3. Chuyển đổi trạng thái bảo trì
**POST** `/api/maintenance/toggle`

**Mô tả:** Chuyển đổi trạng thái bảo trì (on ↔ off)

**Authentication:** Cần đăng nhập với quyền admin

**Response:**
```json
{
    "success": true,
    "status": "on/off",
    "message": "Thông báo"
}
```

**Ví dụ sử dụng:**
```bash
# PowerShell
Invoke-WebRequest -Uri "http://localhost:8069/api/maintenance/toggle" -Method POST -Headers @{"Authorization"="Bearer YOUR_TOKEN"}

# cURL
curl -X POST "http://localhost:8069/api/maintenance/toggle" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## Cách sử dụng trong ứng dụng

### 1. Kiểm tra trạng thái bảo trì khi khởi động app
```javascript
async function checkMaintenanceStatus() {
    try {
        const response = await fetch('/api/maintenance/status');
        const data = await response.json();
        
        if (data.status === 'on') {
            // Hiển thị màn hình bảo trì
            showMaintenanceScreen(data.message, data.duration);
            return false; // Không cho phép sử dụng app
        }
        
        return true; // Cho phép sử dụng app bình thường
    } catch (error) {
        console.error('Lỗi kiểm tra trạng thái bảo trì:', error);
        return true; // Mặc định cho phép sử dụng nếu có lỗi
    }
}

function showMaintenanceScreen(message, duration) {
    // Hiển thị toàn màn hình thông báo bảo trì
    const maintenanceHTML = `
        <div id="maintenance-overlay" style="
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.9);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 9999;
            color: white;
            text-align: center;
        ">
            <div>
                <h1>🔧 Ứng dụng đang bảo trì</h1>
                <p>${message}</p>
                <p>Thời gian dự kiến: ${duration}</p>
                <p>Vui lòng quay lại sau!</p>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', maintenanceHTML);
}
```

### 2. Kiểm tra định kỳ trong khi sử dụng app
```javascript
// Kiểm tra mỗi 30 giây
setInterval(async () => {
    const isAppAvailable = await checkMaintenanceStatus();
    
    if (!isAppAvailable) {
        // Khóa tất cả thao tác
        document.body.style.pointerEvents = 'none';
    } else {
        // Mở khóa nếu bảo trì đã kết thúc
        const overlay = document.getElementById('maintenance-overlay');
        if (overlay) {
            overlay.remove();
            document.body.style.pointerEvents = 'auto';
        }
    }
}, 30000);
```

### 3. Quản lý từ admin panel
Admin có thể quản lý bảo trì từ:
1. **Giao diện web:** Menu "Cài đặt" → "Chế độ bảo trì"
2. **API trực tiếp:** Sử dụng các endpoint `/api/maintenance/set` hoặc `/api/maintenance/toggle`

## Các định dạng duration được hỗ trợ
- `"30 phút"` → 30 minutes
- `"2 giờ"` → 2 hours  
- `"1 ngày"` → 1 day
- `"15 phút"` → 15 minutes
- `"3 giờ"` → 3 hours

## Lưu ý quan trọng
1. **Tự động tắt:** Hệ thống sẽ tự động tắt bảo trì khi hết thời gian dự kiến
2. **CORS:** API hỗ trợ CORS cho phép gọi từ domain khác
3. **Quyền hạn:** Chỉ admin mới có thể thay đổi trạng thái bảo trì
4. **Lưu trữ:** Trạng thái được lưu trong `ir.config_parameter` của Odoo

## Error Codes
- **400:** Dữ liệu không hợp lệ
- **403:** Không có quyền thực hiện thao tác
- **500:** Lỗi hệ thống

## Testing
Chạy file test để kiểm tra logic:
```bash
python test_maintenance_api.py
```