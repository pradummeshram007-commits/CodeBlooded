import os
from dotenv import load_dotenv
import psycopg
from supabase import create_client

load_dotenv()

# 1. Database
with psycopg.connect(os.environ["SUPABASE_DB_URL"], connect_timeout=10) as conn:
    print("DB OK:", conn.execute("select version()").fetchone()[0][:40])

# 2. Storage
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
print("Storage OK, buckets:", [b.name for b in sb.storage.list_buckets()])