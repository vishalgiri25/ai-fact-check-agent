import fitz

def extract_text_from_pdf(uploaded_file):
    
    text = ""

    try:
        pdf = fitz.open(
            stream=uploaded_file.read(),
            filetype="pdf"
        )
    except Exception as e:
        if "PDF" in str(e) or "malformed" in str(e).lower():
            raise Exception("Invalid PDF file: The file appears to be corrupted or not a valid PDF")
        else:
            raise Exception(f"Error reading PDF: {str(e)}")

    try:
        for page in pdf:
            text += page.get_text()
    except Exception as e:
        raise Exception(f"Error extracting text from PDF: {str(e)}")

    if not text or len(text.strip()) < 10:
        raise Exception("No readable text found in PDF: Document may be empty or image-based")

    return text