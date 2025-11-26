import os # Add this line to read environment variables
import time
# ... rest of imports
import time
import requests
import json
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
import re
from google import genai 

# =======================================================
#               --- CONFIGURATION (REQUIRED UPDATES) ---
# =======================================================
# 1. *** REPLACE THIS with the EXACT secret string you put in the Google Form. ***
SECRET = os.environ.get("SECRET") 

# 2. *** REPLACE THIS with your actual Google/Gemini API Key (AIza...). ***
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") 

# 3. The Flask route where the evaluator will send the POST request
API_ENDPOINT_URL = "/quiz-api" 

# 4. LLM Model to use for analysis 
LLM_MODEL = "gemini-2.5-flash"
# =======================================================

app = Flask(__name__)
client = genai.Client(api_key=GEMINI_API_KEY)


def solve_quiz_task(email, secret, quiz_url):
    """The core logic to scrape, analyze, and submit the quiz answer."""
    print(f"--- Starting solver for URL: {quiz_url} ---")
    
    quiz_content = ""
    submit_url = ""

    # --- 1. Launch Headless Browser and Scrape Question ---
    try:
        with sync_playwright() as p:
            print("Launching Playwright browser...")
            browser = p.chromium.launch(headless=True) 
            page = browser.new_page()
            page.goto(quiz_url, wait_until="networkidle") 
            page.wait_for_selector("#result", timeout=15000) 
            
            quiz_content = page.inner_text("#result")
            browser.close()
            print("Scraping complete.")
            
            submit_match = re.search(r'Post your answer to (https?://[^\s]+)', quiz_content)
            if submit_match:
                submit_url = submit_match.group(1).rstrip('.')
            
    except Exception as e:
        print(f"Playwright/Scraping Error: {e}")
        return {"error": f"Scraping failed: {e}"}

    # --- 2. LLM Analysis and Answer Generation ---
    prompt = f"""
    You are an expert data analyst and quiz solver. Your goal is to solve the complex data task provided in the following quiz text.
    
    **Instructions:**
    1. Carefully read the "Quiz Content" below, including the question, any data links, and the required JSON payload format for the answer.
    2. Analyze the question and determine the single, final answer (which could be a number, string, or boolean).
    3. Respond ONLY with a valid JSON object in the following format: {{"answer": "..."}}. Do not include any other text or explanation.

    **Quiz Content:**
    ---
    {quiz_content}
    ---
    """
    
    final_answer = None
    try:
        response = client.models.generate_content(
            model=LLM_MODEL,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        
        llm_response_text = response.text.strip()
        llm_result = json.loads(llm_response_text)
        final_answer = llm_result.get("answer")
        
        if final_answer is None:
            raise ValueError("LLM response did not contain the 'answer' key.")

        print(f"LLM successfully generated answer: {final_answer}")

    except Exception as e:
        print(f"LLM Call/Parsing Error: {e}")
        return {"error": f"LLM analysis failed: {e}"}

    # --- 3. Submission ---
    if not submit_url:
        print("Could not find the submission URL. Cannot submit.")
        return {"status": "Analysis complete, submission failed (no submit URL found)"}

    final_payload = {
        "email": email,
        "secret": secret,
        "url": quiz_url,
        "answer": final_answer
    }

    try:
        print(f"Submitting answer to: {submit_url}")
        submit_response = requests.post(submit_url, json=final_payload)
        submit_data = submit_response.json()
        print(f"Submission Result: {submit_data}")

        # --- 4. Handle Response and Next Quiz ---
        
        if submit_data.get("correct") is True and submit_data.get("url"):
            print(f"CORRECT! Moving to next quiz: {submit_data['url']}")
            return solve_quiz_task(email, secret, submit_data["url"])
        
        elif submit_data.get("correct") is False and submit_data.get("url"):
            print(f"INCORRECT, skipping to new quiz: {submit_data['url']}")
            return solve_quiz_task(email, secret, submit_data["url"])
        
        return {"status": "Quiz chain complete or ended"}

    except Exception as e:
        print(f"Submission/Recurrence Error: {e}")
        return {"error": f"Submission failed: {e}"}


# =======================================================
#                  --- FLASK API ENDPOINT ---
# =======================================================

@app.route(API_ENDPOINT_URL, methods=['POST'])
def handle_quiz_request():
    """Handles the incoming POST request from the evaluator."""
    try:
        data = request.get_json()
        email = data.get("email")
        secret = data.get("secret")
        url = data.get("url")

        # 1. VERIFY SECRET (HTTP 403 Forbidden if wrong)
        if secret != SECRET:
            return jsonify({"error": "Invalid secret"}), 403

        if not url:
            # HTTP 400 Bad Request for missing data
            return jsonify({"error": "Missing quiz URL"}), 400

        # Run the solver function
        quiz_response = solve_quiz_task(email, secret, url) 
        
        # Return a successful acknowledgement to the evaluator
        return jsonify({"status": "Quiz solving initiated", "result_summary": quiz_response, "task_url": url}), 200

    except Exception as e:
        print(f"Server Error: {e}")
        return jsonify({"error": "Invalid JSON or Internal Server Error"}), 400

if __name__ == '__main__':
    print("Local Server Running...")
    # NOTE: We set debug=True to help find errors faster during this step.
    app.run(debug=True, host='0.0.0.0', port=5000)
