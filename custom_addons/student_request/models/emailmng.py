from odoo import models, fields

class StudentEmailTemplate(models.Model):
    _name = 'student.emailmng.template'
    _description = 'Student Email Template'

    name = fields.Char(string='Template Name', required=True)
    subject = fields.Char(string='Subject', required=True)
    body_html = fields.Html(string='Body (HTML)', required=True)
    active = fields.Boolean(string='Active', default=True)


def send_email_request(env, request_obj, send_type=0, to_emails=None):
    """
    Gửi email thông báo khi Yêu cầu dịch vụ có thay đổi (tương tự send_fcm_request)
    :param env: Odoo environment
    :param request_obj: Đối tượng yêu cầu dịch vụ
    :param send_type: Loại thông báo (xem send_fcm_request)
    :param to_emails: Danh sách email nhận (nếu None sẽ lấy email của request_user_id)
    """
    # Cấu hình SMTP Google
    SMTP_SERVER = 'smtp.gmail.com'
    SMTP_PORT = 587
    SMTP_USER = 'your_email@gmail.com'  # Thay bằng email gửi
    SMTP_PASSWORD = 'your_app_password' # Thay bằng app password

    # Xác định nội dung email
    subject = ""
    body = ""
    try:
        if send_type == 0:
            subject = f"Yêu cầu dịch vụ {request_obj.service_id.name} đã được tạo thành công"
            body = f"Yêu cầu của bạn đã được tạo thành công. Nội dung: {request_obj.note}"
        elif send_type == 1:
            subject = f"Yêu cầu dịch vụ {request_obj.service_id.name} đã được cập nhật"
            body = f"Yêu cầu của bạn đã được cập nhật. Nội dung: {request_obj.note}"
        elif send_type == 2:
            subject = f"Yêu cầu dịch vụ {request_obj.service_id.name} đã được cập nhật bước"
            body = f"Yêu cầu của bạn đã được cập nhật: {request_obj.note}"
        elif send_type == 3:
            subject = f"Yêu cầu dịch vụ {request_obj.service_id.name} đã hoàn thành cần nghiệm thu"
            body = f"Yêu cầu của bạn đã được hoàn thành. {request_obj.note}. Bạn hãy kiểm tra chi tiết và nghiệm thu trong ứng dụng."
        elif send_type == 4:
            subject = f"Bạn đã gửi đánh giá {request_obj.service_id.name}"
            body = f"Đánh giá cho yêu cầu {request_obj.service_id.name} của bạn đã được gửi."
        elif send_type == 5:
            subject = f"Đã gửi khiếu nại dịch vụ {request_obj.service_id.name}"
            body = f"Bạn đã gửi khiếu nại yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note}"
        elif send_type == 6:
            subject = f"Bạn đã gửi nghiệm thu yêu cầu dịch vụ {request_obj.service_id.name}"
            body = f"Gửi nghiệm thu yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note} thành công"
        elif send_type == 7:
            subject = f"Yêu cầu dịch vụ {request_obj.service_id.name} đã được gia hạn"
            body = f"Yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note} đã gia hạn"
        elif send_type == 8:
            subject = f"Yêu cầu dịch vụ {request_obj.service_id.name} của bạn đã hủy"
            body = f"Yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note} đã hủy"
        elif send_type == 9:
            subject = f"Yêu cầu dịch vụ {request_obj.service_id.name} đang xử lý sửa lại"
            body = f"Sửa lại yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note}: {request_obj.final_data}"
        elif send_type == 10:
            subject = f"Yêu cầu dịch vụ {request_obj.service_id.name} đã nghiệm thu hoàn thành"
            body = f"Yêu cầu của Bạn: {request_obj.service_id.name}. {request_obj.note} đã được nghiệm thu và đóng lại"
        elif send_type == 11:
            subject = f"Cán bộ quản lý đã nghiệm thu yêu cầu dịch vụ {request_obj.service_id.name} của bạn"
            body = f"Đã nghiệm thu yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note} thành công"
        elif send_type == 13:
            subject = f"Yêu cầu dịch vụ {request_obj.service_id.name} của bạn sắp hết hạn"
            body = f"Yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note} sắp hết hạn, cần bạn xử lý gấp hoặc gia hạn yêu cầu này"
        else:
            subject = "Thông báo yêu cầu dịch vụ"
            body = f"Yêu cầu dịch vụ có thay đổi: {request_obj.note}"

        # Lấy email người nhận
        if not to_emails:
            to_emails = []
            if hasattr(request_obj.request_user_id, 'email') and request_obj.request_user_id.email:
                to_emails.append(request_obj.request_user_id.email)
        if not to_emails:
            return False

        # Tạo email
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = ', '.join(to_emails)
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        # Gửi email
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, to_emails, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return False