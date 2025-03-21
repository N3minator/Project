import colorlog
import logging
import socket
import threading
from datetime import datetime, timedelta, timezone

# Configure colorlog for colored log output
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    "%(log_color)s%(asctime)s [%(levelname)s] %(message)s",
    datefmt='%Y-%m-%d %H:%M:%S',
    log_colors={
        'DEBUG': 'yellow',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red',
    }
))
logger = colorlog.getLogger(__name__)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

from database import Session, engine, Base
from models import ChatMessage, PrivateMessage

Base.metadata.create_all(engine)

HOST = '127.0.0.1'
PORT = 9090

# Dictionary: client_socket -> username
clients = {}

# Dictionary to store users' timezones (username -> offset in seconds)
user_timezones = {}


def format_offset(offset_seconds):
    hours = offset_seconds // 3600
    minutes = (abs(offset_seconds) % 3600) // 60
    sign = "+" if offset_seconds >= 0 else "-"
    return f"{sign}{abs(hours):02d}:{minutes:02d}"


def format_time(dt, username=None):
    if dt is None:
        return "Unknown time"
    try:
        dt_utc = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        if username and username in user_timezones and user_timezones[username] is not None:
            offset_seconds = user_timezones[username]
            logger.info("User %s UTC offset: %s", username, format_offset(offset_seconds))
            user_tz = timezone(timedelta(seconds=offset_seconds))
            dt_local = dt_utc.astimezone(user_tz)
            return dt_local.strftime("%Y-%m-%d %H:%M")
        else:
            return dt_utc.strftime("%Y-%m-%d %H:%M")
    except Exception as e:
        logger.error('Error obtaining time for user "%s": %s', username, e)
        return "Unknown time"


def broadcast(message, exclude_client=None):
    """
    Sends the message to all connected clients.
    If sending fails for a client, removes it from the list and notifies others.
    """
    disconnected_sockets = []
    for client_socket in list(clients.keys()):
        if client_socket != exclude_client:
            try:
                client_socket.sendall((message + "\n").encode('utf-8'))
            except Exception as e:
                logger.error("Error sending message to client '%s': %s", clients.get(client_socket, "Unknown"), e)
                disconnected_sockets.append(client_socket)

    # Process disconnected clients
    for sock in disconnected_sockets:
        if sock in clients:
            left_user = clients[sock]
            logger.info("Client '%s' disconnected unexpectedly.", left_user)
            del clients[sock]
            left_text = f'==> "{left_user}" disconnected unexpectedly'
            now = datetime.utcnow()
            broadcast_line = f"[{format_time(now, username=left_user)}] System: {left_text}"
            for cs in list(clients.keys()):
                try:
                    cs.sendall((broadcast_line + "\n").encode('utf-8'))
                except Exception as e:
                    logger.error("Error sending message to client '%s': %s", clients.get(cs, "Unknown"), e)
            broadcast_online_users()


def broadcast_online_users():
    """
    Sends a system message with the current number of connected users.
    Format: ONLINE_USERS|<number>|<nick1>|<nick2>|...
    """
    user_list = list(clients.values())
    n = len(user_list)
    msg = "ONLINE_USERS|" + str(n)
    for username in user_list:
        msg += "|" + username
    logger.debug("Broadcasting online users: %s", msg)
    broadcast(msg)


