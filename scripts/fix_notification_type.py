import configparser
import psycopg2

cfg_path = r"d:\motcua-quantri-odoo\odoo.cfg"
config = configparser.ConfigParser()
config.read(cfg_path)
opts = config["options"]

host = opts.get("db_host", "localhost")
port = int(opts.get("db_port", "5432"))
user = opts.get("db_user", "odoo")
password = opts.get("db_password", "odoo123")
dbname = opts.get("db_name", "odoo_db")

print(f"Connecting to DB {dbname} as {user}@{host}:{port}...")
conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=dbname)
conn.autocommit = True
cur = conn.cursor()

# Force email notification for share users to satisfy mail constraint
cur.execute("""
UPDATE res_users
SET notification_type = 'email'
WHERE share = TRUE AND (notification_type IS NULL OR notification_type <> 'email');
""")
print(f"Updated share users to notification_type=email")

# Ensure admin user specifically is compliant
cur.execute("""
UPDATE res_users
SET notification_type = 'email'
WHERE id IN (1,2) AND (notification_type IS NULL OR notification_type <> 'email');
""")
print("Ensured admin/public users have notification_type=email")

# Show a short summary
cur.execute("SELECT id, login, share, notification_type FROM res_users WHERE id IN (1,2)")
rows = cur.fetchall()
for r in rows:
    print("User:", r)

cur.close()
conn.close()
print("Done.")