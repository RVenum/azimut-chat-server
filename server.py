import pymysql
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import time

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# --- Настройки подключения к MySQL ---
DB_HOST = 'localhost'
DB_USER = 'ваш_пользователь'
DB_PASS = 'ваш_пароль'
DB_NAME = 'ваша_база_данных'

def get_db():
    return pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME, charset='utf8mb4')

DEFAULT_ROOMS = [
    "Штаб", "Дежурная смена", "Альпинисты", "Медики", "ПСР",
    "Тренировки", "Водители", "Связисты", "Кинологи", "Водолазы",
    "Резерв", "Общий сбор", "Отдых", "Махачкала-центр", "Аэропорт"
]

@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')

@socketio.on('join')
def on_join(data):
    room = data.get('room', '')
    username = data.get('username', 'Гость')
    if room:
        join_room(room)
        # Отправляем последние 50 сообщений комнаты
        try:
            db = get_db()
            cur = db.cursor()
            cur.execute("SELECT username, message, timestamp FROM chat_messages WHERE room_name=%s ORDER BY timestamp DESC LIMIT 50", (room,))
            rows = cur.fetchall()
            history = []
            for u, msg, ts in reversed(list(rows)):
                history.append({
                    'type': 'user',
                    'username': u,
                    'text': msg,
                    'room': room,
                    'timestamp': ts
                })
            db.close()
            emit('history', {'messages': history}, room=request.sid)
        except Exception as e:
            print('Ошибка загрузки истории:', e)
        # Системное сообщение
        sys_msg = {
            'type': 'system',
            'text': f'{username} присоединился',
            'room': room,
            'timestamp': int(time.time() * 1000)
        }
        emit('message', sys_msg, room=room)

@socketio.on('leave')
def on_leave(data):
    room = data.get('room', '')
    username = data.get('username', 'Гость')
    if room:
        leave_room(room)
        sys_msg = {
            'type': 'system',
            'text': f'{username} покинул комнату',
            'room': room,
            'timestamp': int(time.time() * 1000)
        }
        emit('message', sys_msg, room=room)

@socketio.on('chat_message')
def handle_chat_message(data):
    room = data.get('room', '')
    username = data.get('username', 'Гость')
    text = data.get('text', '')
    if not room or not text:
        return
    ts = int(time.time() * 1000)
    msg = {
        'type': 'user',
        'username': username,
        'text': text,
        'room': room,
        'timestamp': ts
    }
    emit('message', msg, room=room)

    # Сохраняем в БД
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("INSERT INTO chat_messages (room_name, username, message, timestamp) VALUES (%s,%s,%s,%s)",
                    (room, username, text, ts))
        db.commit()
        db.close()
    except Exception as e:
        print('Ошибка сохранения сообщения:', e)

@socketio.on('create_private')
def handle_create_private(data):
    user1 = data.get('user1', '')
    user2 = data.get('user2', '')
    if user1 and user2:
        users = sorted([user1, user2])
        room_name = f"private_{users[0]}_{users[1]}"
        # Добавляем комнату в БД, если ещё нет
        try:
            db = get_db()
            cur = db.cursor()
            cur.execute("INSERT IGNORE INTO chat_rooms (name, type, created_by) VALUES (%s, 'private', %s)", (room_name, user1))
            db.commit()
            db.close()
        except Exception as e:
            print('Ошибка создания приватной комнаты:', e)
        emit('private_created', {'room': room_name}, room=request.sid)
        socketio.emit('private_created', {'room': room_name})

@socketio.on('get_rooms')
def handle_get_rooms():
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT name FROM chat_rooms ORDER BY created_at")
        rows = cur.fetchall()
        rooms = [r[0] for r in rows]
        db.close()
    except Exception:
        rooms = DEFAULT_ROOMS + []  # если БД недоступна, отдаём стандартный список
    emit('rooms_list', {'rooms': rooms})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000, debug=False, allow_unsafe_werkzeug=True)
