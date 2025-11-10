import re
import pdfplumber
from pathlib import Path
from datetime import datetime

def extract_text_from_pdf(file_path):
    """Extract text from PDF using pdfplumber"""
    try:
        text = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return ""

def extract_text_from_image(file_path):
    """For images, we'll need tesseract - install it if available, otherwise return empty"""
    try:
        import pytesseract
        from PIL import Image
        
        # Basic image processing and OCR
        image = Image.open(file_path)
        text = pytesseract.image_to_string(image)
        return text
    except ImportError:
        print("Warning: pytesseract not available for image processing. Install it with: pip install pytesseract")
        return ""
    except Exception as e:
        print(f"Error extracting text from image: {e}")
        return ""

def get_file_type(file_path):
    """Determine file type"""
    file_path = Path(file_path)
    extension = file_path.suffix.lower()
    
    if extension == '.pdf':
        return 'pdf'
    elif extension in ['.jpg', '.jpeg', '.png', '.tiff', '.bmp']:
        return 'image'
    else:
        return 'unknown'

def extract_vendor(text):
    """Extract vendor name with improved patterns"""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # Check for specific known vendors first
    text_lower = text.lower()
    if 'railway corporation' in text_lower:
        return 'Railway Corporation'
    if 'electro galactica' in text_lower:
        return 'Electro Galactica Company LTD'
    
    # For OPay receipts, look for recipient details
    # Use line-by-line approach for better accuracy
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    for line in lines:
        if 'recipient details' in line.lower():
            # Extract everything after 'Recipient Details'
            parts = line.split('Details', 1)
            if len(parts) > 1:
                vendor = parts[1].strip()
                if len(vendor) > 3:
                    return vendor
    
    # Fallback to pattern matching for companies
    recipient_patterns = [
        r'recipient\s+details\s+([A-Z][A-Z\s&.-]+(?:LTD|LIMITED|INC|COMPANY|CORP|PLC))',  # Companies
        r'([A-Z][A-Za-z\s&.-]+(?:STORES?|SHOPPING|COMMUNICATIONS?|BANK|NIGERIA)(?:\s+(?:LIMITED|LTD|PLC))?)',  # Nigerian companies
    ]
    
    for pattern in recipient_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            vendor = match.strip()
            if len(vendor) > 3:
                return vendor
    
    # If no recipient found but contains OPay/Pay, it's an OPay transaction
    if any(indicator in text_lower for indicator in ['opay', 'pay transaction', '#']) and 'recipient' in text_lower:
        return 'OPay'
    
    # Look for general company patterns
    vendor_patterns = [
        r'([A-Z][A-Za-z\s&.-]+(?:Corporation|Corp|Ltd|Limited|Inc|Company|LLC|PLC))',
        r'(Railway\s+Corporation)',
        r'([A-Z][A-Z\s]{2,20}(?:LTD|LIMITED|INC|COMPANY|CORP|PLC))',
    ]
    
    for pattern in vendor_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            vendor = match.strip()
            if len(vendor) > 3 and 'bank' not in vendor.lower():
                return vendor
    
    # Look for lines that appear to be company names
    for line in lines[:5]:  # Check first 5 lines
        if any(skip in line.lower() for skip in ['invoice', 'receipt', 'transaction', 'date', 'bill to', '@']):
            continue
        
        # If line has mostly uppercase and is reasonable length
        if len(line) > 3 and len(line) < 50:
            uppercase_ratio = sum(1 for c in line if c.isupper()) / len(line.replace(' ', ''))
            if uppercase_ratio > 0.5:
                return line.strip()
    
    return None

def extract_amount(text):
    """Extract amount with improved patterns for both USD and Naira"""
    # Patterns for different currency formats
    patterns = [
        # USD patterns (for Railway invoices) - note: no need to escape $ in raw strings
        r'Amount\s+due\s+\$([0-9,]+\.?\d{0,2})\s*USD',  # "Amount due $5.00 USD"
        r'\$([0-9,]+\.?\d{0,2})\s*USD\s+due',           # "$5.00 USD due"
        r'Total\s+\$([0-9,]+\.?\d{0,2})',               # "Total $5.00"
        r'Amount\s+due\s+\$([0-9,]+\.?\d{0,2})',        # "Amount due $5.00"
        
        # Naira patterns (for OPay receipts)
        r'₦\s*([0-9,]+\.?\d{0,2})',                     # "₦7,000.00"
        r'#([0-9,]+\.?\d{0,2})',                        # "#7,000.00" (OPay format)
        r'#([0-9,]+)',                                  # "#250000" (no decimal)
        r'([0-9,]+\.?\d{0,2})\s*naira',                 # "7,000.00 naira"
        
        # Generic patterns
        r'total[:\s]*\$?([0-9,]+\.?\d{0,2})',           # "TOTAL: $5.00" or "TOTAL: 7000"
        r'amount[:\s]*\$?([0-9,]+\.?\d{0,2})',          # "AMOUNT: $5.00"
    ]
    
    amounts_found = []
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            try:
                amount_str = match.replace(',', '')  # Remove commas
                amount = float(amount_str)
                
                # Filter out unreasonably large amounts (likely IDs)
                if 0.01 <= amount <= 10000000:  # Reasonable range (up to 10 million naira/dollars)
                    amounts_found.append(amount)
            except ValueError:
                continue
    
    if not amounts_found:
        return None
    
    # Return the largest amount found (usually the total)
    return max(amounts_found)

