#!/usr/bin/env python3
"""
Script để test chức năng gửi email thông báo quá hạn
"""

import xmlrpc.client
import datetime

# Cấu hình kết nối Odoo
url = 'http://localhost:8069'
db = 'odoo_db'
username = 'admin'
password = 'admin'

def test_email_notifications():
    """Test chức năng gửi email thông báo quá hạn"""
    
    # Kết nối đến Odoo
    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
    uid = common.authenticate(db, username, password, {})
    
    if not uid:
        print("❌ Không thể đăng nhập vào Odoo")
        return False
    
    print(f"✅ Đăng nhập thành công với user ID: {uid}")
    
    # Kết nối đến object service
    models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
    
    try:
        # 1. Tìm các yêu cầu đã quá hạn
        expired_requests = models.execute_kw(db, uid, password,
            'student.service.request', 'search_read',
            [[('is_expired', '=', True)]],
            {'fields': ['name', 'service_id', 'student_id', 'deadline', 'state', 'expired_date']}
        )
        
        print(f"\n📋 Tìm thấy {len(expired_requests)} yêu cầu đã quá hạn:")
        for req in expired_requests:
            print(f"  - {req['name']}: {req['service_id'][1] if req['service_id'] else 'N/A'}")
            print(f"    Sinh viên: {req['student_id'][1] if req['student_id'] else 'N/A'}")
            print(f"    Hạn: {req['deadline']}, Trạng thái: {req['state']}")
        
        # 2. Chạy cron job kiểm tra quá hạn
        print(f"\n🔄 Chạy cron job kiểm tra yêu cầu quá hạn...")
        result = models.execute_kw(db, uid, password,
            'student.service.request', '_cron_check_expired_requests', [])
        
        print(f"✅ Cron job đã chạy thành công")
        
        # 3. Kiểm tra mail queue
        mail_queue = models.execute_kw(db, uid, password,
            'mail.mail', 'search_read',
            [[('create_date', '>=', datetime.datetime.now().strftime('%Y-%m-%d'))]],
            {'fields': ['subject', 'email_to', 'state', 'create_date'], 'limit': 10}
        )
        
        print(f"\n📧 Mail queue hôm nay ({len(mail_queue)} emails):")
        for mail in mail_queue:
            print(f"  - {mail['subject']}")
            print(f"    Đến: {mail['email_to']}, Trạng thái: {mail['state']}")
            print(f"    Tạo lúc: {mail['create_date']}")
        
        # 4. Test gửi email thông báo cho một yêu cầu cụ thể
        if expired_requests:
            test_request = expired_requests[0]
            print(f"\n🧪 Test gửi email cho yêu cầu: {test_request['name']}")
            
            # Gọi method gửi email thông báo quá hạn
            models.execute_kw(db, uid, password,
                'student.service.request', '_send_expiry_notification',
                [test_request['id']])
            
            print(f"✅ Đã gửi email thông báo quá hạn")
        
        return True
        
    except Exception as e:
        print(f"❌ Lỗi khi test email: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Bắt đầu test chức năng email thông báo quá hạn...")
    success = test_email_notifications()
    
    if success:
        print("\n✅ Test hoàn thành! Kiểm tra terminal SMTP để xem email đã được gửi.")
        print("📧 SMTP Debug Server đang chạy tại localhost:1025")
    else:
        print("\n❌ Test thất bại!")