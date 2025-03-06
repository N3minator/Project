import os

os.environ["TCL_LIBRARY"] = r"C:\Users\Виталик\AppData\Local\Programs\Python\Python313\tcl\tcl8.6"
os.environ["TK_LIBRARY"] = r"C:\Users\Виталик\AppData\Local\Programs\Python\Python313\tcl\tk8.6"

import socket
import threading
import tkinter as tk
from tkinter import simpledialog, scrolledtext, filedialog
import winsound  # Used for sound notifications (Windows only)

HOST = '127.0.0.1'
PORT = 9090


class ChatClient:
    def __init__(self, master):
        self.master = master
        self.master.title("Chat Client")

        # Top panel: online users label + chat export button
        top_frame = tk.Frame(master)
        top_frame.pack(pady=5)

        self.online_label = tk.Label(top_frame, text="Current online: 0", fg="blue", cursor="hand2")
        self.online_label.pack(side=tk.LEFT)
        self.online_label.bind("<Button-1>", self.show_online_users)

        self.export_button = tk.Button(top_frame, text="Export Chat", command=self.export_chat)
        self.export_button.pack(side=tk.LEFT, padx=10)

        # List of online users (local)
        self.current_users = []

        # Message display area with scrolling
        self.text_area = scrolledtext.ScrolledText(master, state='disabled', wrap='word')
        self.text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        self.text_area.tag_config("system", foreground="blue", font=("Helvetica", 10, "italic"))
        self.text_area.tag_config("client", foreground="black", font=("Helvetica", 10))

        # Input panel and "Send" button
        entry_frame = tk.Frame(master)
        entry_frame.pack(pady=5, fill=tk.X)

        self.entry_field = tk.Entry(entry_frame)
        self.entry_field.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.entry_field.bind("<Return>", self.send_message)

        self.send_button = tk.Button(entry_frame, text="Send", command=self.send_message)
        self.send_button.pack(side=tk.RIGHT, padx=5)

        # Request username
        self.username = simpledialog.askstring("Username", "Enter your name:", parent=self.master)
        if not self.username:
            self.master.destroy()
            return

        # Connect to the server
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((HOST, PORT))
        self.running = True

        # Send username to the server
        self.sock.sendall(self.username.encode('utf-8'))

        # Start message receiving thread
        self.receive_thread = threading.Thread(target=self.receive_loop)
        self.receive_thread.start()

        # Handle window closing
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def export_chat(self):
        # Exports the current chat content to a .txt file.
        chat_text = self.text_area.get("1.0", tk.END)
        file_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(chat_text)

    def play_notification_sound(self):
        # Plays a sound when a new message is received.
        try:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS)
        except:
            pass

    def receive_loop(self):
        buffer = ""
        while self.running:
            try:
                data = self.sock.recv(1024)
                if not data:
                    break

                buffer += data.decode('utf-8')
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    if line.startswith("ONLINE_USERS:"):
                        self.handle_online_users_message(line)
                    else:
                        # If the message contains "System:", consider it a system message
                        if "System:" in line:
                            self.display_message(line, tag="system")
                        else:
                            self.display_message(line, tag="client")
                            # Play a notification sound if the message is not from the user
                            if self.username not in line:
                                self.play_notification_sound()
            except:
                break
        self.sock.close()

    def handle_online_users_message(self, message):
        parts = message.split()
        count_str = parts[0].split(":")[1]
        count = int(count_str)
        users = parts[1:]
        self.online_label.config(text=f"Current online: {count}")
        self.current_users = users

    def display_message(self, message, tag="client"):
        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, message + "\n", tag)
        self.text_area.config(state='disabled')
        self.text_area.see(tk.END)

    def clear_chat(self):
        # Clears the chat window.
        self.text_area.config(state='normal')
        self.text_area.delete("1.0", tk.END)
        self.text_area.config(state='disabled')

    def show_help(self):
        # Displays a list of available commands.
        help_text = (
            "Available commands:\n"
            "/who - list users\n"
            "/clear - clear chat\n"
            "/pm <username> <message> - private message\n"
            "/help - help"
        )
        self.display_message(help_text, tag="system")

    def send_message(self, event=None):
        msg = self.entry_field.get().strip()
        if not msg:
            return

        if msg.startswith("/"):
            if msg.startswith("/who"):
                self.display_message("Users: " + ", ".join(self.current_users), tag="system")
            elif msg.startswith("/clear"):
                self.clear_chat()
            elif msg.startswith("/help"):
                self.show_help()
            elif msg.startswith("/pm"):
                parts = msg.split(" ", 2)
                if len(parts) < 3:
                    self.display_message("Error: Usage /pm <username> <message>", tag="system")
                else:
                    self.sock.sendall(msg.encode('utf-8'))
            else:
                self.display_message("Unknown command. Use /help", tag="system")
            self.entry_field.delete(0, tk.END)
            return

        self.sock.sendall(msg.encode('utf-8'))
        self.entry_field.delete(0, tk.END)

    def show_online_users(self, event=None):
        # Opens a window showing the list of online users.
        top = tk.Toplevel(self.master)
        top.title("Online Users List")
        listbox = tk.Listbox(top)
        listbox.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        for user in self.current_users:
            listbox.insert(tk.END, user)

    def on_closing(self):
        self.running = False
        self.sock.close()
        self.master.destroy()


def main():
    root = tk.Tk()
    client = ChatClient(root)
    root.mainloop()


if __name__ == "__main__":
    main()