def extract_date(text):
    """Extract date with improved patterns"""
    date_patterns = [
        # Full month names
        r'((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})',
        # Short month names with time (OPay format) - more flexible
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-?\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\s+\d{1,2}:\d{2}:\d{2})',
        # Short month names with ordinal indicators
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:st|nd|rd|th),?\s+\d{4})',
        # Short month names  
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*-?\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})',
        # Standard formats
        r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
        r'(\d{4}-\d{1,2}-\d{1,2})',
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    return None

def classify_category(vendor, text):
    """Classify receipt category"""
    vendor_lower = (vendor or '').lower()
    text_lower = text.lower()
    
    # Check vendor-specific patterns first (more accurate)
    vendor_categories = {
        'technology': ['railway', 'hosting', 'domain', 'server', 'cloud', 'software', 'railway corporation'],
        'electronics': ['electro', 'galactica', 'electronics', 'computer', 'tech'],
        'groceries': ['shoprite', 'grocery', 'supermarket', 'food', 'market', 'stores'],
        'retail': ['konga', 'jumia', 'amazon', 'shop', 'mall', 'boutique', 'shopping', 'online shopping'],
        'utilities': ['mtn', 'airtel', 'glo', 'communications', 'telecom', 'electric', 'water', 'internet', 'phone'],
        'financial': ['bank', 'first bank', 'access bank', 'gtbank', 'zenith bank'],
        'restaurant': ['restaurant', 'cafe', 'dining', 'bar', 'kfc', 'dominos'],
        'fuel': ['gas', 'fuel', 'petrol', 'filling station', 'mobil', 'total', 'oando'],
        'transportation': ['uber', 'bolt', 'taxi', 'transport', 'airline'],
    }
    
    # First check vendor name for specific categorization
    for category, keywords in vendor_categories.items():
        if any(keyword in vendor_lower for keyword in keywords):
            return category
    
    # If vendor doesn't match, check full text but avoid false positives
    general_categories = {
        'financial': ['opay', 'mobile money', 'wallet', 'payment app'],
        'personal': ['opay | 7', 'opay | 8', 'opay | 9'],  # Personal phone numbers in OPay format
        'business': ['company ltd', 'limited', 'corporation', 'enterprise'],
    }
    
    # Check if it's a personal transfer (individual recipient)
    if vendor and len(vendor.split()) >= 2:  # Full name format
        # Check if vendor looks like a person's name (no company indicators)
        company_indicators = ['ltd', 'limited', 'inc', 'corp', 'company', 'plc', 'stores', 'bank', 'communications']
        if not any(indicator in vendor.lower() for indicator in company_indicators):
            return 'personal'
    
    for category, keywords in general_categories.items():
        if any(keyword in text_lower for keyword in keywords):
            # Only if it's not already categorized by vendor
            return category
    
    return 'other'

def process_receipt(file_path):
    """Main receipt processing function"""
    try:
        file_type = get_file_type(file_path)
        
        if file_type == 'pdf':
            text = extract_text_from_pdf(file_path)
        elif file_type == 'image':
            text = extract_text_from_image(file_path)
        else:
            return {
                'vendor': None,
                'amount': None,
                'date': None,
                'category': 'other',
                'line_items': [],
                'raw_text': '',
                'success': False,
                'error': 'Unsupported file type'
            }
        
        if not text or len(text.strip()) < 10:
            return {
                'vendor': None,
                'amount': None,
                'date': None,
                'category': 'other',
                'line_items': [],
                'raw_text': text,
                'success': False,
                'error': 'Could not extract meaningful text from file'
            }
        
        # Extract information
        vendor = extract_vendor(text)
        amount = extract_amount(text)
        date = extract_date(text)
        category = classify_category(vendor, text)
        
        return {
            'vendor': vendor,
            'amount': amount,
            'date': date,
            'category': category,
            'line_items': [],  # Keep simple for now
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