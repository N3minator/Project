import colorlog
import logging
import socket
import threading
from datetime import datetime
from zoneinfo import ZoneInfo  # For Python 3.9+

# Configure colorlog for colored log output
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    "%(log_color)s%(asctime)s [%(levelname)s] %(message)s",
    datefmt='%Y-%m-%d %H:%M:%S',
    log_colors={
        'DEBUG': 'yellow',   # Debug actions
        'INFO': 'green',     # Success messages
        'WARNING': 'yellow', # Warnings / actions
        'ERROR': 'red',      # Errors
        'CRITICAL': 'red',
    }
))
logger = colorlog.getLogger(__name__)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

# Attempt to determine the user's local timezone.
try:
    from tzlocal import get_localzone
except ImportError:
    get_localzone = None

# Import modules for database and models
from database import Session, engine, Base
from models import ChatMessage, PrivateMessage

Base.metadata.create_all(engine)

HOST = '127.0.0.1'
PORT = 9090

# Dictionary: client_socket -> username
clients = {}


def format_time(dt, username=None):
    if dt is None:
        return "Unknown time"
    try:
        if get_localzone is not None:
            local_tz = get_localzone()
            dt_local = dt.astimezone(local_tz)
            if username:
                logger.info('User "%s" successfully obtained local time.', username)
        else:
            raise Exception("tzlocal not available")
    except Exception as e:
        if username:
            logger.error('Error - Local time not available for user "%s" (Switching to server time)', username)
        try:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            dt_local = dt.astimezone(ZoneInfo("Europe/Berlin"))
        except Exception as e2:
            if username:
                logger.error('Error retrieving server time for user "%s" (Switching to "Unknown time")', username)
            return "Unknown time"
    return dt_local.strftime('%d-%m-%y %H:%M')


def broadcast(message, exclude_client=None):
    # Sends the message to all connected clients.
    disconnected_sockets = []
    for client_socket in list(clients.keys()):
        if client_socket != exclude_client:
            try:
                client_socket.sendall((message + "\n").encode('utf-8'))
            except Exception as e:
                logger.error("Error sending message to client '%s': %s", clients.get(client_socket, "Unknown"), e)
                disconnected_sockets.append(client_socket)

    # Handle disconnected clients
    for sock in disconnected_sockets:
        if sock in clients:
            left_user = clients[sock]
            logger.info("Client '%s' disconnected unexpectedly.", left_user)
            del clients[sock]
            left_text = f"==> {left_user} (unexpectedly) left the chat"
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
    Sends a system message in the format:
    ONLINE_USERS:<number> user1 user2 ...
    """
    user_list = list(clients.values())
    n = len(user_list)
    msg = "ONLINE_USERS:" + str(n) + " " + " ".join(user_list)
    logger.debug("Broadcasting online users list: %s", msg)
    broadcast(msg)


def handle_client(client_socket):
    session_db = Session()
    try:
        # Read the username
        data = client_socket.recv(1024)
        if not data:
            logger.warning("Username not received (empty data). Closing connection.")
            client_socket.close()
            return

        username = data.decode('utf-8').strip()
        if not username:
            logger.warning("Username is empty. Closing connection.")
            client_socket.close()
            return

        clients[client_socket] = username
        logger.info("New client connected: '%s'", username)

        # Send the history of public messages
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

        # System message for joining
        join_text = f"==> {username} joined the chat"
        join_msg = ChatMessage(username="System", message=join_text)
        session_db.add(join_msg)
        session_db.commit()
        session_db.refresh(join_msg)

        t_str = format_time(join_msg.timestamp, username=username)
        broadcast_line = f"[{t_str}] System: {join_text}"
        broadcast(broadcast_line)
        broadcast_online_users()

        logger.info("User '%s' has entered the chat.", username)

        # Main loop for receiving messages
        while True:
            data = client_socket.recv(1024)
            if not data:
                logger.info("Client '%s' disconnected.", username)
                break

            message_text = data.decode('utf-8').strip()
            if not message_text:
                continue

            # Process /pm command for private messages
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
                        logger.error("Error saving private message '%s' -> '%s': %s", username, target, e, exc_info=True)
                        session_db.rollback()
                        client_socket.sendall("Error saving private message to the database.\n".encode('utf-8'))
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

            # Process public message
            try:
                new_msg = ChatMessage(username=username, message=message_text)
                session_db.add(new_msg)
                session_db.commit()
                session_db.refresh(new_msg)
            except Exception as e:
                logger.error("Error saving public message from '%s': %s", username, e, exc_info=True)
                session_db.rollback()
                client_socket.sendall("Error saving message to the database.\n".encode('utf-8'))
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

            left_text = f"==> {left_user} left the chat"
            left_msg = ChatMessage(username="System", message=left_text)
            try:
                session_db.add(left_msg)
                session_db.commit()
                session_db.refresh(left_msg)
            except Exception as e:
                logger.error("Error saving system exit message for '%s': %s", left_user, e, exc_info=True)
                session_db.rollback()

            t_str = format_time(left_msg.timestamp, username=left_user)
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
        logger.error("Error binding port %s: %s", PORT, e)
        return

    server_socket.listen(5)
    logger.info("Server started on %s:%s. Waiting for clients...", HOST, PORT)

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
