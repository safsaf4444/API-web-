import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# 1. Load your credentials
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌ Error: DATABASE_URL not found. check your .env file!")
else:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        print("📡 Connected to Database. Running final repair...")

        # A) Fix User Verification
        conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE'))
        
        # B) The "Safe" Status Sync
        # We cast reading_status to ::text so we can find the empty ones ('') 
        # without Postgres throwing a fit about Enum types.
        print("🛠️  Cleaning up reading_status values...")
        sync_sql = text("""
            UPDATE study 
            SET reading_status = 'unread' 
            WHERE reading_status IS NULL 
            OR reading_status::text = '' 
            OR reading_status::text = 'DONE'
        """)
        
        result = conn.execute(sync_sql)
        conn.commit()
        print(f"✅ Success! Fixed {result.rowcount} rows.")

print('Done')