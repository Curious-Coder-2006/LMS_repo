# LMS — Library Management System

A Flask + SQLite application built from the assignment requirements:

## Minimum requirements
- Add and manage books and library members
- Allow members to borrow and return books
- Track book availability
- Prevent unavailable books from being borrowed
- Store borrowing history and relevant data in a database

## Bonus features included
- Book reservations / waitlists
- Overdue book tracking
- Authentication (login)
- Responsive, well-designed user interface

## Run locally

1. Install Python 3.10+.
2. Open a terminal in this `LMS` folder.
3. Create/activate a virtual environment (recommended):
   - Windows: `python -m venv .venv` then `.venv\Scripts\activate`
   - Linux/macOS: `python3 -m venv .venv` then `source .venv/bin/activate`
4. Install dependencies:
   `pip install -r requirements.txt`
5. Start:
   `python app.py`
6. Open:
   `http://127.0.0.1:5000`

## Demo login
Username: `admin`
Password: `admin123`

Change the default credentials and `SECRET_KEY` before deploying publicly.

The SQLite database is automatically created at `instance/lms.db` with a few sample books and members on the first run.
