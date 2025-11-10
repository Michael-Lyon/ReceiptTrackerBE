from fastapi import FastAPI, Depends, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from models import get_db, User, Receipt, LineItem, create_tables
from auth import create_access_token, verify_token, get_password_hash, verify_password
from simple_ocr import process_receipt
import shutil
from pathlib import Path

app = FastAPI(title="Receipt Tracker API")

# Create database tables
create_tables()

# Create upload directory
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "https://receipt-tracker-ecru.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class UserCreate(BaseModel):
    email: str
    password: str

@app.get("/")
def read_root():
    return {"message": "Receipt Tracker API"}

@app.post("/api/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    # Check if user exists
    existing = db.query(User).filter(User.email == user.email).first()
    if existing:
        raise HTTPException(400, "Email already registered")
    
    # Create user
    hashed = get_password_hash(user.password)
    db_user = User(email=user.email, password_hash=hashed)
    db.add(db_user)
    db.commit()
    return {"message": "User created successfully"}

@app.post("/api/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    
    token = create_access_token(data={"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/api/me")
def get_current_user(current_user: str = Depends(verify_token)):
    return {"email": current_user}

@app.post("/api/receipts/upload")
async def upload_receipt(
    file: UploadFile = File(...),
    current_user: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    # Validate file type - check content type OR file extension
    allowed_content_types = ["image/jpeg", "image/png", "image/jpg", "application/pdf"]
    allowed_extensions = [".jpg", ".jpeg", ".png", ".pdf"]
    
    file_extension = Path(file.filename).suffix.lower()
    
    # Allow file if either content type OR extension is valid
    valid_content_type = file.content_type in allowed_content_types
    valid_extension = file_extension in allowed_extensions
    
    if not (valid_content_type or valid_extension):
        raise HTTPException(400, "Only JPEG/PNG images and PDF files allowed")
    
    # Get user
    user = db.query(User).filter(User.email == current_user).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    # Check rate limit: maximum 10 receipts per user (increased for local testing)
    receipt_count = db.query(Receipt).filter(Receipt.user_id == user.id).count()
    if receipt_count >= 10:
        raise HTTPException(429, "Maximum of 10 receipts per user allowed. Please delete some receipts to upload new ones.")
    
    # Save file
    file_path = UPLOAD_DIR / f"{user.id}_{file.filename}"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Create receipt record
    receipt = Receipt(user_id=user.id, filename=str(file_path))
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    
    return {"id": receipt.id, "filename": file.filename}

@app.get("/api/receipts")
def list_receipts(current_user: str = Depends(verify_token), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == current_user).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    receipts = db.query(Receipt).options(joinedload(Receipt.line_items)).filter(Receipt.user_id == user.id).all()
    return receipts

@app.get("/api/receipts/{receipt_id}")
def get_receipt(receipt_id: int, current_user: str = Depends(verify_token), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == current_user).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    receipt = db.query(Receipt).options(joinedload(Receipt.line_items)).filter(Receipt.id == receipt_id, Receipt.user_id == user.id).first()
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    return receipt

@app.put("/api/receipts/{receipt_id}")
def update_receipt(
    receipt_id: int,
    data: dict,
    current_user: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == current_user).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id, Receipt.user_id == user.id).first()
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    
    # Update receipt fields
    allowed_fields = ['vendor', 'amount', 'date', 'category']
    for key, value in data.items():
        if key in allowed_fields:
            setattr(receipt, key, value)
    
    db.commit()
    db.refresh(receipt)
    return receipt

@app.delete("/api/receipts/{receipt_id}")
def delete_receipt(receipt_id: int, current_user: str = Depends(verify_token), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == current_user).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id, Receipt.user_id == user.id).first()
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    
    # Delete file if it exists
    try:
        file_path = Path(receipt.filename)
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass  # Continue even if file deletion fails
    
    db.delete(receipt)
    db.commit()
    return {"message": "Receipt deleted successfully"}

@app.post("/api/receipts/{receipt_id}/process")
def process_receipt_ocr(receipt_id: int, current_user: str = Depends(verify_token), db: Session = Depends(get_db)):
    # Get user
    user = db.query(User).filter(User.email == current_user).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    # Get receipt
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id, Receipt.user_id == user.id).first()
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    
    # Check if file exists
    if not Path(receipt.filename).exists():
        raise HTTPException(404, "Receipt image file not found")
    
    # Process receipt with OCR
    try:
        ocr_data = process_receipt(receipt.filename)
        
        if not ocr_data['success']:
            raise HTTPException(500, f"OCR processing failed: {ocr_data['error']}")
        
        # Update receipt with extracted data
        receipt.vendor = ocr_data['vendor']
        receipt.amount = ocr_data['amount']
        receipt.date = ocr_data['date']
        receipt.category = ocr_data['category']
        receipt.raw_text = ocr_data['raw_text']
        
        # Clear existing line items (keep simple for now)
        for item in receipt.line_items:
            db.delete(item)
        
        # Add line items if any (OCR processor returns empty list for now)
        for item_data in ocr_data.get('line_items', []):
            line_item = LineItem(
                receipt_id=receipt.id,
                name=item_data['name'],
                quantity=item_data['quantity'],
                unit_price=item_data['unit_price'],
                total_price=item_data['total_price']
            )
            db.add(line_item)
        
        db.commit()
        db.refresh(receipt)
        
        return {
            "id": receipt.id,
            "vendor": receipt.vendor,
            "amount": receipt.amount,
            "date": receipt.date,
            "category": receipt.category,
            "success": True
        }
        
    except Exception as e:
        raise HTTPException(500, f"OCR processing failed: {str(e)}")