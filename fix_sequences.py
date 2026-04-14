import os
from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import text
from models import db
from config import Config

# Load environment variables
load_dotenv()

def reset_sequences():
    # Setup Flask app to use models and DB
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    # List of tables and their primary key columns
    tables = [
        ('users', 'id'),
        ('students', 'id'),
        ('attendance', 'id'),
        ('leaves', 'id'),
        ('penalties', 'id')
    ]

    print("Synchronizing PostgreSQL sequences...")
    
    with app.app_context():
        try:
            for table_name, pk_col in tables:
                print(f"  Resetting sequence for {table_name}...")
                
                # PostgreSQL command to set the sequence to the current max ID
                # pg_get_serial_sequence finds the sequence name for a given table and column
                sql = text(f"""
                    SELECT setval(
                        pg_get_serial_sequence('{table_name}', '{pk_col}'), 
                        COALESCE((SELECT MAX({pk_col}) FROM {table_name}), 1), 
                        true
                    );
                """)
                
                db.session.execute(sql)
            
            db.session.commit()
            print("\n✓ All sequences synchronized successfully!")
            print("You should now be able to add records without 'UniqueViolation' errors.")
            
        except Exception as e:
            print(f"\n✗ Failed to reset sequences: {str(e)}")
            db.session.rollback()

if __name__ == "__main__":
    reset_sequences()
