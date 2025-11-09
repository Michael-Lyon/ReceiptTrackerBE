import pytesseract
import cv2
import re
import numpy as np
from datetime import datetime
from pathlib import Path
from PIL import Image
import PyPDF2
import pdfplumber
import io

def preprocess_image(image_path):
    """Basic image preprocessing for OCR"""
    # Read image
    img = cv2.imread(str(image_path))
    
    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Apply OTSU thresholding for better text extraction
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Optional: Apply Gaussian blur to reduce noise
    blurred = cv2.GaussianBlur(thresh, (1, 1), 0)
    
    return blurred

def extract_text_from_pdf(file_path):
    """Extract text from PDF receipt using pdfplumber"""
    try:
        text = ""
        
        # Try pdfplumber first (better for structured PDFs)
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        
        # If pdfplumber didn't extract much, fallback to PyPDF2
        if len(text.strip()) < 50:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return ""

def detect_file_type(file_path):
    """Detect if file is PDF or image"""
    file_path = Path(file_path)
    extension = file_path.suffix.lower()
    
    if extension == '.pdf':
        return 'pdf'
    elif extension in ['.jpg', '.jpeg', '.png', '.tiff', '.bmp']:
        return 'image'
    else:
        return 'unknown'

def extract_text(file_path):
    """Extract text from receipt file (image or PDF)"""
    try:
        file_type = detect_file_type(file_path)
        
        if file_type == 'pdf':
            # Extract text from PDF
            return extract_text_from_pdf(file_path)
        elif file_type == 'image':
            # Preprocess image and extract text using OCR
            processed = preprocess_image(file_path)
            text = pytesseract.image_to_string(processed, config='--psm 6')
            return text
        else:
            print(f"Unsupported file type: {file_type}")
            return ""
    except Exception as e:
        print(f"Error extracting text: {e}")
        return ""

def extract_vendor(text):
    """Extract vendor name - improved for Nigerian receipts"""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # Look for company names in typical positions
    vendor_patterns = [
        r'recipient details\s+([A-Z][A-Z\s&.-]+(?:LTD|LIMITED|INC|COMPANY|CORP|PLC)?)',  # After "Recipient Details"
        r'merchant[:\s]+([A-Z][A-Z\s&.-]+(?:LTD|LIMITED|INC|COMPANY|CORP|PLC)?)',       # After "Merchant:"
        r'payee[:\s]+([A-Z][A-Z\s&.-]+(?:LTD|LIMITED|INC|COMPANY|CORP|PLC)?)',         # After "Payee:"
        r'([A-Z][A-Z\s&.-]+(?:LTD|LIMITED|INC|COMPANY|CORP|PLC))',                     # Any company name pattern
    ]
    
    # First try pattern matching
    for pattern in vendor_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            vendor = match.group(1).strip()
            # Clean up vendor name - remove bank info if included
            vendor = vendor.split('\n')[0].strip()  # Take only first line
            if len(vendor) > 3 and 'bank' not in vendor.lower():  # Must be at least 4 characters and not a bank
                return vendor
    
    # Fallback: look for lines that look like company names
    for line in lines:
        # Skip obvious non-vendor lines
        if any(skip in line.lower() for skip in ['transaction', 'receipt', 'successful', 'opay', '@', 'nov ', 'session', 'enjoy']):
            continue
        
        # Look for lines with mostly uppercase letters (company names)
        if len(line) > 3 and sum(1 for c in line if c.isupper()) > len(line) * 0.6:
            vendor = re.sub(r'[^\w\s&.-]', '', line)  # Clean special chars
            return vendor.strip()
    
    # Last resort: first meaningful line
    for line in lines:
        if len(line) > 3 and not any(skip in line.lower() for skip in ['@', 'transaction', 'receipt']):
            vendor = re.sub(r'[^\w\s&.-]', '', line)
            return vendor.strip()
    
    return None

