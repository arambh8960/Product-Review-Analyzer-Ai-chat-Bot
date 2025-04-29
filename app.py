import os
import logging
import google.generativeai as genai
from flask import Flask, render_template, request, jsonify
import json
import trafilatura
import urllib.parse

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default_secret_key")

# Configure Gemini API
API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyATq02UU7l4jyyTLoJdqzP_HwujVTkSBjw")
genai.configure(api_key=API_KEY)

# Initialize the model variable
model = None

# Use the model that we know exists from the logs
try:
    logger.info("Fetching available Gemini models...")
    available_models = genai.list_models()
    model_names = [m.name for m in available_models]
    logger.info(f"Available models count: {len(model_names)}")
    
    # Try a few models we've seen in the logs, in order of preference
    model_candidates = [
        'models/gemini-1.5-flash',
        'models/chat-bison-001', 
        'models/text-bison-001'
    ]
    
    # Try to initialize each model in sequence until one works
    for candidate in model_candidates:
        try:
            logger.info(f"Attempting to initialize model: {candidate}")
            model = genai.GenerativeModel(candidate)
            
            # Test with a minimal prompt
            test_response = model.generate_content("Hello")
            logger.info(f"Successfully initialized and verified model: {candidate}")
            # If we got here, the model is working
            break
        except Exception as model_error:
            logger.warning(f"Failed to initialize model {candidate}: {str(model_error)}")
            # Continue to the next candidate
    
    # If no model was successfully initialized
    if model is None:
        logger.error("All standard models failed. Trying direct model name from the logs.")
        # Try with the actual model name from the last logs
        logger.warning("Trying with model 'models/gemini-1.5-flash-latest'")
        model = genai.GenerativeModel('models/gemini-1.5-flash-latest')
except Exception as e:
    logger.error(f"Complete failure initializing any Gemini model: {str(e)}")
    logger.critical("Unable to initialize any model - API connectivity issues likely")

@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze_review():
    """Analyze a product review using Gemini API."""
    try:
        # Get the review text from the request
        data = request.get_json()
        review_text = data.get('review', '')
        
        if not review_text:
            return jsonify({'error': 'No review text provided'}), 400
        
        # Create the prompt for Gemini
        prompt = f"""
        You are a product review analyzer with expertise in detecting fake reviews. Please analyze the following product review:
        
        "{review_text}"
        
        Please provide the following analysis in JSON format:
        1. Sentiment: Overall sentiment (positive, negative, or neutral)
        2. Score: A numerical score from 1-10
        3. Key Points: List of main points from the review (maximum 5)
        4. Strengths: Product strengths mentioned (maximum 3)
        5. Weaknesses: Product weaknesses mentioned (maximum 3)
        6. Summary: A brief summary of the review (maximum 2 sentences)
        7. Improvement Suggestions: Suggested improvements based on the review (maximum 2)
        8. AuthenticityScore: A numerical score from 1-100 indicating how likely the review is genuine (where 100 is definitely genuine)
        9. AuthenticityAssessment: A brief assessment of whether the review seems authentic or potentially fake, and what factors led to this determination
        
        Factors that might indicate a fake review:
        - Overly positive or negative language without specific details
        - Generic statements that could apply to any product
        - Excessive use of brand names
        - Language inconsistencies or awkward phrasing
        - Lack of personal experience details
        
        Factors indicating authentic reviews:
        - Specific details about product usage
        - Balanced pros and cons
        - Specific context about how they used the product
        - Mentions of comparable products
        - Natural language patterns
        
        Return only a valid JSON object with these fields.
        """
        
        # Generate response from Gemini
        response = model.generate_content(prompt)
        
        # Process the response
        response_text = response.text
        
        # Extract JSON from the response
        # Sometimes the API response contains markdown code blocks, so we need to extract the JSON
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            json_str = response_text.split("```")[1].strip()
        else:
            json_str = response_text
        
        # Clean the JSON string if needed
        json_str = json_str.replace('\n', ' ').strip()
        
        try:
            # Parse the JSON response
            analysis = json.loads(json_str)
            return jsonify(analysis)
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON: {e}")
            logger.debug(f"Response text: {response_text}")
            logger.debug(f"Extracted JSON string: {json_str}")
            return jsonify({
                'error': 'Failed to parse the response from Gemini API',
                'raw_response': response_text
            }), 500
            
    except Exception as e:
        logger.error(f"Error analyzing review: {e}")
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

