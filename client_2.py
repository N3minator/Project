import socket
import threading
import tkinter as tk
from tkinter import simpledialog, scrolledtext, filedialog
import winsound  # used for sound notifications (Windows only)
from datetime import datetime

HOST = '127.0.0.1'
PORT = 9090


class ChatClient:
    def __init__(self, master):
        self.master = master
        self.master.title("Chat Client")

        # Top panel: online label, export button, username label, and connection toggle button
        top_frame = tk.Frame(master)
        top_frame.pack(pady=5)

        self.online_label = tk.Label(top_frame, text="Current online: 0", fg="blue", cursor="hand2")
        self.online_label.pack(side=tk.LEFT, padx=(0, 10))
        self.online_label.bind("<Button-1>", self.show_online_users)

        self.export_button = tk.Button(top_frame, text="Export Chat", command=self.export_chat)
        self.export_button.pack(side=tk.LEFT, padx=10)

        self.user_label = tk.Label(top_frame, text="", fg="green")
        self.user_label.pack(side=tk.LEFT, padx=10)

        self.toggle_button = tk.Button(top_frame, text="Disconnect", command=self.toggle_connection)
        self.toggle_button.pack(side=tk.LEFT, padx=10)

        self.current_users = []
        self.history_loaded = False

        # Chat area
        self.text_area = scrolledtext.ScrolledText(master, state='disabled', wrap='word')
        self.text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        self.text_area.tag_config("system", foreground="blue", font=("Helvetica", 10, "italic"))
        self.text_area.tag_config("client", foreground="black", font=("Helvetica", 10))
        self.text_area.tag_config("private_sent", foreground="purple", font=("Helvetica", 10, "bold"))
        self.text_area.tag_config("private_received", foreground="orange", font=("Helvetica", 10, "bold"))
        self.text_area.tag_config("my_message", foreground="green", font=("Helvetica", 10, "bold"))

        # Message input field
        entry_frame = tk.Frame(master)
        entry_frame.pack(pady=5, fill=tk.X)

        self.entry_field = tk.Entry(entry_frame)
        self.entry_field.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.entry_field.bind("<Return>", self.send_message)

        self.send_button = tk.Button(entry_frame, text="Send", command=self.send_message)
        self.send_button.pack(side=tk.RIGHT, padx=5)

        # Prompt for username
        self.username = simpledialog.askstring("Username", "Enter your name:", parent=self.master)
        if not self.username:
            self.master.destroy()
            return
        self.user_label.config(text=f"Your nick: {self.username}")

        self.running = True
        # Flag to indicate that the connection is manually disabled
        self.connection_blocked = False

        # Connect to the server
        self.connect_to_server()

        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def connect_to_server(self):
        """Attempt to connect to the server if the connection is not manually blocked."""
        if self.connection_blocked:
            return

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            self.sock.connect((HOST, PORT))
        except Exception:
            if not self.connection_blocked:
                self.master.after(5000, self.connect_to_server)
            return

        try:
            local_offset_seconds = int(datetime.now().astimezone().utcoffset().total_seconds())
            self.sock.sendall(f"{self.username}|{local_offset_seconds}".encode('utf-8'))
        except Exception:
            self.display_message("Error sending username.", tag="system")
            self.master.after(5000, self.connect_to_server)
            return

        self.display_message("Connection to the server restored!", tag="system")

        # Clear chat before reloading chat history
        self.clear_chat()

        self.receive_thread = threading.Thread(target=self.receive_loop, daemon=True)
        self.receive_thread.start()

    def toggle_connection(self):
        # Toggles the connection state: disconnects when pressed, reconnects when pressed again.
        if not self.connection_blocked:
            self.connection_blocked = True
            try:
                self.sock.close()
            except Exception:
                pass
            self.display_message("Connection manually disconnected.", tag="system")
            self.toggle_button.config(text="Connect")
        else:
            self.connection_blocked = False
            self.display_message("Attempting to reconnect...", tag="system")
            self.toggle_button.config(text="Disconnect")
            self.connect_to_server()

    def export_chat(self):
        chat_text = self.text_area.get("1.0", tk.END)
        file_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(chat_text)
            except Exception:
                self.display_message("Error exporting chat.", tag="system")

    def play_notification_sound(self):
        try:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS)
        except Exception:
            pass

    def receive_loop(self):
        """
        Main loop for receiving data from the server.
        Collects history in a buffer until receiving the string HISTORY_END,
        then displays it all at once for immediate presentation.
        """
        buffer = ""
        collecting_history = True
        history_lines = []

        while self.running:
            try:
                data = self.sock.recv(1024)
                if not data:
                    self.display_message("Server disconnected.", tag="system")
                    break

                buffer += data.decode('utf-8')
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    if collecting_history:
                        if line == "HISTORY_END":
                            for hist_line in history_lines:
                                self.display_message(hist_line)
                            history_lines.clear()
                            collecting_history = False
                            self.history_loaded = True
                            continue
                        else:
                            history_lines.append(line)
                            continue

                    if line.startswith("ONLINE_USERS|"):
                        self.handle_online_users_message(line)
                    else:
                        if "(Private)" in line:
                            if f"(Private) {self.username} ->" in line:
                                self.display_message(line, tag="private_sent")
                            else:
                                self.display_message(line, tag="private_received")
                                if self.history_loaded:
                                    self.play_notification_sound()
                        else:
                            if "System:" in line:
                                self.display_message(line, tag="system")
                            else:
                                if f"] {self.username}:" in line:
                                    self.display_message(line, tag="my_message")
                                else:
                                    self.display_message(line, tag="client")
                                    if self.history_loaded and self.username not in line:
                                        self.play_notification_sound()

            except Exception:
                self.display_message("Error receiving data from the server.", tag="system")
                break

        self.sock.close()
        if self.running and not self.connection_blocked:
            self.display_message("Attempting to reconnect...", tag="system")
            self.master.after(5000, self.connect_to_server)

    def handle_online_users_message(self, message):
        # Processes the online users message.
        parts = message.split("|")
        if len(parts) < 2:
            return
        try:
            count = int(parts[1])
        except ValueError:
            count = 0
        users = parts[2:]
        self.online_label.config(text=f"Current online: {count}")
        self.current_users = users

    def display_message(self, message, tag="client"):
        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, message + "\n", tag)
        self.text_area.config(state='disabled')
        self.text_area.see(tk.END)

    def clear_chat(self):
        self.text_area.config(state='normal')
        self.text_area.delete("1.0", tk.END)
        self.text_area.config(state='disabled')

    def process_command(self, msg):
        if msg.startswith("/who"):
            self.display_message("Users: " + ", ".join(self.current_users), tag="system")
        elif msg.startswith("/clear"):
            self.clear_chat()
        elif msg.startswith("/help"):
            help_text = (
                "Available commands:\n"
                "/who - list users\n"
                "/clear - clear chat\n"
                "/pm <username> <message> - private message\n"
                "/help - help"
            )
            self.display_message(help_text, tag="system")
        elif msg.startswith("/pm"):
            parts = msg.split(" ", 2)
            if len(parts) < 3:
                self.display_message("Error: Usage /pm <username> <message>", tag="system")
            else:
                try:
                    self.sock.sendall(msg.encode('utf-8'))
                except Exception:
                    self.display_message("Error sending private message.", tag="system")
        else:
            self.display_message("Unknown command. Use /help", tag="system")

    def send_message(self, event=None):
        msg = self.entry_field.get().strip()
        if not msg:
            return
        if msg.startswith("/"):
            self.process_command(msg)
        else:
            try:
                self.sock.sendall(msg.encode('utf-8'))
            except Exception:
                self.display_message("Error sending message. The server may be unavailable.", tag="system")
        self.entry_field.delete(0, tk.END)

    def show_online_users(self, event=None):
        top = tk.Toplevel(self.master)
        top.title("Online Users List")
        listbox = tk.Listbox(top)
        listbox.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        for user in self.current_users:
            listbox.insert(tk.END, user)

    def on_closing(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
        self.master.destroy()


def main():
    root = tk.Tk()
    client = ChatClient(root)
    root.mainloop()


if __name__ == "__main__":
    main()
