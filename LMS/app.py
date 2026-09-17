from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
import sqlite3

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "instance" / "lms.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-secret-key"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        isbn TEXT UNIQUE,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        category TEXT DEFAULT '',
        total_copies INTEGER NOT NULL DEFAULT 1 CHECK(total_copies > 0),
        available_copies INTEGER NOT NULL DEFAULT 1 CHECK(available_copies >= 0)
    );

    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        email TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        joined_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS loans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        book_id INTEGER NOT NULL,
        member_id INTEGER NOT NULL,
        borrowed_at TEXT NOT NULL,
        due_at TEXT NOT NULL,
        returned_at TEXT,
        FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE RESTRICT,
        FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE RESTRICT
    );

    CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        book_id INTEGER NOT NULL,
        member_id INTEGER NOT NULL,
        reserved_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'waiting',
        FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE,
        FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE
    );
    """)
    user = conn.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if not user:
        conn.execute(
            "INSERT INTO users(username, password_hash) VALUES (?, ?)",
            ("admin", generate_password_hash("admin123"))
        )

    # Seed sample data once.
    if conn.execute("SELECT COUNT(*) AS c FROM books").fetchone()["c"] == 0:
        conn.executemany("""
            INSERT INTO books(isbn, title, author, category, total_copies, available_copies)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [
            ("9780135957059", "The Pragmatic Programmer", "David Thomas & Andrew Hunt", "Programming", 3, 3),
            ("9780132350884", "Clean Code", "Robert C. Martin", "Programming", 2, 2),
            ("9780262046305", "Introduction to Algorithms", "Thomas H. Cormen et al.", "Algorithms", 2, 2),
        ])
    if conn.execute("SELECT COUNT(*) AS c FROM members").fetchone()["c"] == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.executemany("""
            INSERT INTO members(member_code, name, email, phone, joined_at)
            VALUES (?, ?, ?, ?, ?)
        """, [
            ("LMS001", "Aarav Sharma", "aarav@example.com", "9876543210", now),
            ("LMS002", "Priya Verma", "priya@example.com", "9876501234", now),
        ])
    conn.commit()
    conn.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.template_filter("datefmt")
def datefmt(value):
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%d %b %Y, %I:%M %p")
    except ValueError:
        return value


@app.context_processor
def inject_globals():
    return {"current_year": datetime.now().year}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def dashboard():
    conn = get_db()
    stats = {
        "books": conn.execute("SELECT COUNT(*) c FROM books").fetchone()["c"],
        "members": conn.execute("SELECT COUNT(*) c FROM members").fetchone()["c"],
        "borrowed": conn.execute("SELECT COUNT(*) c FROM loans WHERE returned_at IS NULL").fetchone()["c"],
        "overdue": conn.execute(
            "SELECT COUNT(*) c FROM loans WHERE returned_at IS NULL AND due_at < ?",
            (datetime.now().isoformat(sep=" "),)
        ).fetchone()["c"],
        "waiting": conn.execute("SELECT COUNT(*) c FROM reservations WHERE status = 'waiting'").fetchone()["c"],
    }
    recent = conn.execute("""
        SELECT loans.*, books.title, members.name, members.member_code
        FROM loans
        JOIN books ON books.id = loans.book_id
        JOIN members ON members.id = loans.member_id
        ORDER BY loans.borrowed_at DESC
        LIMIT 8
    """).fetchall()
    conn.close()
    return render_template("dashboard.html", stats=stats, recent=recent)