def extract_amount(text):
    """Extract total amount using regex patterns - Updated for Nigerian receipts and international invoices"""
    # Nigerian amount patterns (₦ Naira) and international formats
    patterns = [
        r'₦\s*([0-9,]+\.?\d{0,2})',           # "₦7,000.00" or "₦7,000"
        r'([0-9,]+\.?\d{0,2})\s*naira',       # "7,000.00 naira"
        r'total[:\s]*₦?\s*([0-9,]+\.?\d{0,2})',  # "TOTAL: ₦7,000.00"
        r'amount[:\s]*₦?\s*([0-9,]+\.?\d{0,2})',  # "AMOUNT: ₦7,000.00"
        r'\$\s*([0-9,]+\.?\d{0,2})',          # "$12.34" (USD for international invoices)
        r'([0-9,]+\.?\d{0,2})\s*USD',         # "12.34 USD"
        r'total[:\s]*\$?\s*([0-9,]+\.?\d{0,2})',  # "TOTAL: $12.34"
        r'amount[:\s]*\$?\s*([0-9,]+\.?\d{0,2})',  # "AMOUNT: $12.34"
        r'^([0-9]{1,3}(?:,[0-9]{3})*\.?[0-9]{0,2})$',  # Standalone amounts like "7,000.00" on their own line
        r'\n([0-9]{1,3}(?:,[0-9]{3})*\.?[0-9]{0,2})\n',  # Amount surrounded by newlines
    ]
    
    amounts = []
    
    for pattern in patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            try:
                amount_str = match.group(1).replace(',', '')  # Remove commas
                amount = float(amount_str)
                
                # Filter out unreasonably large amounts (likely transaction IDs)
                if amount > 1000000:  # More than 1 million naira is likely an ID
                    continue
                
                # Get position in text (prefer amounts in top or middle for Nigerian receipts)
                position = match.start() / len(text)
                
                amounts.append((amount, position))
            except (ValueError, IndexError):
                continue
    
    if not amounts:
        return None
    
    # Filter out very small amounts (likely unit prices or fees)
    significant_amounts = [(amt, pos) for amt, pos in amounts if amt >= 0.50]
    
    if not significant_amounts:
        return amounts[0][0] if amounts else None
    
    # For invoices/receipts, prioritize amounts that appear later in the document
    # (total, amount due) over earlier amounts (subtotal, line items)
    # Also give preference to "total" or "due" context
    
    # Check for amounts with "total", "due", or "amount" keywords nearby
    final_amounts = []
    for amt, pos in significant_amounts:
        # Higher score for larger amounts and later position
        position_score = pos * 100  # Later in document = higher score
        size_score = min(amt, 1000)  # Cap size influence
        
        # Bonus for amounts that are likely "final" amounts
        text_around = text[max(0, int(pos * len(text)) - 50):int(pos * len(text)) + 50].lower()
        if any(keyword in text_around for keyword in ['total', 'due', 'amount due', 'pay']):
            position_score += 50  # Bonus for final amount context
        
        final_score = position_score + size_score
        final_amounts.append((amt, pos, final_score))
    
    # Sort by final score (highest first)
    final_amounts.sort(key=lambda x: x[2], reverse=True)
    
    # Return the amount with the highest final score
    return final_amounts[0][0]

def extract_date(text):
    """Extract transaction date - Updated for Nigerian formats"""
    # Nigerian and international date patterns
    patterns = [
        r'(Nov\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\s+\d{1,2}:\d{2}:\d{2})',  # "Nov 7th, 2025 17:53:25"
        r'(Nov\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})',  # "Nov 7th, 2025"
        r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',  # 12/31/2024, 12-31-24
        r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})',  # 31 Dec 2024
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{2,4})',  # December 31, 2024
        r'(\d{4}-\d{1,2}-\d{1,2})',  # 2024-12-31 (ISO format)
        r'(\d{2}/\d{2}/\d{4})',  # DD/MM/YYYY
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            date_str = match.group(1) if len(match.groups()) > 0 else match.group(0)
            return date_str.strip()
    
    return None

def classify_category(vendor, text):
    """Classify receipt category - Updated for Nigerian businesses and international services"""
    content = ((vendor or '') + ' ' + text).lower()
    
    categories = {
        'financial': ['opay', 'bank', 'transfer', 'payment', 'transaction', 'mobile money', 'fintech'],
        'electronics': ['electro', 'galactica', 'electronics', 'computer', 'tech', 'gadget'],
        'technology': ['hosting', 'domain', 'server', 'cloud', 'software', 'saas', 'railway', 'vercel', 'netlify', 'aws', 'invoice'],
        'business': ['company ltd', 'limited', 'corporation', 'enterprise', 'services', 'consultant'],
        'groceries': ['grocery', 'supermarket', 'food', 'market', 'shoprite', 'spar', 'provision'],
        'restaurant': ['restaurant', 'cafe', 'pizza', 'dining', 'bar', 'grill', 'kitchen', 'eatery'],
        'fuel': ['gas', 'fuel', 'petrol', 'filling station', 'total', 'mobil', 'oando'],
        'retail': ['store', 'shop', 'mall', 'boutique', 'clothing', 'fashion'],
        'pharmacy': ['pharmacy', 'medical', 'drug', 'health', 'hospital', 'clinic'],
        'transportation': ['uber', 'bolt', 'taxi', 'bus', 'transport', 'travel'],
        'utilities': ['electric', 'water', 'nepa', 'internet', 'phone', 'utility', 'telecom', 'mtn', 'airtel'],
        'education': ['school', 'university', 'education', 'training', 'course'],
    }
    
    for category, keywords in categories.items():
        if any(keyword in content for keyword in keywords):
            return category
    
    return 'other'

