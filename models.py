from sqlalchemy import Column, Integer, String, DateTime, func
from database import Base


class ChatMessage(Base):
    __tablename__ = 'chat_messages'

    id = Column(Integer, primary_key=True)
    username = Column(String(50))
    message = Column(String(500))
    timestamp = Column(DateTime, default=func.now())

    def __repr__(self):
        return f"<ChatMessage(username='{self.username}', message='{self.message}', timestamp='{self.timestamp}')>"


class PrivateMessage(Base):
    __tablename__ = 'private_messages'

    id = Column(Integer, primary_key=True)
    sender = Column(String(50))
    receiver = Column(String(50))
    message = Column(String(500))
    timestamp = Column(DateTime, default=func.now())

    def __repr__(self):
        return f"<PrivateMessage(sender='{self.sender}', receiver='{self.receiver}', message='{self.message}', timestamp='{self.timestamp}')>"
