from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text, func
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

class UserRoomRead(db.Model):
    """Хранит время последнего прочитанного сообщения пользователем в комнате."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    room = db.Column(db.String(150), nullable=False)
    last_read = db.Column(db.DateTime, default=datetime.utcnow)

# ---------- Инициализация и авто-миграция ----------
with app.app_context():
    db.create_all()

    inspector = inspect(db.engine)
    # Автоматическое обновление структуры chat_room, если не хватает колонок
    if 'chat_room' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('chat_room')]
        if 'user1' not in columns:
            print("Обнаружена старая структура chat_room. Удаляю и пересоздаю...")
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

# ------------------- Вспомогательные функции -------------------
def get_unread_count(room, username):
    """Возвращает количество непрочитанных сообщений для пользователя в комнате."""
    last_read_record = UserRoomRead.query.filter_by(username=username, room=room).first()
    if last_read_record:
        return Message.query.filter(
            Message.room == room,
            Message.timestamp > last_read_record.last_read,
            Message.username != username  # не считаем свои сообщения
        ).count()
    else:
        # Если записи нет – все сообщения считаются непрочитанными
        return Message.query.filter(
            Message.room == room,
            Message.username != username
        ).count()

def get_last_message(room):
    """Возвращает последнее сообщение в комнате (или None)."""
    msg = Message.query.filter_by(room=room).order_by(Message.timestamp.desc()).first()
    return msg

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

    # Обновляем время последнего прочитанного до текущего
    now = datetime.utcnow()
    rec = UserRoomRead.query.filter_by(username=username, room=room).first()
    if rec:
        rec.last_read = now
    else:
        db.session.add(UserRoomRead(username=username, room=room, last_read=now))
    db.session.commit()

    # Отправляем историю
    history = Message.query.filter_by(room=room)\
        .order_by(Message.timestamp.asc()).limit(100).all()
    emit('history', {'messages': [msg.to_dict() for msg in history]})

    # Системное сообщение
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
def handle_get_rooms(data=None):
    # data может содержать { username: '...' } для персонализации непрочитанных
    username = data.get('username') if data else None
    all_rooms = ChatRoom.query.order_by(ChatRoom.created_at).all()
    rooms_info = []
    for r in all_rooms:
        last_msg = get_last_message(r.name)
        unread = get_unread_count(r.name, username) if username else 0
        rooms_info.append({
            'name': r.name,
            'lastMessage': last_msg.text if last_msg else '',
            'lastTime': last_msg.timestamp.isoformat() if last_msg else None,
            'unread': unread
        })
    emit('rooms_list', {'rooms': rooms_info})

@socketio.on('get_users')
def handle_get_users():
    users = [row[0] for row in db.session.query(Message.username).distinct().all()]
    users = [u for u in users if u != 'Система']
    emit('users_list', {'users': users})

# Запуск
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
