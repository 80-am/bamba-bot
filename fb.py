from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time
import json
import re
from datetime import datetime
import openai
import os

def format_menu_with_openai(raw_menu_text):
    """Use OpenAI GPT to format the menu into a clean, readable list with emojis"""
    try:
        # Set up OpenAI client
        client = openai.OpenAI(
            api_key=os.getenv('OPENAI_KEY')
        )
        
        prompt = f"""
        You are a Swedish restaurant menu formatter. Convert this raw Swedish lunch menu text into a clean, emoji-formatted list.

        Rules:
        - Extract only the actual food items/dishes
        - Add appropriate food emojis before each item
        - Keep Swedish names but make them readable
        - If there are quantity limitations, add "(begränsad mängd!)" 
        - One dish per line
        - Remove any extra text like greetings, store info, etc.

        Raw menu text:
        {raw_menu_text}

        Format as a simple list with emojis, like:
        🌺 Hawaiikassler med ris
        🥧 Ost- & skinkpaj
        🐟 Fisksoppa
        """
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0.3
        )
        
        formatted_text = response.choices[0].message.content.strip()
        print(f"✅ OpenAI formatted menu successfully")
        return formatted_text
        
    except Exception as e:
        print(f"❌ OpenAI formatting failed: {e}")
        print("💡 Make sure to set OPENAI_API_KEY environment variable")
        # Fallback to original text
        return raw_menu_text

def clean_menu_text(text):
    """Clean up menu text by removing UI elements and extra whitespace"""
    # Remove common UI elements
    ui_elements = [
        "All reactions:",
        "from ICA Supermarket Hansa | Malmö",
        "Email or phone number",
        "Password"
    ]
    
    for element in ui_elements:
        text = text.replace(element, "")
    
    # Remove contact information patterns
    text = re.sub(r'\d{3}-\d{2} \d{2} \d{2}', '', text)  # Phone numbers
    text = re.sub(r'[a-zA-Z]+\.[a-zA-Z]+@[a-zA-Z]+\.[a-zA-Z]+', '', text)  # Email addresses
    text = re.sub(r'[a-zA-Z]+\.[a-zA-Z]+/[a-zA-Z]+', '', text)  # Website URLs
    
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def scrape_facebook_page(page_name, url):
    """Scrape a single Facebook page for lunch content"""
    # Set up headless Chrome
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        print(f"Loading {page_name}: {url}...")
        driver.get(url)
        
        # Wait for page to load
        time.sleep(5)
        
        # Scroll down multiple times to load more content (including older posts)
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        
        # Get all text content from the page
        page_text = driver.find_element(By.TAG_NAME, "body").text
        
        # Split into lines and look for lunch-related content
        lines = page_text.split('\n')
        
        # Debug: print all lines fetched from the page
        print("\n--- All lines fetched from Facebook page ---")
        for i, line in enumerate(lines):
            print(f"{i}: {line}")
        print("--- End of lines ---\n")
        
        # Look for lunch content - collect all relevant lines
        lunch_candidates = []
        
        # Broadened keyword search
        keywords = ["lunch", "lunchdags", "dagens", "idag", "serverar", "meny", "rätt"]
        for i, line in enumerate(lines):
            line = line.strip()
            if not line or len(line) < 20:
                continue
            if any(word in line.lower() for word in keywords):
                # Get context around the lunch mention
                start = max(0, i-1)
                end = min(len(lines), i+6)
                context_lines = []
                for j in range(start, end):
                    context_line = lines[j].strip()
                    if context_line and len(context_line) > 10:
                        context_lines.append(context_line)
                content = " ".join(context_lines)
                if len(content) > 50:
                    lunch_candidates.append(content)
        
        # Find the best lunch content (prefer longer descriptions)
        if lunch_candidates:
            best_content = max(lunch_candidates, key=len)
            cleaned_content = clean_menu_text(best_content)
            print(f"✅ Found lunch content for {page_name}")
            return cleaned_content
        else:
            print(f"❌ No lunch content found for {page_name}")
            return None
            
    except Exception as e:
        print(f"Error scraping {page_name}: {e}")
        return None
    finally:
        driver.quit()

def scrape_all_restaurants():
    """Scrape all restaurant pages and save to JSON"""
    restaurants = {
        "ICA Supermarket Hansa": "https://www.facebook.com/people/ICA-Supermarket-Hansa/100063773389377/"
    }
    
    menu_data = {}
    
    for restaurant_name, url in restaurants.items():
        content = scrape_facebook_page(restaurant_name, url)
        if content:
            formatted_content = format_menu_with_openai(content)
            menu_data[restaurant_name] = {
                "raw": content,
                "formatted": formatted_content
            }
    
    # Save to JSON file
    output_file = "menu.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(menu_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n📄 Menu saved to {output_file}")
    print("\nMenu content:")
    for restaurant, data in menu_data.items():
        print(f"\n{restaurant}:")
        print(f"  Raw: {data['raw']}")
        print(f"  Formatted: {data['formatted']}")

if __name__ == "__main__":
    scrape_all_restaurants()