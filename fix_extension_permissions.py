#!/usr/bin/env python3
"""
Script để kiểm tra và sửa lỗi quyền duyệt gia hạn
"""

import xmlrpc.client
import sys

# Cấu hình kết nối Odoo
url = 'http://localhost:8069'
db = 'odoo_db'

# Thử các thông tin đăng nhập khác nhau
login_options = [
    ('admin', 'admin'),
    ('admin', '123456'),
    ('admin', 'password'),
    ('admin', ''),
]

def connect_odoo():
    """Kết nối đến Odoo với nhiều tùy chọn đăng nhập"""
    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
    
    for username, password in login_options:
        try:
            print(f"🔐 Thử đăng nhập với: {username} / {'*' * len(password) if password else '(trống)'}")
            uid = common.authenticate(db, username, password, {})
            if uid:
                models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
                print(f"✅ Đăng nhập thành công! (User ID: {uid})")
                return uid, models, username, password
        except Exception as e:
            print(f"❌ Lỗi với {username}: {e}")
            continue
    
    print("❌ Không thể đăng nhập với bất kỳ thông tin nào")
    return None, None, None, None

def check_database_exists():
    """Kiểm tra database có tồn tại không"""
    try:
        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
        # Thử phương thức db_list thay vì list
        try:
            db_list = common.db_list()
        except:
            # Nếu không có phương thức db_list, thử version để kiểm tra kết nối
            version = common.version()
            print(f"📋 Odoo version: {version}")
            return True  # Giả sử database tồn tại nếu có thể kết nối
        
        print(f"📋 Các database có sẵn: {db_list}")
        return db in db_list
    except Exception as e:
        print(f"❌ Lỗi kiểm tra database: {e}")
        # Thử kết nối trực tiếp để kiểm tra
        return True

def check_user_groups(uid, models, username, password):
    """Kiểm tra nhóm quyền của user hiện tại"""
    try:
        user_data = models.execute_kw(db, uid, password, 'res.users', 'read', 
                                    [uid], {'fields': ['name', 'groups_id', 'login']})
        
        if user_data:
            user = user_data[0]
            print(f"\n👤 Thông tin user: {user['name']} (login: {user['login']})")
            
            # Lấy thông tin các nhóm
            if user['groups_id']:
                groups = models.execute_kw(db, uid, password, 'res.groups', 'read',
                                         [user['groups_id']], {'fields': ['name', 'category_id']})
                
                print("📋 Các nhóm quyền:")
                manager_found = False
                for group in groups:
                    print(f"   - {group['name']}")
                    if 'Student Request Manager' in group['name'] or 'Settings' in group['name'] or 'Administration' in group['name']:
                        manager_found = True
                        
                return manager_found
            else:
                print("❌ User không có nhóm quyền nào")
                return False
    except Exception as e:
        print(f"❌ Lỗi kiểm tra user groups: {e}")
        return False

def check_extension_views_access(uid, models, username, password):
    """Kiểm tra quyền truy cập các view gia hạn"""
    try:
        # Kiểm tra quyền truy cập model request.extension
        extension_access = models.execute_kw(db, uid, password, 'ir.model.access', 'search_read',
                                           [[('model_id.model', '=', 'request.extension')]], 
                                           {'fields': ['name', 'perm_read', 'perm_write', 'perm_create', 'perm_unlink', 'group_id']})
        
        print(f"\n🔐 Quyền truy cập model request.extension:")
        for access in extension_access:
            group_name = access['group_id'][1] if access['group_id'] else 'Tất cả user'
            print(f"   - {access['name']}: R:{access['perm_read']} W:{access['perm_write']} C:{access['perm_create']} D:{access['perm_unlink']} - Nhóm: {group_name}")
            
        return len(extension_access) > 0
        
    except Exception as e:
        print(f"❌ Lỗi kiểm tra quyền truy cập: {e}")
        return False

def check_extension_requests(uid, models, username, password):
    """Kiểm tra các yêu cầu gia hạn"""
    try:
        # Tìm tất cả yêu cầu gia hạn
        all_extensions = models.execute_kw(db, uid, password, 'request.extension', 'search_read',
                                         [[]], 
                                         {'fields': ['name', 'request_id', 'requested_by', 'state', 'hours']})
        
        print(f"\n📋 Tổng cộng {len(all_extensions)} yêu cầu gia hạn:")
        
        pending_count = 0
        for ext in all_extensions:
            status_icon = "⏳" if ext['state'] == 'submitted' else "✅" if ext['state'] == 'approved' else "❌" if ext['state'] == 'rejected' else "📝"
            print(f"   {status_icon} {ext['name']} - {ext['state']} - {ext['hours']} giờ")
            if ext['state'] == 'submitted':
                pending_count += 1
                
        print(f"\n🔔 Có {pending_count} yêu cầu đang chờ duyệt")
        return all_extensions
        
    except Exception as e:
        print(f"❌ Lỗi kiểm tra extension requests: {e}")
        return []

def main():
    """Hàm chính"""
    print("🔍 Kiểm tra quyền duyệt gia hạn...")
    
    # Kiểm tra database
    if not check_database_exists():
        print(f"❌ Database '{db}' không tồn tại!")
        sys.exit(1)
    
    # Kết nối Odoo
    uid, models, username, password = connect_odoo()
    if not uid:
        print("\n💡 Hướng dẫn:")
        print("1. Truy cập http://localhost:8069")
        print("2. Tạo database mới hoặc đăng nhập với thông tin đúng")
        print("3. Chạy lại script này")
        sys.exit(1)
    
    # Kiểm tra quyền user
    has_permission = check_user_groups(uid, models, username, password)
    
    # Kiểm tra quyền truy cập model
    has_model_access = check_extension_views_access(uid, models, username, password)
    
    # Kiểm tra các yêu cầu gia hạn
    extensions = check_extension_requests(uid, models, username, password)
    
    print("\n" + "="*50)
    print("📊 TÓM TẮT KIỂM TRA:")
    print("="*50)
    print(f"✅ Kết nối Odoo: Thành công")
    print(f"{'✅' if has_permission else '⚠️'} Quyền quản lý: {'Có' if has_permission else 'Cần kiểm tra'}")
    print(f"{'✅' if has_model_access else '❌'} Quyền model: {'Có' if has_model_access else 'Không có'}")
    print(f"📋 Tổng yêu cầu gia hạn: {len(extensions)}")
    
    pending_extensions = [e for e in extensions if e['state'] == 'submitted']
    if pending_extensions:
        print(f"🔔 Yêu cầu chờ duyệt: {len(pending_extensions)}")
        print("\n💡 Để duyệt gia hạn:")
        print("1. Vào menu 'Quản lý gia hạn' > 'Chờ duyệt gia hạn'")
        print("2. Mở từng yêu cầu và nhấn nút 'Duyệt' hoặc 'Từ chối'")
    else:
        print("✅ Không có yêu cầu nào chờ duyệt")

if __name__ == "__main__":
    main()