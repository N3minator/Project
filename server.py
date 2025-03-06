import os
os.environ["TCL_LIBRARY"] = r"C:\Users\Виталик\AppData\Local\Programs\Python\Python313\tcl\tcl8.6"
os.environ["TK_LIBRARY"] = r"C:\Users\Виталик\AppData\Local\Programs\Python\Python313\tcl\tk8.6"

import socket
import threading
from datetime import datetime, timedelta
import pytz

from database import Session, engine, Base
from models import ChatMessage

# Create tables if they do not exist
Base.metadata.create_all(engine)

HOST = '127.0.0.1'
PORT = 9090

# Global dictionary: client socket -> username
clients = {}


def format_time(dt):
    utc = pytz.utc
    local_tz = pytz.timezone("Europe/Moscow")
    dt_utc = utc.localize(dt)
    dt_local = dt_utc.astimezone(local_tz)
    dt_local = dt_local - timedelta(hours=2)  # Subtract 2 hours
    return dt_local.strftime('%d-%m-%y %H:%M')


def broadcast(message, exclude_client=None):
    for client_socket in list(clients.keys()):
        if client_socket != exclude_client:
            try:
                client_socket.sendall((message + "\n").encode('utf-8'))
            except:
                pass


def broadcast_online_users():
    user_list = list(clients.values())
    n = len(user_list)
    msg = "ONLINE_USERS:" + str(n) + " " + " ".join(user_list)
    broadcast(msg)


def handle_client(client_socket):
    session_db = Session()
    try:
        # Receive username
        username = client_socket.recv(1024).decode('utf-8').strip()
        clients[client_socket] = username

        # Send chat history to the new client
        history = session_db.query(ChatMessage).order_by(ChatMessage.timestamp.asc()).all()
        history_lines = []
        for msg in history:
            t_str = format_time(msg.timestamp)
            line = f"[{t_str}] {msg.username}: {msg.message}"
            history_lines.append(line)
        history_text = "\n".join(history_lines) + "\n"
        client_socket.sendall(history_text.encode('utf-8'))

        # Create and broadcast a system message about the new user joining
        join_text = f'==> "{username}" joined the chat'
        join_msg = ChatMessage(username="System", message=join_text)
        session_db.add(join_msg)
        session_db.commit()

        t_str = format_time(join_msg.timestamp)
        broadcast_line = f"[{t_str}] System: {join_text}"
        broadcast(broadcast_line)
        broadcast_online_users()

        while True:
            data = client_socket.recv(1024)
            if not data:
                break

            message_text = data.decode('utf-8').strip()
            if not message_text:
                continue

            # Private message handling (command /pm)
            if message_text.startswith("/pm "):
                parts = message_text.split(" ", 2)
                if len(parts) < 3:
                    error_msg = "Error: Usage /pm <username> <message>"
                    client_socket.sendall((error_msg + "\n").encode('utf-8'))
                    continue
                target = parts[1]
                if target == username:
                    client_socket.sendall(("Error: You cannot send a private message to yourself.\n").encode('utf-8'))
                    continue
                private_text = parts[2]
                target_socket = None
                for sock, uname in clients.items():
                    if uname == target:
                        target_socket = sock
                        break
                if target_socket:
                    new_msg = ChatMessage(username=username, message=f"/pm {target} {private_text}")
                    session_db.add(new_msg)
                    session_db.commit()
                    t_str = format_time(new_msg.timestamp)
                    private_line = f'[{t_str}] (Private) "{username}" -> "{target}": {private_text}'
                    try:
                        target_socket.sendall((private_line + "\n").encode('utf-8'))
                    except:
                        pass
                    client_socket.sendall((private_line + "\n").encode('utf-8'))
                else:
                    client_socket.sendall((f'User "{target}" not found.\n').encode('utf-8'))
                continue

            # Regular message - save and broadcast
            new_msg = ChatMessage(username=username, message=message_text)
            session_db.add(new_msg)
            session_db.commit()

            t_str = format_time(new_msg.timestamp)
            broadcast_line = f"[{t_str}] {username}: {message_text}"
            broadcast(broadcast_line)

    except Exception as e:
        print("Error in handle_client:", e)
    finally:
        client_socket.close()
        if client_socket in clients:
            left_user = clients[client_socket]
            del clients[client_socket]

            left_text = f'==> "{left_user}" left the chat'
            left_msg = ChatMessage(username="System", message=left_text)
            session_db.add(left_msg)
            session_db.commit()

            t_str = format_time(left_msg.timestamp)
            broadcast_line = f"[{t_str}] System: {left_text}"
            broadcast(broadcast_line)
            broadcast_online_users()

        session_db.close()


def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Allows reusing the port even if it is in TIME_WAIT state
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen(5)
    print(f"Server started on {HOST}:{PORT}. Waiting for clients...")

    while True:
        client_socket, addr = server_socket.accept()
        print(f"New connection: {addr}")
        client_thread = threading.Thread(target=handle_client, args=(client_socket,))
        client_thread.start()


if __name__ == "__main__":
    main()
