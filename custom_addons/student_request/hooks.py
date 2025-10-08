def post_init_hook(env):
    """Hook được gọi sau khi module được install"""
    # Gán quyền manager cho admin user
    extension_model = env['request.extension']
    extension_model._setup_admin_permissions()