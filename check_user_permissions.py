#!/usr/bin/env python3
import sys
import os

# Add Odoo to path
sys.path.append(os.path.dirname(__file__))

import odoo
from odoo import api, SUPERUSER_ID

def check_user_permissions():
    # Parse config
    odoo.tools.config.parse_config(['-c', 'odoo.cfg'])
    db_name = odoo.tools.config['db_name']
    
    # Get registry and cursor
    registry = odoo.registry(db_name)
    
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        
        try:
            # Get all users
            users = env['res.users'].search([('active', '=', True)])
            manager_group = env.ref('student_request.group_student_request_manager')
            
            print("=== KIỂM TRA QUYỀN USER ===")
            print(f"Group: {manager_group.name} (ID: {manager_group.id})")
            print()
            
            users_with_permission = []
            users_without_permission = []
            
            for user in users:
                if manager_group in user.groups_id:
                    users_with_permission.append(user)
                else:
                    users_without_permission.append(user)
            
            print("✅ USERS CÓ QUYỀN DUYỆT:")
            if users_with_permission:
                for user in users_with_permission:
                    print(f"  - {user.name} (login: {user.login}, ID: {user.id})")
            else:
                print("  Không có user nào có quyền duyệt!")
            
            print()
            print("❌ USERS KHÔNG CÓ QUYỀN DUYỆT:")
            if users_without_permission:
                for user in users_without_permission[:10]:  # Chỉ hiển thị 10 user đầu
                    print(f"  - {user.name} (login: {user.login}, ID: {user.id})")
                if len(users_without_permission) > 10:
                    print(f"  ... và {len(users_without_permission) - 10} user khác")
            
            print()
            print("=== KẾT LUẬN ===")
            print(f"Tổng số user: {len(users)}")
            print(f"User có quyền duyệt: {len(users_with_permission)}")
            print(f"User không có quyền: {len(users_without_permission)}")
            
            if len(users_with_permission) == 0:
                print()
                print("⚠️  CẢNH BÁO: Không có user nào có quyền duyệt!")
                print("   Nút duyệt sẽ không hiển thị cho bất kỳ user nào.")
                print("   Chạy assign_admin_permissions.py để gán quyền cho admin.")
            
        except Exception as e:
            print(f'✗ Lỗi: {e}')

if __name__ == '__main__':
    check_user_permissions()