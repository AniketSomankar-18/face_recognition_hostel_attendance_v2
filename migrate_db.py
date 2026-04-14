import sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import text
from models import db, User, Student, Attendance, Leave, Penalty
from config import Config

# Load environment variables
load_dotenv()

def migrate():
    # Setup Flask app to use models and DB
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    # 1. Create tables in the new database (PostgreSQL/Supabase)
    print("Creating tables in Supabase...")
    with app.app_context():
        db.create_all()
        print("Tables created successfully.")

    # 2. Connect to the old SQLite database
    sqlite_db_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'database', 'hostel.db')
    if not os.path.exists(sqlite_db_path):
        print(f"Error: SQLite database not found at {sqlite_db_path}")
        return

    print(f"Connecting to SQLite: {sqlite_db_path}")
    sqlite_conn = sqlite3.connect(sqlite_db_path)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_curr = sqlite_conn.cursor()

    # Helper function to copy data
    def copy_table(table_name, model_class):
        print(f"Migrating table: {table_name}...")
        sqlite_curr.execute(f"SELECT * FROM {table_name}")
        rows = sqlite_curr.fetchall()
        
        with app.app_context():
            count = 0
            for row in rows:
                data = dict(row)
                
                # Existence check to prevent UniqueViolation
                if 'id' in data:
                    if db.session.get(model_class, data['id']):
                        continue
                elif table_name == 'users' and 'username' in data:
                    if model_class.query.filter_by(username=data['username']).first():
                        continue
                elif table_name == 'students' and 'registration_number' in data:
                    if model_class.query.filter_by(registration_number=data['registration_number']).first():
                        continue
                
                # Create model instance
                instance = model_class(**data)
                db.session.add(instance)
                count += 1
            
            db.session.commit()
            print(f"Migrated {count} records to {table_name}.")

    # Table migration order (dependencies first)
    try:
        copy_table('users', User)
        copy_table('students', Student)
        copy_table('attendance', Attendance)
        copy_table('leaves', Leave)
        copy_table('penalties', Penalty)
        
        # 3. Synchronize PostgreSQL sequences
        print("\nSynchronizing PostgreSQL sequences...")
        tables = [('users', 'id'), ('students', 'id'), ('attendance', 'id'), ('leaves', 'id'), ('penalties', 'id')]
        with app.app_context():
            for table_name, pk_col in tables:
                sql = text(f"SELECT setval(pg_get_serial_sequence('{table_name}', '{pk_col}'), COALESCE((SELECT MAX({pk_col}) FROM {table_name}), 1), true);")
                db.session.execute(sql)
            db.session.commit()
            
        print("\n✓ Migration completed successfully!")
    except Exception as e:
        print(f"\n✗ Migration failed: {str(e)}")
        with app.app_context():
            db.session.rollback()
    finally:
        sqlite_conn.close()

if __name__ == "__main__":
    migrate()