def handle_client(client_socket):
    session_db = Session()
    username = None
    try:
        # Read data for user identification (username and timezone offset)
        data = client_socket.recv(1024)
        if not data:
            logger.warning("No data received for user identification. Closing connection.")
            client_socket.close()
            return

        initial_message = data.decode('utf-8').strip()
        parts = initial_message.split("|")
        if len(parts) == 2:
            username = parts[0].strip()
            try:
                offset_seconds = int(parts[1].strip())
            except ValueError:
                offset_seconds = None
        else:
            username = initial_message
            offset_seconds = None

        if not username:
            logger.warning("Username is empty. Closing connection.")
            client_socket.close()
            return

        clients[client_socket] = username
        user_timezones[username] = offset_seconds

        logger.info("New client connected: '%s'", username)

        # Send public chat history
        history = session_db.query(ChatMessage).order_by(ChatMessage.timestamp.asc()).all()
        history_lines = []
        for msg in history:
            t_str = format_time(msg.timestamp)
            line = f"[{t_str}] {msg.username}: {msg.message}"
            history_lines.append(line)
        history_text = "\n".join(history_lines) + "\n"
        client_socket.sendall(history_text.encode('utf-8'))
        client_socket.sendall("HISTORY_END\n".encode('utf-8'))
        logger.debug("Chat history sent to client '%s'", username)

        # System message for joining, not saved in the database
        join_text = f'==> "{username}" joined the chat'
        now = datetime.utcnow()
        t_str = format_time(now, username=username)
        broadcast_line = f"[{t_str}] System: {join_text}"
        broadcast(broadcast_line)
        broadcast_online_users()

        logger.info("User '%s' joined the chat.", username)

        # Main loop to receive messages from the client
        while True:
            data = client_socket.recv(1024)
            if not data:
                logger.info("Client '%s' disconnected.", username)
                break

            message_text = data.decode('utf-8').strip()
            if not message_text:
                continue

            # Process private messages
            if message_text.startswith("/pm "):
                parts = message_text.split(" ", 2)
                if len(parts) < 3:
                    error_msg = "Error: Usage /pm <username> <message>"
                    client_socket.sendall((error_msg + "\n").encode('utf-8'))
                    continue
                target = parts[1]
                if target == username:
                    client_socket.sendall("Error: Cannot send a private message to yourself.\n".encode('utf-8'))
                    continue
                private_text = parts[2]

                target_socket = None
                for sock, uname in clients.items():
                    if uname == target:
                        target_socket = sock
                        break
                if target_socket:
                    try:
                        new_private = PrivateMessage(sender=username, receiver=target, message=private_text)
                        session_db.add(new_private)
                        session_db.commit()
                        session_db.refresh(new_private)
                    except Exception as e:
                        logger.error("Error saving private message from '%s' to '%s': %s", username, target, e, exc_info=True)
                        session_db.rollback()
                        client_socket.sendall("Error saving private message to DB.\n".encode('utf-8'))
                        continue

                    t_str = format_time(new_private.timestamp, username=username)
                    private_line = f"[{t_str}] (Private) {username} -> {target}: {private_text}"

                    try:
                        target_socket.sendall((private_line + "\n").encode('utf-8'))
                    except Exception as e:
                        logger.error("Error sending private message to '%s': %s", target, e)

                    client_socket.sendall((private_line + "\n").encode('utf-8'))
                    logger.debug("Private message from '%s' to '%s': %s", username, target, private_text)
                else:
                    client_socket.sendall((f"User {target} not found.\n").encode('utf-8'))
                continue

            # Process public messages (save to DB)
            try:
                new_msg = ChatMessage(username=username, message=message_text)
                session_db.add(new_msg)
                session_db.commit()
                session_db.refresh(new_msg)
            except Exception as e:
                logger.error("Error saving public message from '%s': %s", username, e, exc_info=True)
                session_db.rollback()
                client_socket.sendall("Error saving message to DB.\n".encode('utf-8'))
                continue

            t_str = format_time(new_msg.timestamp, username=username)
            broadcast_line = f"[{t_str}] {username}: {message_text}"
            broadcast(broadcast_line)
            logger.debug("Public message from '%s': %s", username, message_text)

    except Exception as e:
        logger.error("Error in handle_client (user='%s'): %s", clients.get(client_socket, "Unknown"), e, exc_info=True)
    finally:
        client_socket.close()
        if client_socket in clients:
            left_user = clients[client_socket]
            del clients[client_socket]
            if left_user in user_timezones:
                del user_timezones[left_user]

            # System message for disconnection, not saved in the DB
            left_text = f'==> "{left_user}" left the chat'
            now = datetime.utcnow()
            t_str = format_time(now, username=left_user)
            broadcast_line = f"[{t_str}] System: {left_text}"
            broadcast(broadcast_line)
            broadcast_online_users()

            logger.info("Client '%s' removed from list after disconnection.", left_user)

        session_db.close()


def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((HOST, PORT))
    except Exception as e:
        logger.error("Error binding to port %s: %s", PORT, e)
        return

    server_socket.listen(5)
    logger.info("Server running on %s:%s. Waiting for clients...", HOST, PORT)

    while True:
        try:
            client_socket, addr = server_socket.accept()
            logger.info("New connection: %s", addr)
            client_thread = threading.Thread(target=handle_client, args=(client_socket,))
            client_thread.start()
        except Exception as e:
            logger.error("Error accepting new connection: %s", e, exc_info=True)


if __name__ == "__main__":
    main()
