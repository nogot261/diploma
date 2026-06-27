import os
import sqlite3
from functools import wraps

from flask import Flask, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["DATABASE"] = os.environ.get("DATABASE_PATH", "knowledge_testing.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_one(sql, args=()):
    return get_db().execute(sql, args).fetchone()


def query_all(sql, args=()):
    return get_db().execute(sql, args).fetchall()


def execute(sql, args=()):
    db = get_db()
    db.execute(sql, args)
    db.commit()


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(**kwargs)

    return wrapped_view


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(**kwargs):
            if session.get("role") not in roles:
                return redirect(url_for("index"))
            return view(**kwargs)

        return wrapped_view

    return decorator


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            login TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            department_id INTEGER,
            FOREIGN KEY (department_id) REFERENCES departments(id)
        );

        CREATE TABLE IF NOT EXISTS tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            pass_score INTEGER NOT NULL DEFAULT 70,
            created_by INTEGER NOT NULL,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            FOREIGN KEY (test_id) REFERENCES tests(id)
        );

        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            is_correct INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (question_id) REFERENCES questions(id)
        );

        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Назначен',
            score INTEGER,
            finished_at TEXT,
            FOREIGN KEY (test_id) REFERENCES tests(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """
    )
    db.commit()

    if query_one("SELECT id FROM users LIMIT 1"):
        return

    execute("INSERT INTO departments (name) VALUES (?)", ("Отдел продаж",))
    execute("INSERT INTO departments (name) VALUES (?)", ("Отдел кадров",))

    users = [
        ("Администратор", "admin", "admin123", "admin", 2),
        ("Специалист отдела кадров", "hr", "hr123", "hr", 2),
        ("Иванов Иван Иванович", "ivanov", "12345", "employee", 1),
        ("Петрова Анна Сергеевна", "petrova", "12345", "employee", 1),
    ]
    for full_name, login, password, role, department_id in users:
        execute(
            """
            INSERT INTO users (full_name, login, password_hash, role, department_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (full_name, login, generate_password_hash(password), role, department_id),
        )

    execute(
        """
        INSERT INTO tests (title, description, pass_score, created_by)
        VALUES (?, ?, ?, ?)
        """,
        (
            "Проверка знаний по информационной безопасности",
            "Короткий тест для сотрудников после инструктажа.",
            70,
            2,
        ),
    )
    test_id = query_one("SELECT id FROM tests WHERE title = ?", ("Проверка знаний по информационной безопасности",))["id"]

    demo_questions = [
        (
            "Что нужно сделать при получении подозрительного письма?",
            ["Открыть вложение", "Переслать письмо специалисту по ИБ", "Ответить отправителю"],
            1,
        ),
        (
            "Какой пароль считается более надежным?",
            ["12345678", "qwerty", "Сложный пароль из букв, цифр и символов"],
            2,
        ),
        (
            "Можно ли передавать свой пароль коллегам?",
            ["Да", "Нет", "Можно только руководителю"],
            1,
        ),
    ]
    for question_text, answers, correct_index in demo_questions:
        execute("INSERT INTO questions (test_id, text) VALUES (?, ?)", (test_id, question_text))
        question_id = query_one("SELECT last_insert_rowid() AS id")["id"]
        for index, answer_text in enumerate(answers):
            execute(
                "INSERT INTO answers (question_id, text, is_correct) VALUES (?, ?, ?)",
                (question_id, answer_text, 1 if index == correct_index else 0),
            )

    execute("INSERT INTO assignments (test_id, user_id) VALUES (?, ?)", (test_id, 3))
    execute("INSERT INTO assignments (test_id, user_id) VALUES (?, ?)", (test_id, 4))


@app.before_request
def before_request():
    init_db()


@app.route("/")
@login_required
def index():
    if session["role"] in ("admin", "hr"):
        tests = query_all("SELECT * FROM tests ORDER BY id DESC")
        return render_template("manager.html", tests=tests)

    assignments = query_all(
        """
        SELECT a.*, t.title, t.description, t.pass_score
        FROM assignments a
        JOIN tests t ON t.id = a.test_id
        WHERE a.user_id = ?
        ORDER BY a.id DESC
        """,
        (session["user_id"],),
    )
    return render_template("employee.html", assignments=assignments)


@app.route("/login", methods=("GET", "POST"))
def login():
    error = None
    if request.method == "POST":
        user = query_one("SELECT * FROM users WHERE login = ?", (request.form["login"],))
        if user and check_password_hash(user["password_hash"], request.form["password"]):
            session.clear()
            session["user_id"] = user["id"]
            session["full_name"] = user["full_name"]
            session["role"] = user["role"]
            return redirect(url_for("index"))
        error = "Неверный логин или пароль"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/tests/new", methods=("GET", "POST"))
@login_required
@role_required("admin", "hr")
def create_test():
    if request.method == "POST":
        execute(
            """
            INSERT INTO tests (title, description, pass_score, created_by)
            VALUES (?, ?, ?, ?)
            """,
            (
                request.form["title"],
                request.form["description"],
                int(request.form["pass_score"]),
                session["user_id"],
            ),
        )
        return redirect(url_for("index"))
    return render_template("test_form.html")


@app.route("/tests/<int:test_id>/questions", methods=("GET", "POST"))
@login_required
@role_required("admin", "hr")
def questions(test_id):
    test = query_one("SELECT * FROM tests WHERE id = ?", (test_id,))
    if request.method == "POST":
        execute("INSERT INTO questions (test_id, text) VALUES (?, ?)", (test_id, request.form["text"]))
        question_id = query_one("SELECT last_insert_rowid() AS id")["id"]
        correct_answer = int(request.form["correct_answer"])
        for index in range(1, 4):
            execute(
                "INSERT INTO answers (question_id, text, is_correct) VALUES (?, ?, ?)",
                (question_id, request.form[f"answer_{index}"], 1 if index == correct_answer else 0),
            )
        return redirect(url_for("questions", test_id=test_id))

    question_rows = query_all("SELECT * FROM questions WHERE test_id = ?", (test_id,))
    return render_template("questions.html", test=test, questions=question_rows)


@app.route("/tests/<int:test_id>/assign", methods=("GET", "POST"))
@login_required
@role_required("admin", "hr")
def assign_test(test_id):
    test = query_one("SELECT * FROM tests WHERE id = ?", (test_id,))
    employees = query_all("SELECT * FROM users WHERE role = 'employee' ORDER BY full_name")
    if request.method == "POST":
        user_id = int(request.form["user_id"])
        exists = query_one(
            "SELECT id FROM assignments WHERE test_id = ? AND user_id = ?",
            (test_id, user_id),
        )
        if not exists:
            execute("INSERT INTO assignments (test_id, user_id) VALUES (?, ?)", (test_id, user_id))
        return redirect(url_for("reports"))
    return render_template("assign.html", test=test, employees=employees)


@app.route("/assignments/<int:assignment_id>/take", methods=("GET", "POST"))
@login_required
def take_test(assignment_id):
    assignment = query_one(
        """
        SELECT a.*, t.title, t.description, t.pass_score
        FROM assignments a
        JOIN tests t ON t.id = a.test_id
        WHERE a.id = ? AND a.user_id = ?
        """,
        (assignment_id, session["user_id"]),
    )
    if not assignment or assignment["status"] == "Завершен":
        return redirect(url_for("index"))

    questions = query_all("SELECT * FROM questions WHERE test_id = ?", (assignment["test_id"],))
    question_data = []
    for question in questions:
        answers = query_all("SELECT * FROM answers WHERE question_id = ?", (question["id"],))
        question_data.append({"question": question, "answers": answers})

    if request.method == "POST":
        total = len(question_data)
        correct = 0
        for item in question_data:
            answer_id = request.form.get(f"question_{item['question']['id']}")
            if answer_id:
                answer = query_one("SELECT is_correct FROM answers WHERE id = ?", (answer_id,))
                if answer and answer["is_correct"]:
                    correct += 1
        score = round(correct / total * 100) if total else 0
        status = "Завершен"
        execute(
            """
            UPDATE assignments
            SET status = ?, score = ?, finished_at = datetime('now')
            WHERE id = ?
            """,
            (status, score, assignment_id),
        )
        return redirect(url_for("index"))

    return render_template("take_test.html", assignment=assignment, question_data=question_data)


@app.route("/reports")
@login_required
@role_required("admin", "hr")
def reports():
    rows = query_all(
        """
        SELECT a.*, u.full_name, d.name AS department_name, t.title, t.pass_score
        FROM assignments a
        JOIN users u ON u.id = a.user_id
        LEFT JOIN departments d ON d.id = u.department_id
        JOIN tests t ON t.id = a.test_id
        ORDER BY a.id DESC
        """
    )
    return render_template("reports.html", rows=rows)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
