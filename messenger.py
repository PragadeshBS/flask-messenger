import os
import json
import sqlite3
from flask import Flask, jsonify, make_response, redirect, render_template, request, session, url_for
import settings
from dotenv import load_dotenv
import requests
from datetime import datetime
import bcrypt

load_dotenv('.env')

app = Flask(__name__)
app.config.from_object(settings)
hugging_face_url = 'https://api-inference.huggingface.co/models/distilbert-base-uncased-finetuned-sst-2-english'
hugging_face_headers = {
    'Authorization': os.getenv('HUGGING_FACE_API'),
}


# Helper functions
def _get_message(id=None):
    """Return a list of message objects (as dicts)"""
    with sqlite3.connect(app.config['DATABASE']) as conn:
        c = conn.cursor()

        if id:
            id = int(id)  # Ensure that we have a valid id value to query
            q = "SELECT * FROM messages WHERE id=? ORDER BY dt DESC"
            rows = c.execute(q, (id, ))

        else:
            q = "SELECT * FROM messages ORDER BY dt DESC"
            rows = c.execute(q)

        return [{
            'id': r[0],
            'dt': r[1],
            'message': r[2],
            'sender': r[3]
        } for r in rows]


def _add_message(message, sender):
    with sqlite3.connect(app.config['DATABASE']) as conn:
        c = conn.cursor()
        q = "INSERT INTO messages VALUES (NULL, datetime('now'),?,?)"
        c.execute(q, (message, sender))
        conn.commit()
        return c.lastrowid


def _delete_message(ids):
    with sqlite3.connect(app.config['DATABASE']) as conn:
        c = conn.cursor()
        q = "DELETE FROM messages WHERE id=?"

        # Try/catch in case 'ids' isn't an iterable
        try:
            for i in ids:
                c.execute(q, (int(i), ))
        except TypeError:
            c.execute(q, (int(ids), ))

        conn.commit()


def _update_message(message, sender, ids):
    with sqlite3.connect(app.config['DATABASE']) as conn:
        c = conn.cursor()
        q = "UPDATE messages SET message=?, sender=? WHERE id=?"

        # Try/catch in case 'ids' isn't an iterable
        try:
            for i in ids:
                c.execute(q, (message, sender, int(i)))
        except TypeError:
            c.execute(q, (message, sender, int(ids)))

        conn.commit()


def _is_valid_user(username, password):
    with sqlite3.connect(app.config['DATABASE']) as conn:
        c = conn.cursor()
        q = "SELECT password FROM users WHERE username=?"
        c.execute(q, (username, ))
        password_in_db = c.fetchone()
        if password_in_db is None:
            return False
        if bcrypt.checkpw(password.encode('utf-8'), password_in_db[0]):
            return True
        return False


# Standard routing (server-side rendered pages)
@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        _add_message(request.form['message'], request.form['username'])
        redirect(url_for('home'))
    messages = _get_message()
    for i in range(len(messages)):
        # Input string
        date_string = messages[i]['dt']

        # Format string matching the input string
        format_string = '%Y-%m-%d %H:%M:%S'

        # Convert string to datetime object
        datetime_object = datetime.strptime(date_string, format_string)
        messages[i]['dt'] = datetime_object.strftime("%d %b %Y %I:%M %p")
    return render_template('index.html', messages=messages)


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if not 'logged_in' in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        # This little hack is needed for testing due to how Python dictionary keys work
        _delete_message([k[6:] for k in request.form.keys()])
        redirect(url_for('admin'))

    messages = _get_message()
    messages.reverse()

    # print([message['message'] for message in messages])
    data = [{'text': message['message']} for message in messages]
    # print(data)
    r = requests.post(url=hugging_face_url,
                      headers=hugging_face_headers,
                      data=json.dumps(data))
    res = json.loads(r.text)
    for i in range(len(messages)):
        messages[i]['sentiment'] = res[i][0]['label']
    return render_template('admin.html', messages=messages)


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form['username'] == app.config['USERNAME'] and request.form[
                'password'] == app.config['PASSWORD']:
            session['logged_in'] = True
            return redirect(url_for('admin'))
        elif _is_valid_user(request.form['username'],
                            request.form['password']):
            session['user'] = request.form['username']
            return redirect(url_for('home'))
        else:
            error = 'Enter a valid username and/or password'
    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        if _is_valid_user(request.form['username'], request.form['password']):
            error = 'Username already exists'
        else:
            with sqlite3.connect(app.config['DATABASE']) as conn:
                c = conn.cursor()
                salt = bcrypt.gensalt()
                hashed_password = bcrypt.hashpw(
                    request.form['password'].encode('utf-8'), salt)
                q = "INSERT INTO users VALUES (NULL, ?, ?)"
                c.execute(q, (request.form['username'], hashed_password))
                conn.commit()
            session['user'] = request.form['username']
            return redirect(url_for('home'))
    return render_template('register.html', error=error)


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('user', None)
    return redirect(url_for('home'))


# RESTful routing (serves JSON to provide an external API)
@app.route('/api/messages', methods=['GET'])
@app.route('/api/messages/<int:id>', methods=['GET'])
def get_message_by_id(id=None):
    messages = _get_message(id)
    if not messages:
        return make_response(jsonify({'error': 'Not found'}), 404)

    return jsonify({'messages': messages})


@app.route('/api/messages', methods=['POST'])
def create_message():
    if not request.json or not 'message' in request.json or not 'sender' in request.json:
        return make_response(jsonify({'error': 'Bad request'}), 400)

    id = _add_message(request.json['message'], request.json['sender'])

    return get_message_by_id(id), 201


@app.route('/api/messages/<int:id>', methods=['DELETE'])
def delete_message_by_id(id):
    _delete_message(id)
    return jsonify({'result': True})


@app.route('/api/messages/<int:id>', methods=['PUT'])
def update_message_by_id(id):
    if not request.json or not 'message' in request.json or not 'sender' in request.json:
        return make_response(jsonify({'error': 'Bad request'}), 400)
    _update_message(request.json['message'], request.json['sender'], id)
    return jsonify({'result': True})


@app.route('/api/sentiment/<string:id>', methods=['GET'])
@app.route('/api/sentiment')
def get_message_sentiment(id):
    message = _get_message(id)
    r = requests.post(url=hugging_face_url,
                      headers=hugging_face_headers,
                      data={'input': message[0]['message']})
    print(json.loads(r.text))
    return jsonify(json.loads(r.text)[0])


if __name__ == '__main__':

    # Test whether the database exists; if not, create it and create the table
    if not os.path.exists(app.config['DATABASE']):
        try:
            conn = sqlite3.connect(app.config['DATABASE'])
            c = conn.cursor()
            create_messages_table_cmd = """
                CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                dt TEXT NOT NULL,
                message TEXT NOT NULL,
                sender TEXT NOT NULL
                );
            """
            create_users_table_cmd = """
                CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                password TEXT NOT NULL
                );
            """
            c.execute(create_messages_table_cmd)
            c.execute(create_users_table_cmd)
            conn.commit()
            conn.close()
        except IOError:
            print("Couldn't initialize the database, exiting...")
            raise
        except sqlite3.OperationalError:
            print("Couldn't execute the SQL, exiting...")
            raise

    app.run(host='0.0.0.0')
