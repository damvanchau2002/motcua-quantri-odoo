#!/usr/bin/env python3
"""
Script đơn giản để test email thông báo
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def test_smtp_connection():
    """Test kết nối SMTP đơn giản"""
    try:
        print("🔄 Đang test kết nối SMTP...")
        
        # Tạo email test
        msg = MIMEMultipart()
        msg['From'] = 'admin@localhost'
        msg['To'] = 'test@example.com'
        msg['Subject'] = 'Test Email - Thông báo yêu cầu quá hạn'
        
        body = """
        Đây là email test để kiểm tra chức năng gửi thông báo quá hạn.
        
        Thông tin yêu cầu:
        - Mã yêu cầu: TEST-001
        - Loại yêu cầu: Test Service
        - Sinh viên: Test Student
        - Hạn xử lý: 01/01/2025
        - Trạng thái: Quá hạn
        
        Vui lòng xử lý yêu cầu này ngay lập tức.
        
        Trân trọng,
        Hệ thống quản lý sinh viên
        """
        
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # Kết nối và gửi email
        server = smtplib.SMTP('localhost', 1025)
        server.sendmail('admin@localhost', ['test@example.com'], msg.as_string())
        server.quit()
        
        print("✅ Gửi email test thành công!")
        print("📧 Kiểm tra terminal SMTP để xem email đã được nhận")
        return True
        
    except Exception as e:
        print(f"❌ Lỗi khi gửi email: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Test gửi email thông báo quá hạn...")
    success = test_smtp_connection()
    
    if success:
        print("\n✅ Test email thành công!")
        print("📧 Email đã được gửi đến SMTP Debug Server tại localhost:1025")
    else:
        print("\n❌ Test email thất bại!")