def extract_line_items(text):
    """Extract line items from receipt text"""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    line_items = []
    
    # Patterns for line items (name, quantity, price)
    patterns = [
        # Pattern: "Item Name    Qty    Price" or "Item Name    Pcs    2    800.00"
        r'^([A-Za-z][A-Za-z\s\.,&-]+?)\s+(Pcs?|REGULAR)\s+(\d+)\s+([0-9,]+\.?\d{0,2})$',
        # Pattern: "Item Name    Price" (assume quantity = 1)
        r'^([A-Za-z][A-Za-z\s\.,&-]+?)\s+([0-9,]+\.?\d{0,2})$',
        # Pattern with different separators
        r'^([A-Za-z][A-Za-z\s\.,&-]+?)\s+(?:Pcs?|REGULAR|x)?\s*(\d+)?\s*x?\s*([0-9,]+\.?\d{0,2})$'
    ]
    
    for line in lines:
        # Skip header lines and totals
        if any(skip in line.lower() for skip in ['item name', 'subtotal', 'total', 'discount', 'settled', 'thank you', 'receipt', '====']):
            continue
        
        # Skip very short lines or lines without numbers
        if len(line) < 5 or not any(c.isdigit() for c in line):
            continue
            
        for pattern in patterns:
            match = re.match(pattern, line.strip(), re.IGNORECASE)
            if match:
                groups = match.groups()
                
                if len(groups) == 4:  # Full pattern with unit type
                    name, unit_type, qty, price = groups
                    quantity = int(qty)
                    total_price = float(price.replace(',', ''))
                    unit_price = total_price / quantity if quantity > 0 else total_price
                elif len(groups) == 3:  # Flexible pattern  
                    name, qty_or_price, price_or_empty = groups
                    if qty_or_price and qty_or_price.isdigit():
                        # qty_or_price is quantity
                        quantity = int(qty_or_price)
                        total_price = float(price_or_empty.replace(',', ''))
                        unit_price = total_price / quantity if quantity > 0 else total_price
                    else:
                        # qty_or_price is actually price
                        quantity = 1
                        total_price = float(qty_or_price.replace(',', ''))
                        unit_price = total_price
                elif len(groups) == 2:  # Simple name + price
                    name, price = groups
                    quantity = 1
                    total_price = float(price.replace(',', ''))
                    unit_price = total_price
                else:
                    continue
                
                # Clean up name
                name = name.strip().title()
                
                # Filter out very small amounts (likely not real items)
                if total_price < 10:
                    continue
                
                line_items.append({
                    'name': name,
                    'quantity': quantity,
                    'unit_price': unit_price,
                    'total_price': total_price
                })
                break  # Found a match, move to next line
    
    return line_items

def process_receipt(image_path):
    """Complete receipt processing pipeline"""
    try:
        # Extract text from image
        text = extract_text(image_path)
        
        if not text or len(text.strip()) < 10:
            return {
                'vendor': None,
                'amount': None,
                'date': None,
                'category': 'other',
                'line_items': [],
                'raw_text': text,
                'success': False,
                'error': 'Could not extract meaningful text from image'
            }
        
        # Extract individual fields
        vendor = extract_vendor(text)
        amount = extract_amount(text)
        date = extract_date(text)
        category = classify_category(vendor, text)
        line_items = extract_line_items(text)

        return {
            'vendor': vendor,
            'amount': amount,
            'date': date,
            'category': category,
            'line_items': line_items,
            'raw_text': text,
            'success': True,
            'error': None
        }

    except Exception as e:
        return {
            'vendor': None,
            'amount': None,
            'date': None,
            'category': 'other',
            'line_items': [],
            'raw_text': '',
            'success': False,
            'error': str(e)
        }