@app.route("/books", methods=["GET", "POST"])
@login_required
def books():
    conn = get_db()
    if request.method == "POST":
        try:
            isbn = request.form.get("isbn", "").strip() or None
            title = request.form.get("title", "").strip()
            author = request.form.get("author", "").strip()
            category = request.form.get("category", "").strip()
            copies = int(request.form.get("copies", "1"))
            if not title or not author or copies < 1:
                raise ValueError
            conn.execute("""
                INSERT INTO books(isbn, title, author, category, total_copies, available_copies)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (isbn, title, author, category, copies, copies))
            conn.commit()
            flash("Book added successfully.", "success")
        except (ValueError, sqlite3.IntegrityError):
            conn.rollback()
            flash("Could not add the book. Check the fields and make sure ISBN is unique.", "error")
        finally:
            conn.close()
        return redirect(url_for("books"))

    q = request.args.get("q", "").strip()
    if q:
        rows = conn.execute("""
            SELECT * FROM books
            WHERE title LIKE ? OR author LIKE ? OR isbn LIKE ? OR category LIKE ?
            ORDER BY title
        """, tuple(f"%{q}%" for _ in range(4))).fetchall()
    else:
        rows = conn.execute("SELECT * FROM books ORDER BY title").fetchall()
    conn.close()
    return render_template("books.html", books=rows, q=q)


@app.post("/books/<int:book_id>/delete")
@login_required
def delete_book(book_id):
    conn = get_db()
    active = conn.execute(
        "SELECT COUNT(*) c FROM loans WHERE book_id = ? AND returned_at IS NULL", (book_id,)
    ).fetchone()["c"]
    if active:
        flash("This book cannot be deleted while copies are borrowed.", "error")
    else:
        try:
            conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
            conn.commit()
            flash("Book deleted.", "success")
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("This book has history or reservations and cannot be deleted.", "error")
    conn.close()
    return redirect(url_for("books"))


@app.route("/members", methods=["GET", "POST"])
@login_required
def members():
    conn = get_db()
    if request.method == "POST":
        code = request.form.get("member_code", "").strip()
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        if not code or not name:
            flash("Member code and name are required.", "error")
        else:
            try:
                conn.execute("""
                    INSERT INTO members(member_code, name, email, phone, joined_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (code, name, email, phone, datetime.now().isoformat(sep=" ")))
                conn.commit()
                flash("Member added successfully.", "success")
            except sqlite3.IntegrityError:
                conn.rollback()
                flash("Member code must be unique.", "error")
        conn.close()
        return redirect(url_for("members"))

    q = request.args.get("q", "").strip()
    if q:
        rows = conn.execute("""
            SELECT * FROM members
            WHERE member_code LIKE ? OR name LIKE ? OR email LIKE ? OR phone LIKE ?
            ORDER BY name
        """, tuple(f"%{q}%" for _ in range(4))).fetchall()
    else:
        rows = conn.execute("SELECT * FROM members ORDER BY name").fetchall()
    conn.close()
    return render_template("members.html", members=rows, q=q)


@app.post("/members/<int:member_id>/delete")
@login_required
def delete_member(member_id):
    conn = get_db()
    active = conn.execute(
        "SELECT COUNT(*) c FROM loans WHERE member_id = ? AND returned_at IS NULL", (member_id,)
    ).fetchone()["c"]
    if active:
        flash("Member cannot be deleted while they have borrowed books.", "error")
    else:
        try:
            conn.execute("DELETE FROM members WHERE id = ?", (member_id,))
            conn.commit()
            flash("Member deleted.", "success")
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("This member has borrowing history and cannot be deleted.", "error")
    conn.close()
    return redirect(url_for("members"))


@app.route("/borrow", methods=["GET", "POST"])
@login_required
def borrow():
    conn = get_db()
    if request.method == "POST":
        book_id = request.form.get("book_id")
        member_id = request.form.get("member_id")
        if not book_id or not member_id:
            flash("Select both a book and a member.", "error")
        else:
            book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
            member = conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
            if not book or not member:
                flash("Invalid book or member.", "error")
            elif book["available_copies"] <= 0:
                flash("This book is currently unavailable. Use Reservations to join its waitlist.", "error")
            else:
                borrowed_at = datetime.now()
                due_at = borrowed_at + timedelta(days=14)
                conn.execute("""
                    INSERT INTO loans(book_id, member_id, borrowed_at, due_at)
                    VALUES (?, ?, ?, ?)
                """, (book_id, member_id, borrowed_at.isoformat(sep=" "), due_at.isoformat(sep=" ")))
                conn.execute(
                    "UPDATE books SET available_copies = available_copies - 1 WHERE id = ?", (book_id,)
                )
                conn.commit()
                flash(f'"{book["title"]}" borrowed by {member["name"]}. Due in 14 days.', "success")
        conn.close()
        return redirect(url_for("borrow"))

    book_rows = conn.execute("SELECT * FROM books ORDER BY title").fetchall()
    member_rows = conn.execute("SELECT * FROM members ORDER BY name").fetchall()
    conn.close()
    return render_template("borrow.html", books=book_rows, members=member_rows)


@app.get("/returns")
@login_required
def returns():
    conn = get_db()
    q = request.args.get("q", "").strip()
    sql = """
        SELECT loans.*, books.title, books.author, members.name, members.member_code
        FROM loans
        JOIN books ON books.id = loans.book_id
        JOIN members ON members.id = loans.member_id
        WHERE loans.returned_at IS NULL
    """
    params = []
    if q:
        sql += " AND (books.title LIKE ? OR members.name LIKE ? OR members.member_code LIKE ?)"
        params.extend([f"%{q}%"] * 3)
    sql += " ORDER BY loans.due_at"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return render_template("returns.html", loans=rows, q=q)


@app.post("/returns/<int:loan_id>")
@login_required
def return_book(loan_id):
    conn = get_db()
    loan = conn.execute("SELECT * FROM loans WHERE id = ? AND returned_at IS NULL", (loan_id,)).fetchone()
    if not loan:
        flash("Borrowing record not found or already returned.", "error")
        conn.close()
        return redirect(url_for("returns"))

    now = datetime.now().isoformat(sep=" ")
    conn.execute("UPDATE loans SET returned_at = ? WHERE id = ?", (now, loan_id))
    conn.execute("UPDATE books SET available_copies = available_copies + 1 WHERE id = ?", (loan["book_id"],))

    next_res = conn.execute("""
        SELECT id FROM reservations
        WHERE book_id = ? AND status = 'waiting'
        ORDER BY reserved_at
        LIMIT 1
    """, (loan["book_id"],)).fetchone()
    if next_res:
        conn.execute("UPDATE reservations SET status = 'ready' WHERE id = ?", (next_res["id"],))

    conn.commit()
    conn.close()
    flash("Book returned successfully.", "success")
    return redirect(url_for("returns"))


@app.route("/reservations", methods=["GET", "POST"])
@login_required
def reservations():
    conn = get_db()
    if request.method == "POST":
        book_id = request.form.get("book_id")
        member_id = request.form.get("member_id")
        book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        member = conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
        existing = conn.execute("""
            SELECT id FROM reservations
            WHERE book_id = ? AND member_id = ? AND status IN ('waiting', 'ready')
        """, (book_id, member_id)).fetchone()
        if not book or not member:
            flash("Invalid book or member.", "error")
        elif book["available_copies"] > 0:
            flash("Book is available already; it can be borrowed directly.", "error")
        elif existing:
            flash("That member is already on the waitlist.", "error")
        else:
            conn.execute("""
                INSERT INTO reservations(book_id, member_id, reserved_at, status)
                VALUES (?, ?, ?, 'waiting')
            """, (book_id, member_id, datetime.now().isoformat(sep=" ")))
            conn.commit()
            flash("Reservation added to the waitlist.", "success")
        conn.close()
        return redirect(url_for("reservations"))

    rows = conn.execute("""
        SELECT reservations.*, books.title, members.name, members.member_code
        FROM reservations
        JOIN books ON books.id = reservations.book_id
        JOIN members ON members.id = reservations.member_id
        ORDER BY CASE status WHEN 'ready' THEN 0 ELSE 1 END, reserved_at
    """).fetchall()
    available_books = conn.execute("SELECT * FROM books ORDER BY title").fetchall()
    member_rows = conn.execute("SELECT * FROM members ORDER BY name").fetchall()
    conn.close()
    return render_template("reservations.html", reservations=rows, books=available_books, members=member_rows)


@app.post("/reservations/<int:reservation_id>/cancel")
@login_required
def cancel_reservation(reservation_id):
    conn = get_db()
    conn.execute(
        "UPDATE reservations SET status = 'cancelled' WHERE id = ? AND status IN ('waiting','ready')",
        (reservation_id,)
    )
    conn.commit()
    conn.close()
    flash("Reservation cancelled.", "success")
    return redirect(url_for("reservations"))


@app.get("/history")
@login_required
def history():
    conn = get_db()
    rows = conn.execute("""
        SELECT loans.*, books.title, books.author, members.name, members.member_code
        FROM loans
        JOIN books ON books.id = loans.book_id
        JOIN members ON members.id = loans.member_id
        ORDER BY loans.borrowed_at DESC
    """).fetchall()
    conn.close()
    return render_template("history.html", loans=rows)


@app.get("/api/stats")
@login_required
def api_stats():
    conn = get_db()
    data = {
        "books": conn.execute("SELECT COUNT(*) c FROM books").fetchone()["c"],
        "members": conn.execute("SELECT COUNT(*) c FROM members").fetchone()["c"],
        "borrowed": conn.execute("SELECT COUNT(*) c FROM loans WHERE returned_at IS NULL").fetchone()["c"],
        "overdue": conn.execute(
            "SELECT COUNT(*) c FROM loans WHERE returned_at IS NULL AND due_at < ?",
            (datetime.now().isoformat(sep=" "),)
        ).fetchone()["c"],
        "waiting": conn.execute("SELECT COUNT(*) c FROM reservations WHERE status='waiting'").fetchone()["c"]
    }
    conn.close()
    return jsonify(data)


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=True)
