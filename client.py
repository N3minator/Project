import socket
import threading
import tkinter as tk
from tkinter import simpledialog, scrolledtext, filedialog
import winsound  # used for sound notifications (Windows only)

HOST = '127.0.0.1'
PORT = 9090


class ChatClient:
    def __init__(self, master):
        self.master = master
        self.master.title("Chat Client")

        # Top panel: online label, export button, and username label
        top_frame = tk.Frame(master)
        top_frame.pack(pady=5)

        self.online_label = tk.Label(top_frame, text="Currently online: 0", fg="blue", cursor="hand2")
        self.online_label.pack(side=tk.LEFT, padx=(0, 10))
        self.online_label.bind("<Button-1>", self.show_online_users)

        self.export_button = tk.Button(top_frame, text="Export Chat", command=self.export_chat)
        self.export_button.pack(side=tk.LEFT, padx=10)

        # Label with the user's nickname
        self.user_label = tk.Label(top_frame, text="", fg="green")

        # Local list of online users
        self.current_users = []
        self.history_loaded = False

        # Main chat area with scrolling
        self.text_area = scrolledtext.ScrolledText(master, state='disabled', wrap='word')
        self.text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        # Tags for formatting:
        # "system" for system messages,
        # "client" for regular messages,
        # "private_sent" for private messages sent by the user,
        # "private_received" for private messages received from others,
        # "my_message" for regular public messages (to easily identify own messages)
        self.text_area.tag_config("system", foreground="blue", font=("Helvetica", 10, "italic"))
        self.text_area.tag_config("client", foreground="black", font=("Helvetica", 10))
        self.text_area.tag_config("private_sent", foreground="purple", font=("Helvetica", 10, "bold"))
        self.text_area.tag_config("private_received", foreground="orange", font=("Helvetica", 10, "bold"))
        self.text_area.tag_config("my_message", foreground="green", font=("Helvetica", 10, "bold"))

        # Message input panel
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
        # Set the nickname label
        self.user_label.config(text=f"Your nickname: {self.username}")
        self.user_label.pack(side=tk.LEFT, padx=10)

        # Connect to the server
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((HOST, PORT))
        except Exception as e:
            self.display_message("Error connecting to server.", tag="system")
            self.master.after(3000, self.master.destroy)
            return

        self.running = True

        try:
            self.sock.sendall(self.username.encode('utf-8'))
        except Exception as e:
            self.display_message("Error sending username.", tag="system")
            self.master.after(3000, self.master.destroy)
            return

        self.receive_thread = threading.Thread(target=self.receive_loop, daemon=True)
        self.receive_thread.start()

        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def export_chat(self):
        chat_text = self.text_area.get("1.0", tk.END)
        file_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(chat_text)
            except Exception as e:
                self.display_message("Error exporting chat.", tag="system")

    def play_notification_sound(self):
        try:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS)
        except Exception as e:
            pass

    def receive_loop(self):
        buffer = ""
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

                    if line == "HISTORY_END":
                        self.history_loaded = True
                        continue

                    if line.startswith("ONLINE_USERS:"):
                        self.handle_online_users_message(line)
                    else:
                        # If the line contains "(Private)", process separately
                        if "(Private)" in line:
                            if f"(Private) {self.username} ->" in line:
                                self.display_message(line, tag="private_sent")
                            else:
                                self.display_message(line, tag="private_received")
                                if self.history_loaded:
                                    self.play_notification_sound()
                        else:
                            # If the message is a system message
                            if "System:" in line:
                                self.display_message(line, tag="system")
                            else:
                                # If it's a public message, determine if it was sent by the user
                                if f"] {self.username}:" in line:
                                    self.display_message(line, tag="my_message")
                                else:
                                    self.display_message(line, tag="client")
                                    if self.history_loaded and self.username not in line:
                                        self.play_notification_sound()
            except Exception as e:
                self.display_message("Error receiving data from server.", tag="system")
                break
        self.sock.close()

    def handle_online_users_message(self, message):
        parts = message.split()
        try:
            count_str = parts[0].split(":")[1]
            count = int(count_str)
        except:
            count = 0
        users = parts[1:]
        self.online_label.config(text=f"Currently online: {count}")
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
        # Process commands:
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
                except Exception as e:
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
            except Exception as e:
                self.display_message("Error sending message. The server may be unavailable.", tag="system")
        self.entry_field.delete(0, tk.END)

    def show_online_users(self, event=None):
        top = tk.Toplevel(self.master)
        top.title("Online Users")
        listbox = tk.Listbox(top)
        listbox.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        for user in self.current_users:
            listbox.insert(tk.END, user)

    def on_closing(self):
        self.running = False
        try:
            self.sock.close()
        except:
            pass
        self.master.destroy()


def main():
    root = tk.Tk()
    client = ChatClient(root)
    root.mainloop()


if __name__ == "__main__":
    main()
