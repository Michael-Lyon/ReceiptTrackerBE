import anthropic
import base64
import json
from pathlib import Path
import pdfplumber
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize Claude client
client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

# Test mode flag - set to True to use mock data while setting up Claude billing
TEST_MODE = os.getenv("CLAUDE_TEST_MODE", "false").lower() == "true"

def convert_pdf_to_image(pdf_path):
    """Convert first page of PDF to image for Claude processing"""
    try:
        # For now, we'll extract text from PDF and process it as text
        # In production, you'd want to convert PDF to image
        with pdfplumber.open(pdf_path) as pdf:
            if pdf.pages:
                return pdf.pages[0].extract_text()
        return None
    except Exception as e:
        print(f"Error converting PDF: {e}")
        return None

def encode_image(image_path):
    """Encode image to base64 for Claude API"""
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        print(f"Error encoding image: {e}")
        return None

def get_file_type(file_path):
    """Determine if file is image or PDF"""
    file_path = Path(file_path)
    extension = file_path.suffix.lower()
    
    if extension == '.pdf':
        return 'pdf'
    elif extension in ['.jpg', '.jpeg', '.png']:
        return 'image'
    else:
        return 'unknown'

def create_mock_response(file_path):
    """Create mock response for testing without Claude API calls"""
    file_name = Path(file_path).name.lower()
    
    # Mock data based on your actual files
    if "railway" in file_name or "invoice" in file_name:
        return {
            'vendor': 'Railway Corporation',
            'amount': 5.00 if "92ba953e" in file_name else 7.15,
            'date': '2025-10-14' if "92ba953e" in file_name else '2025-11-03',
            'category': 'technology',
            'line_items': [],
            'raw_text': 'Mock response for Railway invoice',
            'success': True,
            'error': None
        }
    elif "opay" in file_name or "photo" in file_name:
        return {
            'vendor': 'OPay',
            'amount': 7000.00,
            'date': '2025-11-07',
            'category': 'financial',
            'line_items': [],
            'raw_text': 'Mock response for OPay receipt',
            'success': True,
            'error': None
        }
    else:
        return {
            'vendor': 'Test Vendor',
            'amount': 100.00,
            'date': '2025-11-10',
            'category': 'other',
            'line_items': [],
            'raw_text': 'Mock response for unknown receipt',
            'success': True,
            'error': None
        }

def process_receipt_with_claude(file_path):
    """Process receipt using Claude API"""
    try:
        # If in test mode, return mock data
        if TEST_MODE:
            return create_mock_response(file_path)
        file_type = get_file_type(file_path)
        
        if file_type == 'pdf':
            # For PDFs, extract text and send to Claude
            text_content = convert_pdf_to_image(file_path)
            if not text_content:
                return {
                    'vendor': None,
                    'amount': None,
                    'date': None,
                    'category': 'other',
                    'line_items': [],
                    'raw_text': '',
                    'success': False,
                    'error': 'Could not extract text from PDF'
                }
            
            # Send text to Claude for processing
            message = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": f"""Please extract the following information from this receipt/invoice text and return it as valid JSON:

Text: {text_content}

Extract:
- vendor: company/business name
- amount: total amount due (number only, no currency symbol)
- date: transaction date in YYYY-MM-DD format if possible, otherwise as written
- category: one of [technology, business, financial, electronics, groceries, restaurant, fuel, retail, pharmacy, transportation, utilities, education, other]

Return only valid JSON in this format:
{{
    "vendor": "Company Name",
    "amount": 12.34,
    "date": "2025-10-14",
    "category": "technology"
}}"""
                }]
            )
            
        elif file_type == 'image':
            # For images, encode and send to Claude
            image_data = encode_image(file_path)
            if not image_data:
                return {
                    'vendor': None,
                    'amount': None,
                    'date': None,
                    'category': 'other',
                    'line_items': [],
                    'raw_text': '',
                    'success': False,
                    'error': 'Could not encode image'
                }
            
            # Determine image format
            file_extension = Path(file_path).suffix.lower()
            media_type = f"image/{'jpeg' if file_extension in ['.jpg', '.jpeg'] else 'png'}"
            
            message = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data
                            }
                        },
                        {
                            "type": "text",
                            "text": """Please extract the following information from this receipt/invoice image and return it as valid JSON:

Extract:
- vendor: company/business name
- amount: total amount due (number only, no currency symbol)
- date: transaction date in YYYY-MM-DD format if possible, otherwise as written
- category: one of [technology, business, financial, electronics, groceries, restaurant, fuel, retail, pharmacy, transportation, utilities, education, other]

Return only valid JSON in this format:
{
    "vendor": "Company Name",
    "amount": 12.34,
    "date": "2025-10-14",
    "category": "technology"
}"""
                        }
                    ]
                }]
            )
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
        
        # Parse Claude's response
        response_text = message.content[0].text.strip()
        
        # Extract JSON from response (Claude might include extra text)
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}') + 1
        
        if start_idx == -1 or end_idx == 0:
            return {
                'vendor': None,
                'amount': None,
                'date': None,
                'category': 'other',
                'line_items': [],
                'raw_text': response_text,
                'success': False,
                'error': 'Could not parse Claude response'
            }
        
        json_str = response_text[start_idx:end_idx]
        parsed_data = json.loads(json_str)
        
        return {
            'vendor': parsed_data.get('vendor'),
            'amount': parsed_data.get('amount'),
            'date': parsed_data.get('date'),
            'category': parsed_data.get('category', 'other'),
            'line_items': [],  # We'll keep this simple for now
            'raw_text': response_text,
            'success': True,
            'error': None
        }
        
    except json.JSONDecodeError as e:
        return {
            'vendor': None,
            'amount': None,
            'date': None,
            'category': 'other',
            'line_items': [],
            'raw_text': response_text if 'response_text' in locals() else '',
            'success': False,
            'error': f'JSON parsing error: {str(e)}'
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
            'error': f'Claude API error: {str(e)}'
        }

# For backward compatibility, keep the same function name
def process_receipt(image_path):
    """Process receipt using Claude API (replaces OCR)"""
    return process_receipt_with_claude(image_path)