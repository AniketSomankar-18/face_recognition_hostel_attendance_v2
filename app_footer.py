# ─── Database Init ────────────────────────────────────────────────────────────
def init_database():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='warden').first():
            warden = User(username='warden', role='warden', hostel_code='N')
            warden.set_password('warden123')
            db.session.add(warden)
            db.session.commit()
            print("[INFO] Default warden created.")

# Run init on startup for Gunicorn compatibility
init_database()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
