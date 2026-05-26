import streamlit as st
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import os

from pdf_extractor import extract_text_from_pdf as _extract_text_from_pdf
from claim_extractor import extract_claims as _extract_claims
from verifier import verify_claim

# ============================================================================
# PAGE CONFIG & STYLING
# ============================================================================

st.set_page_config(
    page_title="Fact Check Agent",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for professional dashboard
st.markdown("""
<style>
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 2rem;
        border-radius: 10px;
        margin-bottom: 2rem;
    }
    
    .main-header h1 {
        margin: 0;
        font-size: 2.5rem;
        font-weight: 700;
    }
    
    .main-header p {
        margin: 0.5rem 0 0 0;
        font-size: 1.1rem;
        opacity: 0.95;
    }
    
    .summary-card {
        padding: 1.5rem;
        border-radius: 8px;
        text-align: center;
        font-weight: 600;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        color: white;
    }
    
    .card-total {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    }
    
    .card-verified {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
    }
    
    .card-inaccurate {
        background: linear-gradient(135deg, #f6b045 0%, #fb866a 100%);
    }
    
    .card-false {
        background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%);
    }
    
    .summary-number {
        font-size: 2.5rem;
        margin: 0.5rem 0;
    }
    
    .claim-card {
        background: white;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
    }
    
    .claim-header {
        display: flex;
        align-items: center;
        margin-bottom: 1rem;
        gap: 1rem;
    }
    
    .claim-number {
        background: #667eea;
        color: white;
        width: 40px;
        height: 40px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
    }
    
    .claim-text {
        flex: 1;
        font-size: 1.1rem;
        font-weight: 500;
        color: #333;
    }
    
    .status-badge {
        padding: 0.5rem 1rem;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.95rem;
        display: inline-block;
        margin: 0.5rem 0;
    }
    
    .status-verified {
        background: #d4edda;
        color: #155724;
        border: 1px solid #c3e6cb;
    }
    
    .status-inaccurate {
        background: #fff3cd;
        color: #856404;
        border: 1px solid #ffeeba;
    }
    
    .status-false {
        background: #f8d7da;
        color: #721c24;
        border: 1px solid #f5c6cb;
    }
    
    .info-section {
        padding: 1rem;
        margin: 0.5rem 0;
        border-radius: 6px;
        border-left: 4px solid #667eea;
        background: #f8f9fa;
    }
    
    .info-label {
        font-weight: 600;
        color: #667eea;
        font-size: 0.95rem;
        margin-bottom: 0.3rem;
    }
    
    .source-badge {
        display: inline-block;
        padding: 0.3rem 0.8rem;
        margin: 0.2rem;
        border-radius: 4px;
        font-size: 0.85rem;
        background: #f0f2f6;
        border: 1px solid #d0d4dd;
    }
    
    .source-reliable {
        background: #d4edda;
        color: #155724;
        border-color: #c3e6cb;
    }
    
    .footer {
        margin-top: 3rem;
        padding: 2rem;
        border-top: 2px solid #e0e0e0;
        text-align: center;
        color: #666;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# SAFETY CHECKS & VALIDATION
# ============================================================================

def validate_api_keys():
    """Check if required API keys are configured"""
    missing_keys = []
    
    if not os.getenv("OPENROUTER_API_KEY"):
        missing_keys.append("OPENROUTER_API_KEY")
    if not os.getenv("TAVILY_API_KEY"):
        missing_keys.append("TAVILY_API_KEY")
    
    if missing_keys:
        return False, missing_keys
    return True, []

def check_file_size(uploaded_file):
    """Check if PDF file is within reasonable size limits"""
    MAX_FILE_SIZE_MB = 50  # 50 MB limit
    
    file_size_bytes = len(uploaded_file.getvalue())
    file_size_mb = file_size_bytes / (1024 * 1024)
    
    if file_size_mb > MAX_FILE_SIZE_MB:
        return False, f"File is {file_size_mb:.1f}MB (max: {MAX_FILE_SIZE_MB}MB)"
    
    if file_size_bytes < 100:
        return False, "File is too small (likely empty)"
    
    return True, ""

def detect_scanned_pdf(text):
    """Detect if PDF is scanned (image-only) with no extractable text"""
    # Check if text is too short (scanned PDFs often yield garbage)
    if len(text.strip()) < 10:
        return True, "scanned"
    
    # Check for suspiciously high ratio of special characters (OCR artifacts)
    special_char_ratio = len([c for c in text if not c.isalnum() and c not in ' \n\t.,:;!?\'-"']) / len(text)
    if special_char_ratio > 0.4:  # More than 40% special characters = likely OCR artifacts
        return True, "ocr_artifacts"
    
    return False, ""

def is_network_available():
    """Check if network is accessible by attempting DNS resolution"""
    import socket
    try:
        # Try to resolve a common public DNS to verify connectivity
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except (socket.timeout, socket.error):
        return False

def clean_claim(claim):
    """Clean claim text: remove bullets, extra spaces, and symbols"""
    # Remove bullet points and list markers
    claim = re.sub(r'^[\s•\-\*\+\~\#\.]+', '', claim)
    
    # Remove extra whitespace (multiple spaces to single)
    claim = re.sub(r'\s+', ' ', claim)
    
    # Remove weird symbols but keep basic punctuation
    claim = re.sub(r'[^\w\s\.\,\?\!\-\(\)\'"]', '', claim)
    
    # Strip leading/trailing whitespace
    claim = claim.strip()
    
    return claim

def is_valid_claim(claim):
    """Check if a claim is meaningful and verifiable"""
    # Minimum length
    if len(claim) < 10:
        return False
    
    # Must have at least 3 words
    words = claim.split()
    if len(words) < 3:
        return False
    
    # Filter out common non-claims
    noise_patterns = [
        r"^(and|or|the|a|an|but|if|this|that|these|those|here|there|where|when|what|which|who|why|how)$",
        r"^\d+$",  # Just numbers
        r"^[a-z]$",  # Single letter
        r"^(page|chapter|section|abstract|introduction|conclusion)",
        r"^(figure|table|image|citation|reference|note)",
    ]
    
    claim_lower = claim.lower()
    for pattern in noise_patterns:
        if re.match(pattern, claim_lower):
            return False
    
    # Check for sentence-like structure (has at least one verb-like word or "has", "is", "was", "are", etc.)
    verbs = r"\b(is|are|was|were|be|have|has|had|do|does|did|can|could|will|would|should|must|may|might|make|makes|made|has|have|become|becomes|became|seem|seems|seemed|appear|appears|appeared|find|found|prove|proved|show|shows|showed|say|says|said|tells|told|states|stated|claims|claimed|suggests|suggested|indicates|indicated|reveals|revealed|demonstrates|demonstrated|requires|required|causes|caused|leads|led|results|resulted)\b"
    
    if not re.search(verbs, claim_lower):
        return False
    
    # Exclude obvious non-factual content
    excluded_words = ["copyright", "trademark", "patent", "advertisement", "ad ", "please ", "click ", "subscribe", "follow"]
    if any(word in claim_lower for word in excluded_words):
        return False
    
    return True

def score_claim(claim):
    """Score claim by importance (length, specificity, complexity)
    Higher scores = more important to fact-check
    """
    score = 0
    
    # Prefer longer claims (more specific)
    claim_len = len(claim)
    if claim_len > 50:
        score += 3
    elif claim_len > 30:
        score += 2
    else:
        score += 1
    
    # Bonus for numbers (concrete facts)
    if re.search(r'\d+', claim):
        score += 2
    
    # Bonus for comparisons (more controversial/important)
    if re.search(r'\b(more|less|greater|fewer|higher|lower|better|worse|faster|slower)\b', claim.lower()):
        score += 1
    
    # Bonus for temporal claims (specific dates/times)
    if re.search(r'\b(2\d{3}|january|february|march|april|may|june|july|august|september|october|november|december|year|week|day|month)\b', claim.lower()):
        score += 1
    
    return score

st.markdown("""
<div class="main-header">
    <h1>🔍 Fact Check Agent</h1>
    <p>Upload a PDF and get AI-powered fact verification with trusted sources</p>
</div>
""", unsafe_allow_html=True)

# ============================================================================
# STARTUP SAFETY CHECKS
# ============================================================================

# Check API keys
api_valid, missing_keys = validate_api_keys()
if not api_valid:
    st.error(f"❌ **Missing API Keys**\n\nThe following keys are not configured:\n- {chr(10).join(f'`{key}`' for key in missing_keys)}\n\nPlease add them to your `.env` file and restart the app.")
    st.stop()

# Check network (non-blocking - warn but continue)
network_ok = is_network_available()
if not network_ok:
    st.warning("⚠️ **Network connection may be unavailable**\n\nThe app requires internet access. Please check your connection if verification fails.")

uploaded_file = st.file_uploader("📄 Upload PDF", type="pdf", label_visibility="collapsed")

if uploaded_file:
    st.success("✅ PDF uploaded successfully")
    
    # Check file size
    try:
        file_valid, file_error = check_file_size(uploaded_file)
        if not file_valid:
            st.error(f"❌ **Invalid PDF File**\n\n{file_error}\n\nPlease upload a valid PDF between 100B and 50MB.")
            st.stop()
    except Exception as e:
        st.error(f"❌ Could not validate file: {str(e)}")
        st.stop()
    
    # Extract text from PDF
    try:
        extracted_text = _extract_text_from_pdf(uploaded_file)
        
        # Check for empty PDF
        if len(extracted_text.strip()) < 20:
            st.warning("⚠️ **PDF Appears Empty**\n\nNo text found in the PDF. This could mean:\n- The PDF is blank/empty\n- The PDF is a scanned image without OCR\n\n**Try:** Converting to text or running OCR before uploading.")
            st.stop()
        
        # Detect scanned PDF (image-only)
        is_scanned, scan_type = detect_scanned_pdf(extracted_text)
        if is_scanned:
            if scan_type == "scanned":
                st.warning("⚠️ **Scanned PDF Detected**\n\nThis appears to be a scanned document (image-based) without text layer.\n\n**Try:** Use an OCR tool to convert to searchable PDF first.")
            else:  # ocr_artifacts
                st.warning("⚠️ **Low Quality Text**\n\nThe PDF text appears corrupted or has too many unreadable characters (likely bad OCR or encoding).\n\n**Try:** Uploading a cleaner PDF or converting with better OCR tools.")
            st.stop()
            
    except Exception as e:
        error_msg = str(e).lower()
        if "corrupt" in error_msg or "malformed" in error_msg:
            st.error("❌ **Corrupted PDF**\n\nThe PDF file appears to be damaged or corrupted.\n\n**Try:** Opening the PDF in Adobe Reader or another viewer first to verify it's valid.")
        elif "permission" in error_msg or "password" in error_msg:
            st.error("❌ **Password Protected**\n\nThe PDF is password-protected and cannot be processed.\n\n**Try:** Removing the password protection first.")
        elif "memory" in error_msg or "out of memory" in error_msg:
            st.error("❌ **File Too Large**\n\nThe PDF is too large to process in available memory.\n\n**Try:** Splitting the PDF into smaller files.")
        else:
            st.error(f"❌ **Could Not Read PDF**\n\nError: {str(e)[:100]}\n\n**Try:** Uploading a different PDF file.")
        st.stop()

    # Extract claims
    try:
        with st.spinner("⏳ Extracting Claims..."):
            claims_text = _extract_claims(extracted_text[:10000])
    except Exception as e:
        error_msg = str(e).lower()
        if "401" in str(e) or "unauthorized" in error_msg:
            st.error("❌ API authentication failed. Please check your OpenRouter API key.")
        elif "429" in str(e) or "rate limit" in error_msg:
            st.error("❌ **Rate Limit Exceeded**\n\nToo many requests sent to the AI service.\n\n**Try:** Wait 2-3 minutes and try again.")
        elif "401" in str(e) or "unauthorized" in error_msg or "api key" in error_msg:
            st.error("❌ **Invalid API Key**\n\nYour OPENROUTER_API_KEY appears to be invalid.\n\n**Try:** Checking your .env file for correct API keys.")
        elif "timeout" in error_msg:
            st.error("❌ **Request Timeout**\n\nThe AI service is not responding quickly enough.\n\n**Try:** Checking your internet connection or try again in a moment.")
        elif "connection" in error_msg or "network" in error_msg or "resolve" in error_msg:
            st.error("❌ **Network Error**\n\nCannot reach the AI service.\n\n**Try:** Checking your internet connection or verify API service is available.")
        else:
            st.error(f"❌ **Claim Extraction Failed**\n\nError: {str(e)[:100]}\n\n**Try:** Uploading a different PDF or checking your internet connection.")
        st.stop()

    claims = [clean_claim(c) for c in claims_text.split("\n")]
    claims = [c for c in claims if is_valid_claim(c)]

    if not claims:
        st.warning("⚠️ **No Claims Found**\n\nNo verifiable claims were extracted from the PDF. This could mean:\n- The document contains only images/diagrams\n- The text is too informal or lacks factual statements\n\n**Try:** Uploading a document with clear factual statements (e.g., news article, research paper).")
        st.stop()

    # Filter out duplicates
    unique_claims = []
    claim_to_first_index = {}  # Maps claim text to its first occurrence index
    duplicate_map = {}  # Maps duplicate indices to their original claim index
    
    for idx, claim in enumerate(claims):
        # Case-insensitive duplicate check (normalize spaces)
        normalized_claim = " ".join(claim.lower().split())
        
        if normalized_claim not in claim_to_first_index:
            # First occurrence of this claim
            claim_to_first_index[normalized_claim] = len(unique_claims)
            unique_claims.append(claim)
        else:
            # Duplicate found - map it to the original claim
            original_idx = claim_to_first_index[normalized_claim]
            duplicate_map[idx] = original_idx
    
    # Show duplicate warning if any found
    if duplicate_map:
        st.info(f"ℹ️ Found {len(duplicate_map)} duplicate claim(s) - verifying unique claims only")

    # ========================================================================
    # PERFORMANCE OPTIMIZATION: Limit claims and prioritize by importance
    # ========================================================================
    MAX_CLAIMS_TO_VERIFY = 10
    claims_filtered_message = ""
    
    if len(unique_claims) > MAX_CLAIMS_TO_VERIFY:
        # Score claims by importance and keep top N
        scored_claims = [(claim, score_claim(claim)) for claim in unique_claims]
        scored_claims.sort(key=lambda x: x[1], reverse=True)  # Sort by score descending
        
        kept_claims = [claim for claim, score in scored_claims[:MAX_CLAIMS_TO_VERIFY]]
        filtered_count = len(unique_claims) - MAX_CLAIMS_TO_VERIFY
        
        # Update unique_claims to only top-scoring claims
        unique_claims = kept_claims
        claims_filtered_message = f"ℹ️ Processing {MAX_CLAIMS_TO_VERIFY} most important claims (filtered {filtered_count} less important)"
        st.info(claims_filtered_message)

    st.markdown("---")
    st.subheader(f"📋 Fact Check Results ({len(claims)} claims, {len(unique_claims)} verifying)")
    st.markdown("---")

    # Show initial status
    status_container = st.empty()
    status_container.info("⏳ Verifying Claims...")

    # Progress indicator
    progress_bar = st.progress(0)
    status_text = st.empty()

    # Verify all unique claims in parallel
    results = {}
    errors = {}
    
    try:
        with ThreadPoolExecutor(max_workers=5) as executor:
            # Submit verification tasks for unique claims only
            future_to_claim = {executor.submit(verify_claim, claim): claim for claim in unique_claims}
            
            # Process results as they complete
            completed = 0
            for future in as_completed(future_to_claim):
                claim = future_to_claim[future]
                try:
                    result = future.result()
                    results[claim] = result
                    completed += 1
                    
                    # Update progress based on unique claims
                    progress = completed / len(unique_claims)
                    progress_bar.progress(progress)
                    status_text.text(f"⏳ Verifying Facts... {completed}/{len(unique_claims)} completed")
                except Exception as e:
                    errors[claim] = str(e)
                    completed += 1
                    progress = completed / len(unique_claims)
                    progress_bar.progress(progress)
    except Exception as e:
        error_msg = str(e).lower()
        status_container.empty()
        progress_bar.empty()
        status_text.empty()
        
        if "429" in str(e) or "rate limit" in error_msg:
            st.error("❌ **Rate Limit Exceeded**\n\nToo many requests to the verification service.\n\n**Try:** Wait 2-3 minutes before trying again (or reduce the number of claims by uploading a shorter document).")
        elif "401" in str(e) or "unauthorized" in error_msg or "api key" in error_msg:
            st.error("❌ **Invalid API Keys**\n\nYour OpenRouter or Tavily API keys may be invalid or expired.\n\n**Try:** \n- Verify keys in .env file: OPENROUTER_API_KEY and TAVILY_API_KEY\n- Restart the app after updating .env\n- Check your API account for quota limits")
        elif "timeout" in error_msg or "connection" in error_msg or "resolve" in error_msg or "network" in error_msg:
            st.error("❌ **Network Connection Error**\n\nCannot reach the verification service.\n\n**Try:** \n- Check your internet connection\n- Try again in a few moments\n- Verify no firewall is blocking the service")
        else:
            st.error(f"❌ **Verification Failed**\n\nError: {str(e)[:80]}\n\n**Try:** Checking your internet connection and API key configuration, then try again.")
        st.stop()

    # Clear progress
    status_container.empty()
    progress_bar.empty()
    status_text.empty()

    # Count results (based on unique claims only)
    verified_count = 0
    false_count = 0
    inaccurate_count = 0

    for claim in unique_claims:
        if claim in results:
            status = results[claim]["status"]
            if status == "VERIFIED":
                verified_count += 1
            elif status == "INACCURATE":
                inaccurate_count += 1
            else:
                false_count += 1

    # Summary text at top
    st.markdown("---")
    if duplicate_map:
        summary_text = f"""
        ### Summary Counts
        **Total Claims:** {len(claims)} (including {len(duplicate_map)} duplicates) | **Unique:** {len(unique_claims)} | **✅ Verified:** {verified_count} | **⚠️ Inaccurate:** {inaccurate_count} | **❌ False:** {false_count}
        """
    else:
        summary_text = f"""
        ### Summary Counts
        **Total Claims:** {len(claims)} | **✅ Verified:** {verified_count} | **⚠️ Inaccurate:** {inaccurate_count} | **❌ False:** {false_count}
        """
    st.markdown(summary_text)
    st.markdown("---")

    # Summary section with colored cards
    st.markdown("", unsafe_allow_html=True)
    
    summary_cols = st.columns(4)
    
    with summary_cols[0]:
        st.markdown(f"""
        <div class="summary-card card-total">
            <div>Unique Claims</div>
            <div class="summary-number">{len(unique_claims)}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with summary_cols[1]:
        st.markdown(f"""
        <div class="summary-card card-verified">
            <div>✅ Verified</div>
            <div class="summary-number">{verified_count}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with summary_cols[2]:
        st.markdown(f"""
        <div class="summary-card card-inaccurate">
            <div>⚠️ Inaccurate</div>
            <div class="summary-number">{inaccurate_count}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with summary_cols[3]:
        st.markdown(f"""
        <div class="summary-card card-false">
            <div>❌ False</div>
            <div class="summary-number">{false_count}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")
    st.subheader("📋 Detailed Analysis")

    # Failed claims
    if errors:
        st.warning(f"⚠️ {len(errors)} claim(s) could not be verified due to service issues")
        with st.expander(f"Failed Claims ({len(errors)})"):
            for claim, error in errors.items():
                error_lower = error.lower()
                
                # Determine error type
                if "rate limit" in error_lower or "429" in error:
                    reason = "Rate limit — service is busy"
                elif "401" in error or "unauthorized" in error_lower:
                    reason = "API key error — invalid credentials"
                elif "timeout" in error_lower:
                    reason = "Request timeout — service slow"
                elif "connection" in error_lower or "network" in error_lower:
                    reason = "Network error — check internet"
                else:
                    reason = "Service unavailable"
                
                st.markdown(f"**❌ {claim}**")
                st.caption(f"⚠️ {reason}")
                st.markdown("")

    # Display individual results
    for idx, claim in enumerate(claims, 1):
        # Check if this is a duplicate
        if idx - 1 in duplicate_map:
            original_idx = duplicate_map[idx - 1]
            original_claim = unique_claims[original_idx]
            
            # Show as duplicate
            st.markdown("━" * 50)
            st.markdown(f"**Claim #{idx}:**")
            st.markdown(f"{claim}")
            st.markdown("")
            st.markdown(f"**⚪ DUPLICATE**")
            st.markdown(f"Same as Claim #{original_idx + 1} • See above for details")
            st.markdown("━" * 50)
            st.markdown("")
            continue
        
        # Original/unique claim - find its result
        # Normalize the claim for lookup
        normalized_claim = " ".join(claim.lower().split())
        
        # Find which unique claim this corresponds to
        found_result = None
        for unique_claim in unique_claims:
            if " ".join(unique_claim.lower().split()) == normalized_claim:
                if unique_claim in results:
                    found_result = results[unique_claim]
                elif unique_claim in errors:
                    # This claim had an error
                    st.markdown("━" * 50)
                    st.markdown(f"**Claim #{idx}:**")
                    st.markdown(f"{claim}")
                    st.markdown("")
                    st.markdown(f"**❌ VERIFICATION FAILED**")
                    st.markdown(f"Could not verify: {errors[unique_claim]}")
                    st.markdown("━" * 50)
                    st.markdown("")
                    found_result = "error"
                break
        
        if found_result is None:
            continue
        
        if found_result == "error":
            continue
            
        result = found_result
        status = result["status"]
        
        # Status emoji
        status_emoji = "✅" if status == "VERIFIED" else "⚠️" if status == "INACCURATE" else "❌"
        
        # Card separator
        st.markdown("━" * 50)
        
        # Claim label and text
        st.markdown(f"**Claim #{idx}:**")
        st.markdown(f"{claim}")
        st.markdown("")
        
        # Status
        st.markdown(f"### {status_emoji} {status}")
        st.markdown("")
        
        # Explanation
        if result["explanation"]:
            st.markdown(f"**Explanation:**")
            st.markdown(f"{result['explanation']}")
            st.markdown("")
        
        # Correct fact
        if result["correct_fact"]:
            st.markdown(f"**Correct Fact:**")
            st.markdown(f"{result['correct_fact']}")
            st.markdown("")
        
        # Sources (expandable)
        with st.expander(f"▶ Sources ({len(result['evidence'])} found)", expanded=False):
            if result["evidence"]:
                for i, evidence in enumerate(result["evidence"][:5], 1):
                    reliability = evidence.get("reliability", 0)
                    url = evidence['url']
                    domain = url.replace("https://", "").replace("http://", "").split("/")[0]
                    
                    # Clean domain name for display
                    clean_domain = domain.replace("www.", "").replace(".com", "").replace(".org", "").replace(".co.uk", "").title()
                    reliability_badge = "✅" if reliability > 0 else "📌"
                    
                    # Format: [🔗 Clean Name] reliability_badge
                    st.markdown(f"[🔗 **{clean_domain}**]({url}) {reliability_badge}")
                    
                    # Show title as caption
                    title = evidence['title']
                    if len(title) > 75:
                        title = title[:75] + "..."
                    st.caption(title)
                    st.markdown("")
            else:
                st.info("No sources found")
        
        # Bottom card separator
        st.markdown("━" * 50)
        st.markdown("")

    # Footer
    st.markdown(f"""
    <div class="footer">
        <p>🔍 <strong>Fact Check Agent</strong> • Professional AI-Powered Verification</p>
        <p style="font-size: 0.8rem; margin-top: 0.5rem;">
            Processed {len(claims)} claims • {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </p>
    </div>
    """, unsafe_allow_html=True)