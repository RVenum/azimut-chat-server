from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text   # добавлен text
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'sqlite:///chat.db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ------------------- Модели -------------------
class ChatRoom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    user1 = db.Column(db.String(100), nullable=True)
    user2 = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(150), db.ForeignKey('chat_room.name'), nullable=False, index=True)
    username = db.Column(db.String(100), nullable=False)
    text = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(20), default='user')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'room': self.room,
            'username': self.username,
            'text': self.text,
            'type': self.type,
            'timestamp': int(self.timestamp.timestamp() * 1000)
        }

# ---------- Инициализация и авто-миграция ----------
with app.app_context():
    db.create_all()

    inspector = inspect(db.engine)
    if 'chat_room' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('chat_room')]
        if 'user1' not in columns:
            print("Обнаружена старая структура chat_room. Удаляю и пересоздаю...")
            # Выполняем через соединение
            with db.engine.connect() as conn:
                conn.execute(text('DROP TABLE IF EXISTS chat_room CASCADE'))
                conn.commit()
            db.create_all()
            print("chat_room пересоздана.")

    DEFAULT_ROOMS = [
        "Штаб", "Дежурная смена", "Альпинисты", "Медики", "ПСР",
        "Тренировки", "Водители", "Связисты", "Кинологи", "Водолазы",
        "Резерв", "Общий сбор", "Отдых", "Махачкала-центр", "Аэропорт"
    ]
    for room_name in DEFAULT_ROOMS:
        if not ChatRoom.query.filter_by(name=room_name).first():
            db.session.add(ChatRoom(name=room_name))
    db.session.commit()

# ------------------- События Socket.IO -------------------
@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')

@socketio.on('join')
def on_join(data):
    room = data.get('room', '')
    username = data.get('username', 'Гость')
    if not room:
        return

    join_room(room)
    history = Message.query.filter_by(room=room)\
        .order_by(Message.timestamp.asc()).limit(100).all()
    emit('history', {'messages': [msg.to_dict() for msg in history]})

    sys_msg = Message(room=room, username='Система',
                      text=f'{username} присоединился', type='system')
    db.session.add(sys_msg)
    db.session.commit()
    emit('message', sys_msg.to_dict(), room=room)

@socketio.on('leave')
def on_leave(data):
    room = data.get('room', '')
    username = data.get('username', 'Гость')
    if not room:
        return

    leave_room(room)
    sys_msg = Message(room=room, username='Система',
                      text=f'{username} покинул комнату', type='system')
    db.session.add(sys_msg)
    db.session.commit()
    emit('message', sys_msg.to_dict(), room=room)

@socketio.on('chat_message')
def handle_chat_message(data):
    room = data.get('room', '')
    username = data.get('username', 'Гость')
    text = data.get('text', '')
    if not room or not text:
        return

    msg = Message(room=room, username=username, text=text, type='user')
    db.session.add(msg)
    db.session.commit()
    emit('message', msg.to_dict(), room=room)

@socketio.on('create_private')
def handle_create_private(data):
    user1 = data.get('user1', '')
    user2 = data.get('user2', '')
    if not user1 or not user2:
        return

    users = sorted([user1, user2])
    room_name = f"private_{users[0]}_{users[1]}"

    existing = ChatRoom.query.filter_by(name=room_name).first()
    if existing:
        emit('private_created', {'room': room_name}, room=request.sid)
        return

    room = ChatRoom(name=room_name, user1=users[0], user2=users[1])
    db.session.add(room)
    db.session.commit()

    emit('private_created', {'room': room_name}, room=request.sid)
    socketio.emit('private_created', {'room': room_name})

@socketio.on('get_rooms')
def handle_get_rooms():
    rooms = [r.name for r in ChatRoom.query.order_by(ChatRoom.created_at).all()]
    emit('rooms_list', {'rooms': rooms})

@socketio.on('get_users')
def handle_get_users():
    users = [row[0] for row in db.session.query(Message.username).distinct().all()]
    users = [u for u in users if u != 'Система']
    emit('users_list', {'users': users})

# Запуск
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