@app.route('/scrape', methods=['POST'])
def scrape_product():
    """Scrape product info from URL and generate a review using Gemini API."""
    try:
        # Get the URL from the request
        data = request.get_json()
        url = data.get('url', '')
        
        if not url:
            return jsonify({'error': 'No URL provided'}), 400
        
        # Check if the URL is valid
        try:
            parsed_url = urllib.parse.urlparse(url)
            if not parsed_url.scheme or not parsed_url.netloc:
                return jsonify({'error': 'Invalid URL format'}), 400
        except Exception:
            return jsonify({'error': 'Invalid URL'}), 400
        
        # Scrape the website content
        try:
            logger.debug(f"Attempting to scrape content from: {url}")
            
            # Try to fetch the URL content
            downloaded = trafilatura.fetch_url(url)
            
            # If that fails, return a more specific error message based on what happened
            if not downloaded:
                # Check if it's a bot protection issue (common with e-commerce sites)
                e_commerce_sites = [".flipkart.", ".amazon.", ".meesho.", ".myntra.", ".ebay.", ".walmart."]
                is_ecommerce = any(site in url.lower() for site in e_commerce_sites)
                
                if is_ecommerce:
                    logger.warning(f"Likely bot protection encountered on {url}")
                    message = (
                        "This e-commerce website has bot protection that prevents scraping. "
                        "Please try one of our sample URLs or another non-e-commerce website."
                    )
                    return jsonify({'error': message}), 429
                
                # Otherwise, it's a generic download error
                logger.error(f"Failed to download content from URL: {url}")
                return jsonify({'error': 'Failed to access this URL. Please try one of our sample URLs like Firefox Privacy, Smartphone Wiki, or Sony Headphones.'}), 400
            
            # Extract the content from the downloaded HTML    
            content = trafilatura.extract(downloaded)
            if not content or len(content) < 100:  # Check for minimum content length
                logger.error(f"Failed to extract meaningful content from URL: {url}")
                return jsonify({'error': 'Could not extract readable content from this URL. The page might not have enough text content or might be protected.'}), 400
                
            logger.debug(f"Successfully extracted content from URL. Length: {len(content)}")
        except Exception as e:
            logger.error(f"Error scraping website: {e}")
            return jsonify({'error': f'Error scraping website: {str(e)}. Try using a different URL.'}), 500
        
        # Create the prompt for Gemini to analyze the product
        prompt = f"""
        You are a product reviewer. I will provide you with content extracted from a product page.
        Based on this content, generate a comprehensive product review.

        Product page content:
        "{content[:8000]}"  # Limiting content length to avoid token limits

        Please write a detailed review of this product that includes:
        1. Product name and basic description
        2. Key features and specifications
        3. Perceived quality and build
        4. Value for money
        5. Target audience
        6. Overall assessment
        
        Keep the review balanced, honest, and informative. The length should be around 300-500 words.
        """
        
        # Generate review from Gemini
        response = model.generate_content(prompt)
        review_text = response.text
        
        # Now analyze this review using the existing analysis function
        analysis_prompt = f"""
        You are a product review analyzer with expertise in detecting fake reviews. Please analyze the following product review:
        
        "{review_text}"
        
        Please provide the following analysis in JSON format:
        1. Sentiment: Overall sentiment (positive, negative, or neutral)
        2. Score: A numerical score from 1-10
        3. Key Points: List of main points from the review (maximum 5)
        4. Strengths: Product strengths mentioned (maximum 3)
        5. Weaknesses: Product weaknesses mentioned (maximum 3)
        6. Summary: A brief summary of the review (maximum 2 sentences)
        7. Improvement Suggestions: Suggested improvements based on the review (maximum 2)
        8. ProductName: The name of the product
        9. Review: The full text of the generated review
        10. AuthenticityScore: A numerical score from 1-100 indicating how likely the review is genuine (where 100 is definitely genuine)
        11. AuthenticityAssessment: A brief assessment of whether the review seems authentic or potentially fabricated
        
        Return only a valid JSON object with these fields.
        """
        
        # Generate analysis response from Gemini
        analysis_response = model.generate_content(analysis_prompt)
        response_text = analysis_response.text
        
        # Extract JSON from the response
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            json_str = response_text.split("```")[1].strip()
        else:
            json_str = response_text
        
        # Clean the JSON string if needed
        json_str = json_str.replace('\n', ' ').strip()
        
        try:
            # Parse the JSON response
            analysis = json.loads(json_str)
            return jsonify(analysis)
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON: {e}")
            logger.debug(f"Response text: {response_text}")
            logger.debug(f"Extracted JSON string: {json_str}")
            return jsonify({
                'error': 'Failed to parse the response from Gemini API',
                'raw_response': response_text
            }), 500
            
    except Exception as e:
        logger.error(f"Error processing product URL: {e}")
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

@app.route('/health')
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
