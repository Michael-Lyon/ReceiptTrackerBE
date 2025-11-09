from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./receipts.db")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Receipt(Base):
    __tablename__ = "receipts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    filename = Column(String)
    vendor = Column(String, nullable=True)
    amount = Column(Float, nullable=True)
    date = Column(String, nullable=True)
    category = Column(String, nullable=True)
    raw_text = Column(Text, nullable=True)  # Use Text for longer content
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship to line items
    line_items = relationship("LineItem", back_populates="receipt", cascade="all, delete-orphan")

class LineItem(Base):
    __tablename__ = "line_items"
    id = Column(Integer, primary_key=True, index=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id"))
    name = Column(String, nullable=False)  # Item name (e.g., "Big pack", "Crispy Fried Yam")
    quantity = Column(Integer, nullable=False, default=1)  # Quantity
    unit_price = Column(Float, nullable=True)  # Price per unit
    total_price = Column(Float, nullable=False)  # Total for this line item
    
    # Relationship back to receipt
    receipt = relationship("Receipt", back_populates="line_items")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    Base.metadata.create_all(bind=engine)