from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import time

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Предустановленные комнаты
DEFAULT_ROOMS = [
    "Штаб", "Дежурная смена", "Альпинисты", "Медики", "ПСР",
    "Тренировки", "Водители", "Связисты", "Кинологи", "Водолазы",
    "Резерв", "Общий сбор", "Отдых", "Махачкала-центр", "Аэропорт"
]

# Хранилище созданных приватных комнат (комнаты с префиксом 'private_')
private_rooms = set()

@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')

@socketio.on('join')
def on_join(data):
    room = data.get('room', '')
    username = data.get('username', 'Гость')
    if room:
        join_room(room)
        emit('message', {
            'type': 'system',
            'text': f'{username} присоединился',
            'room': room,
            'timestamp': int(time.time() * 1000)
        }, room=room)

@socketio.on('leave')
def on_leave(data):
    room = data.get('room', '')
    username = data.get('username', 'Гость')
    if room:
        leave_room(room)
        emit('message', {
            'type': 'system',
            'text': f'{username} покинул комнату',
            'room': room,
            'timestamp': int(time.time() * 1000)
        }, room=room)

@socketio.on('chat_message')
def handle_chat_message(data):
    room = data.get('room', '')
    username = data.get('username', 'Гость')
    text = data.get('text', '')
    if room and text:
        emit('message', {
            'type': 'user',
            'username': username,
            'text': text,
            'room': room,
            'timestamp': int(time.time() * 1000)
        }, room=room)

@socketio.on('create_private')
def handle_create_private(data):
    user1 = data.get('user1', '')
    user2 = data.get('user2', '')
    if user1 and user2:
        # Сортируем имена, чтобы комната была одинаковой с обеих сторон
        users = sorted([user1, user2])
        room_name = f"private_{users[0]}_{users[1]}"
        private_rooms.add(room_name)
        # Возвращаем обоим участникам название комнаты
        emit('private_created', {'room': room_name}, room=request.sid)
        # Уведомляем второго участника (если он в сети, но он может не быть подключен)
        # Для простоты отправим событие всем — клиент сам проверит.
        socketio.emit('private_created', {'room': room_name})

@socketio.on('get_rooms')
def handle_get_rooms():
    # Отдаём список общих комнат + приватные, в которых участвует пользователь
    # Пока возвращаем все предустановленные + известные приватные
    rooms = DEFAULT_ROOMS + list(private_rooms)
    emit('rooms_list', {'rooms': rooms})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000, debug=False, allow_unsafe_werkzeug=True)
